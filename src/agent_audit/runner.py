"""The single boundary between this package and the ``claude`` CLI.

Everything that shells out lives here, so the rest of the package is pure
functions over data and the test suite can run without the CLI installed.

Each analysis pass is one ``claude -p`` subprocess constrained by
``--json-schema``. Passes are independent, so they run concurrently in a
thread pool; a pass that fails is recorded as a coverage gap rather than
aborting the run, because a partial report with an honest hole in it beats
no report at all.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
from collections.abc import Callable
from typing import Any

#: Executable resolved on PATH. Override with ``$AGENT_AUDIT_CLAUDE_BIN``.
CLAUDE_BIN = os.environ.get("AGENT_AUDIT_CLAUDE_BIN", "claude")

#: Wall-clock ceiling for a single pass. Override with ``$AGENT_AUDIT_TIMEOUT_S``.
DEFAULT_TIMEOUT_S = int(os.environ.get("AGENT_AUDIT_TIMEOUT_S", "600"))

# ``--max-budget-usd`` is a *computed* cost ceiling, not a bill. It exists only
# to stop a runaway loop: when it trips, the pass aborts and its section of the
# report comes back empty, so setting it low silently guts the output. Even a
# trivial prompt computes a few tens of cents because the injected system
# prompt dominates cache-creation, so the default is deliberately generous.
DEFAULT_BUDGET_USD = 5.00


class AgentError(RuntimeError):
    """An analysis pass failed, timed out, or returned unparseable output."""


def as_object_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Wrap a top-level-array schema in an ``{"items": [...]}`` object envelope.

    ``--json-schema`` is handed to the model as a tool input schema, which must
    have top-level ``type: object``. A top-level array is rejected, and the
    model then retries the impossible schema until the budget trips — surfacing
    as a bare non-zero exit with no useful message. Wrapping avoids that;
    :func:`rows` unwraps the result.
    """
    if schema.get("type") == "array":
        return {"type": "object", "properties": {"items": schema}, "required": ["items"]}
    return schema


def failure_detail(proc: subprocess.CompletedProcess[str]) -> str | None:
    """Describe a failed run, or ``None`` when it succeeded.

    Two traps make the exit code alone unreliable:

    * A budget or policy stop arrives as a JSON envelope on **stdout** with
      ``is_error`` set and **stderr empty** — so an error message built from
      stderr renders as "failed:" with nothing after it.
    * ``is_error`` can arrive alongside exit code 0.

    So both channels are inspected.
    """
    try:
        envelope = json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError):
        envelope = None
    if not isinstance(envelope, dict):
        envelope = None
    if proc.returncode == 0 and not (envelope or {}).get("is_error"):
        return None
    if envelope is None:
        detail = (proc.stderr or "").strip()[:400] or "(no stderr, no JSON envelope on stdout)"
        return f"exit {proc.returncode}: {detail}"
    bits = [f"{k}={envelope[k]}" for k in ("subtype", "terminal_reason") if envelope.get(k)]
    errors = envelope.get("errors") or []
    if errors:
        errors = errors if isinstance(errors, list) else [errors]
        bits.append("errors=" + "; ".join(str(e) for e in errors))
    return f"exit {proc.returncode}, " + (", ".join(bits) or "is_error=True")[:600]


def build_command(
    prompt: str,
    schema: dict[str, Any] | None,
    *,
    budget_usd: float,
    model: str | None = None,
) -> list[str]:
    """Assemble the ``claude -p`` argv for one analysis pass."""
    cmd = [
        CLAUDE_BIN,
        "-p",
        prompt,
        "--output-format",
        "json",
        "--max-budget-usd",
        str(budget_usd),
        "--no-session-persistence",
    ]
    if model:
        cmd += ["--model", model]
    if schema is not None:
        cmd += ["--json-schema", json.dumps(as_object_schema(schema))]
    return cmd


def call_claude(
    prompt: str,
    schema: dict[str, Any] | None,
    *,
    budget_usd: float = DEFAULT_BUDGET_USD,
    model: str | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Run one analysis pass and return the parsed result envelope.

    Raises :class:`AgentError` on timeout, failure, or unparseable output.
    """
    cmd = build_command(prompt, schema, budget_usd=budget_usd, model=model)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    except FileNotFoundError as exc:
        raise AgentError(
            f"`{CLAUDE_BIN}` not found on PATH — install the Claude Code CLI, "
            f"or set $AGENT_AUDIT_CLAUDE_BIN to its location"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise AgentError(f"pass timed out after {timeout_s}s: {exc}") from exc
    detail = failure_detail(proc)
    if detail is not None:
        raise AgentError(f"pass failed: {detail}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AgentError(f"pass returned non-JSON: {exc}") from exc


def output(envelope: dict[str, Any]) -> dict[str, Any]:
    """Structured output of a successful envelope, or ``{}``."""
    result = envelope.get("structured_output")
    return result if isinstance(result, dict) else {}


def rows(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    """List payload of an envelope, unwrapping the :func:`as_object_schema` box."""
    result = envelope.get("structured_output")
    if isinstance(result, dict):
        result = result.get("items")
    return result if isinstance(result, list) else []


def fan_out(
    tasks: list[tuple[str, str, dict[str, Any] | None]],
    *,
    budget_usd: float = DEFAULT_BUDGET_USD,
    model: str | None = None,
    call: Callable[..., dict[str, Any]] = call_claude,
) -> dict[str, dict[str, Any]]:
    """Run ``(key, prompt, schema)`` passes concurrently, keyed by ``key``.

    A pass that raises :class:`AgentError` yields ``{"_error": "<message>"}``
    so the aggregator can print it under "Coverage gaps" instead of pretending
    the section was clean.
    """
    if not tasks:
        return {}
    results: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = {
            pool.submit(call, prompt, schema, budget_usd=budget_usd, model=model): key
            for key, prompt, schema in tasks
        }
        for future in concurrent.futures.as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except AgentError as exc:
                results[key] = {"_error": str(exc)}
    return results


def coverage_gaps(results: dict[str, dict[str, Any]]) -> list[str]:
    """``"<key>: <error>"`` for every pass that failed, in stable order."""
    return [f"{key}: {env['_error']}" for key, env in sorted(results.items()) if "_error" in env]
