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

#: The only built-in tools an analysis pass may use: read files, search them.
#: The files being audited are untrusted input — they can carry instructions
#: aimed at the auditor — so the boundary is enforced by the launcher, below
#: the prompt, not by asking the model to behave.
READ_ONLY_TOOLS: tuple[str, ...] = ("Read", "Grep", "Glob")

#: Tools named in ``--disallowedTools`` as a second line of defence: anything
#: that writes, executes, or reaches the network.
DENIED_TOOLS: tuple[str, ...] = (
    "Bash",
    "Edit",
    "Write",
    "MultiEdit",
    "NotebookEdit",
    "WebFetch",
    "WebSearch",
)

#: Flags that would widen the capability set. :func:`assert_read_only` refuses a
#: command carrying any of them, whoever added it.
_WIDENING_FLAGS = (
    "--allowedTools",
    "--allowed-tools",
    "--dangerously-skip-permissions",
    "--allow-dangerously-skip-permissions",
    "--permission-mode",
    "--mcp-config",
    "--add-dir",
)


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


#: Validation problems reported per pass before the rest are summarised as a count.
MAX_SCHEMA_PROBLEMS = 5


def _json_type(value: Any) -> str:
    """JSON-schema name of a decoded JSON value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _type_matches(value: Any, expected: str) -> bool:
    actual = _json_type(value)
    return actual == expected or (expected == "number" and actual == "integer")


def schema_problems(value: Any, schema: dict[str, Any], path: str) -> list[str]:
    """Where ``value`` departs from ``schema``, as ``"<path>: <problem>"`` lines.

    Checks the subset of JSON Schema this package's own schemas use — ``type``
    (including a list of types), ``required``, ``properties`` and ``items``.
    Enums and formats are not enforced: a value the model chose badly is still
    a graded result, whereas a missing or wrong-shaped one is not.
    """
    expected = schema.get("type")
    if expected is not None:
        allowed = [expected] if isinstance(expected, str) else list(expected)
        if not any(_type_matches(value, t) for t in allowed):
            return [f"{path}: expected {' or '.join(allowed)}, got {_json_type(value)}"]
    problems: list[str] = []
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                problems.append(f"{path}.{name}: required field missing")
        for name, sub in (schema.get("properties") or {}).items():
            if name in value and isinstance(sub, dict):
                problems += schema_problems(value[name], sub, f"{path}.{name}")
    elif isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            problems += schema_problems(item, schema["items"], f"{path}[{index}]")
    return problems


def validate_result(envelope: dict[str, Any], schema: dict[str, Any] | None) -> None:
    """Raise :class:`AgentError` unless ``envelope`` carries a well-shaped result.

    An empty findings list that matches the schema is a real answer ("nothing
    found") and passes. A missing, null or wrong-shaped ``structured_output`` is
    not an answer at all: the pass was never graded, and reading it as "no
    findings" would print a clean report over a hole.
    """
    if schema is None:
        return
    value = envelope.get("structured_output")
    if value is None:
        raise AgentError(
            "pass returned no structured_output "
            f"(envelope keys: {', '.join(sorted(envelope)) or 'none'}); it was not graded"
        )
    # :func:`rows` also accepts a bare list for a boxed array schema; so does this.
    if schema.get("type") == "array" and isinstance(value, list):
        target = schema
    else:
        target = as_object_schema(schema)
    problems = schema_problems(value, target, "structured_output")
    if problems:
        shown = problems[:MAX_SCHEMA_PROBLEMS]
        extra = len(problems) - len(shown)
        if extra:
            shown.append(f"(+{extra} more)")
        raise AgentError("pass returned malformed structured_output: " + "; ".join(shown))


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
        # ``=`` form: these flags take variadic values, and a bare value list
        # would swallow whatever argument follows it.
        f"--tools={','.join(READ_ONLY_TOOLS)}",
        f"--disallowedTools={','.join(DENIED_TOOLS)}",
        "--strict-mcp-config",
    ]
    if model:
        cmd += ["--model", model]
    if schema is not None:
        cmd += ["--json-schema", json.dumps(as_object_schema(schema))]
    return cmd


def _flag_values(cmd: list[str], flag: str) -> list[str] | None:
    """Comma-split values of ``--flag=a,b`` / ``--flag a,b`` in ``cmd``, or ``None``."""
    for i, token in enumerate(cmd):
        if token == flag and i + 1 < len(cmd):
            return [v for v in cmd[i + 1].split(",") if v]
        if token.startswith(flag + "="):
            return [v for v in token.split("=", 1)[1].split(",") if v]
    return None


def assert_read_only(cmd: list[str]) -> None:
    """Refuse to launch a command that does not carry the read-only restrictions.

    Raises :class:`AgentError` rather than running unrestricted, so a future
    change to :func:`build_command` that drops or widens the boundary fails
    loudly instead of silently handing untrusted input a writable agent.
    """
    tools = _flag_values(cmd, "--tools")
    denied = _flag_values(cmd, "--disallowedTools")
    problems = []
    if tools is None or not set(tools) <= set(READ_ONLY_TOOLS):
        problems.append(f"--tools must be a subset of {','.join(READ_ONLY_TOOLS)}")
    if denied is None or not set(DENIED_TOOLS) <= set(denied):
        problems.append("--disallowedTools must name every write/execute/network tool")
    if "--strict-mcp-config" not in cmd:
        problems.append("--strict-mcp-config is missing")
    for token in cmd:
        flag = token.split("=", 1)[0]
        if flag in _WIDENING_FLAGS:
            problems.append(f"{flag} widens the capability set")
    if problems:
        raise AgentError(
            "refusing to launch: command is not read-only (" + "; ".join(problems) + ")"
        )


def call_claude(
    prompt: str,
    schema: dict[str, Any] | None,
    *,
    budget_usd: float = DEFAULT_BUDGET_USD,
    model: str | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Run one analysis pass and return the parsed result envelope.

    Raises :class:`AgentError` on timeout, failure, unparseable output, or — when
    a ``schema`` was requested — a missing or wrong-shaped ``structured_output``.
    """
    cmd = build_command(prompt, schema, budget_usd=budget_usd, model=model)
    assert_read_only(cmd)
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
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AgentError(f"pass returned non-JSON: {exc}") from exc
    if not isinstance(envelope, dict):
        raise AgentError(f"pass result is not a JSON object (got {_json_type(envelope)})")
    validate_result(envelope, schema)
    return envelope


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
