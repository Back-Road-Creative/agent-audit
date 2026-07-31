"""Workflow maturity — is each piece of your setup in the right form?

An AI-development setup accretes: a prompt that should have become a script, a
script that outgrew its skill, a pipeline that grew to twenty stages, a memory
file asserting things that stopped being true. This auditor classifies every
component against a maturity taxonomy and emits graduation signals.

Flow: glob the components, compute deterministic signals over them, then run
three parallel passes — each scoped to only the file domains it can speak to —
and aggregate.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import prompts, reporting, runner

#: Component domains and the globs that find them, relative to the target.
DISCOVERY_GLOBS: dict[str, list[str]] = {
    "skills": ["**/SKILL.md"],
    "agents": ["**/agents/*.md"],
    "memory": ["**/MEMORY.md"],
    "pipelines": ["**/pipeline*.py", "**/orchestrator*.py"],
    "config": [".mcp.json", ".claude/settings.json", "AGENTS.md"],
}

# Backup snapshots and test fixtures are not live components. Left in, they
# inflate every count with stale duplicates of the same handful of files and
# make the report look worse the more carefully you back things up.
DISCOVERY_EXCLUDE = ("/backups/", "/backup/", ".bak", "/evals/", "/fixtures/", "/node_modules/")

#: A definition longer than this is worth a second look regardless of verdict.
LONG_DEFINITION_LINES = 200

#: Memory older than this is flagged as worth re-verifying.
STALE_MEMORY_DAYS = 180

GRADUATION_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "currentCategory": {"type": "string", "enum": ["skill", "agent"]},
            "verdict": {"type": "string", "enum": ["STAY", "GRADUATE_CODE", "GRADUATE_AGENT"]},
            "rationale": {"type": "string"},
        },
        "required": ["name", "verdict", "rationale"],
    },
}

PIPELINE_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "file": {"type": "string"},
            "stages": {"type": "integer"},
            "couplingRisk": {"type": "string", "enum": ["low", "medium", "high"]},
            "subPipelineCandidates": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["file", "stages", "couplingRisk"],
    },
}

MEMORY_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "file": {"type": "string"},
            "stalenessRisk": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
            "staleClaimsFound": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string"},
                        "risk": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
                        "reason": {"type": "string"},
                    },
                    "required": ["claim", "risk"],
                },
            },
        },
        "required": ["file", "stalenessRisk"],
    },
}

#: ``(key, prompt name, schema, domains fed to that pass)``.
PASSES: list[tuple[str, str, dict[str, Any], list[str]]] = [
    ("graduation", "maturity_graduation", GRADUATION_SCHEMA, ["skills", "agents"]),
    ("pipeline", "maturity_pipeline", PIPELINE_SCHEMA, ["pipelines"]),
    ("memory", "maturity_memory", MEMORY_SCHEMA, ["memory"]),
]


def is_excluded(path: Path) -> bool:
    """True for backup snapshots, fixtures and vendored trees."""
    text = str(path)
    return any(fragment in text for fragment in DISCOVERY_EXCLUDE)


def discover_components(target_dir: str) -> dict[str, list[str]]:
    """Glob each component domain under ``target_dir``."""
    root = Path(target_dir).expanduser().resolve()
    components: dict[str, list[str]] = {}
    for domain, patterns in DISCOVERY_GLOBS.items():
        found: set[Path] = set()
        for pattern in patterns:
            if "*" in pattern:
                found.update(p for p in root.glob(pattern) if p.is_file() and not is_excluded(p))
            else:
                candidate = root / pattern
                if candidate.is_file() and not is_excluded(candidate):
                    found.add(candidate)
        components[domain] = sorted(str(p) for p in found)
    return components


def _age_days(path: Path, *, now: float | None = None) -> int | None:
    """Whole days since the file was last modified, or ``None`` if unknown."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    reference = dt.datetime.now().timestamp() if now is None else now
    return max(0, int((reference - mtime) // 86400))


def mechanical_signals(components: dict[str, list[str]]) -> dict[str, Any]:
    """Deterministic facts the passes should not have to re-derive.

    Length and last-modified date are measurements, not judgments. Computing
    them here keeps the model's attention on the classification and gives the
    report numbers that are true whether or not the passes succeed.
    """
    definitions: list[dict[str, Any]] = []
    for domain in ("skills", "agents"):
        for raw in components.get(domain, []):
            path = Path(raw)
            try:
                lines = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
            except OSError:
                lines = None
            definitions.append(
                {
                    "file": raw,
                    "domain": domain,
                    "lines": lines,
                    "over_budget": bool(lines and lines > LONG_DEFINITION_LINES),
                }
            )

    memory = []
    for raw in components.get("memory", []):
        age = _age_days(Path(raw))
        memory.append(
            {
                "file": raw,
                "age_days": age,
                "unverified_for": bool(age is not None and age > STALE_MEMORY_DAYS),
            }
        )

    return {
        "counts": {domain: len(paths) for domain, paths in sorted(components.items())},
        "definitions": sorted(definitions, key=lambda d: -(d["lines"] or 0)),
        "memory": sorted(memory, key=lambda m: -(m["age_days"] or 0)),
        "long_definition_lines": LONG_DEFINITION_LINES,
        "stale_memory_days": STALE_MEMORY_DAYS,
    }


def build_prompt(prompt_name: str, files: list[str], signals: dict[str, Any], args: Any) -> str:
    """Prompt for one maturity pass, scoped to its own file domains."""
    return "\n\n".join(
        [
            prompts.load(prompt_name, prompt_dir=getattr(args, "prompt_dir", None)),
            prompts.file_list_block("COMPONENT FILES", files),
            prompts.json_block("MECHANICAL SIGNALS", signals),
            prompts.schema_reminder("an object whose `items` array holds one entry per component"),
        ]
    )


def build_tasks(
    components: dict[str, list[str]], signals: dict[str, Any], args: Any
) -> list[tuple[str, str, dict[str, Any]]]:
    """One task per pass, each seeing only the files its domains contain."""
    tasks = []
    for key, prompt_name, schema, domains in PASSES:
        files = [f for domain in domains for f in components.get(domain, [])]
        tasks.append((key, build_prompt(prompt_name, files, signals, args), schema))
    return tasks


def write_report(
    *,
    output: Path,
    date: str,
    target_dir: str,
    components: dict[str, list[str]],
    signals: dict[str, Any],
    results: dict[str, dict[str, Any]],
) -> Path:
    """Render the workflow-maturity report; return the path written."""
    gaps = runner.coverage_gaps(results)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        counts = ", ".join(f"{d}: {len(v)}" for d, v in sorted(components.items()))
        f.write("# Workflow maturity audit\n\n")
        f.write(f"**Date:** {date} | **Target:** {target_dir}\n\n")
        f.write(f"**Discovered:** {counts}\n\n")

        f.write("## Mechanical signals\n\n")
        over_budget = [d for d in signals.get("definitions", []) if d.get("over_budget")]
        unverified = [m for m in signals.get("memory", []) if m.get("unverified_for")]
        f.write(
            f"- Definitions over {signals.get('long_definition_lines')} lines: {len(over_budget)}\n"
        )
        f.write(
            f"- Memory files untouched for over {signals.get('stale_memory_days')} days: "
            f"{len(unverified)}\n\n"
        )
        if over_budget:
            f.write("| Long definition | Lines |\n|---|---|\n")
            for row in over_budget:
                f.write(f"| {reporting.cell(row['file'])} | {row['lines']} |\n")
            f.write("\n")

        f.write("## Graduation assessment\n\n")
        graduations = runner.rows(results.get("graduation", {}))
        if graduations:
            f.write("| Name | Category | Verdict | Rationale |\n|---|---|---|---|\n")
            for row in graduations:
                f.write(
                    f"| {reporting.cell(row.get('name'))} "
                    f"| {reporting.cell(row.get('currentCategory')) or '—'} "
                    f"| {reporting.cell(row.get('verdict'))} "
                    f"| {reporting.cell(row.get('rationale'))} |\n"
                )
            f.write("\n")
        else:
            f.write("_No assessments returned._\n\n")

        f.write("## Pipeline health\n\n")
        pipelines = runner.rows(results.get("pipeline", {}))
        if pipelines:
            f.write("| Pipeline | Stages | Coupling | Sub-pipeline candidates |\n")
            f.write("|---|---|---|---|\n")
            for row in pipelines:
                candidates = ", ".join(row.get("subPipelineCandidates", []))
                f.write(
                    f"| {reporting.cell(row.get('file'))} | {row.get('stages', '—')} "
                    f"| {reporting.cell(row.get('couplingRisk')) or '—'} "
                    f"| {reporting.cell(candidates) or '—'} |\n"
                )
            f.write("\n")
        else:
            f.write("_No pipelines assessed._\n\n")

        f.write("## Memory staleness\n\n")
        memory = runner.rows(results.get("memory", {}))
        if memory:
            f.write("| File | Risk | Stale claims |\n|---|---|---|\n")
            for row in memory:
                claims = row.get("staleClaimsFound", []) or []
                summary = (
                    "; ".join(f"{c.get('risk', '?')}: {c.get('claim', '')}" for c in claims) or "—"
                )
                f.write(
                    f"| {reporting.cell(row.get('file'))} "
                    f"| {reporting.cell(row.get('stalenessRisk')) or '—'} "
                    f"| {reporting.cell(summary)} |\n"
                )
            f.write("\n")
        else:
            f.write("_No memory files assessed._\n\n")

        reporting.write_coverage_gaps(f, gaps)
    return output


def run(args: Any, *, call: Callable[..., dict[str, Any]] = runner.call_claude) -> int:
    """Entry point for the ``maturity`` command."""
    date = reporting.today()
    components = discover_components(args.target_dir)
    signals = mechanical_signals(components)
    total = sum(len(v) for v in components.values())
    print(f"Discovered {total} component(s) under {args.target_dir}")

    tasks = build_tasks(components, signals, args)
    results = runner.fan_out(tasks, budget_usd=args.budget_usd, model=args.model, call=call)

    output = reporting.resolve_output(
        args.output,
        report_dir=args.report_dir,
        target=args.target_dir,
        kind="workflow-maturity",
        date=date,
    )
    write_report(
        output=output,
        date=date,
        target_dir=args.target_dir,
        components=components,
        signals=signals,
        results=results,
    )
    print(f"Report written: {output}")
    return 0
