"""Instruction audit — contradictions, effectiveness and context cost.

Instruction files are the standing rules loaded before every request: agent
instruction files, rule files, memory files, command definitions. They are paid
for on every turn and, unlike code, nothing type-checks them, so they rot
quietly — two rules that disagree, a rule about a system that no longer exists,
a paragraph that could be a sentence.

Flow: glob the instruction-bearing files, measure them deterministically, then
run three parallel passes — contradictions, effectiveness scoring, context
optimisation — and aggregate.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import prompts, reporting, runner

#: Well-known instruction filenames, checked at the target root.
GOVERNANCE_FILENAMES = [
    "AGENTS.md",
    "CLAUDE.md",
    ".cursorrules",
    ".windsurfrules",
    ".clinerules",
    ".continuerules",
    "copilot-instructions.md",
]

#: Instruction-bearing files found by pattern anywhere under the target.
GLOB_PATTERNS = [
    ".claude/skills/**/*.md",
    ".claude/commands/**/*.md",
    ".github/copilot-instructions.md",
    "_governance/**/*.md",
    "**/MEMORY.md",
]

# A context window is measured in tokens, but token counts are model-specific
# and counting them properly would mean a tokeniser dependency. Four characters
# per token is the standard rough figure for English prose and is accurate
# enough to rank files by cost, which is all the optimisation pass needs.
CHARS_PER_TOKEN = 4

#: Denominator for the "percentage of context" figure. Override with --context-window.
DEFAULT_CONTEXT_WINDOW = 200_000

CONTRADICTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
                    "locations": {"type": "string"},
                    "directives": {"type": "string"},
                    "resolution": {"type": "string"},
                },
                "required": ["severity", "directives"],
            },
        }
    },
    "required": ["findings"],
}

EFFECTIVENESS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "clarity": {"type": "number"},
                    "specificity": {"type": "number"},
                    "enforceability": {"type": "number"},
                    "coverage": {"type": "number"},
                },
                "required": ["file"],
            },
        },
        "top_improvements": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["files", "top_improvements"],
}

OPTIMIZATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "opportunities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "description": {"type": "string"},
                    "est_savings_tokens": {"type": ["integer", "null"]},
                },
                "required": ["category", "description"],
            },
        },
        "total_savings_tokens": {"type": ["integer", "null"]},
        "projected_context_pct": {"type": ["number", "null"]},
    },
    "required": ["opportunities"],
}

#: ``(key, prompt name, schema)`` for each parallel pass.
PASSES: list[tuple[str, str, dict[str, Any]]] = [
    ("contradictions", "instructions_contradictions", CONTRADICTION_SCHEMA),
    ("effectiveness", "instructions_effectiveness", EFFECTIVENESS_SCHEMA),
    ("optimization", "instructions_optimization", OPTIMIZATION_SCHEMA),
]


def discover_instruction_files(target_dir: str) -> list[str]:
    """Every instruction-bearing file under ``target_dir``, sorted."""
    root = Path(target_dir).expanduser().resolve()
    found: set[Path] = set()
    for name in GOVERNANCE_FILENAMES:
        candidate = root / name
        if candidate.is_file():
            found.add(candidate)
    for pattern in GLOB_PATTERNS:
        found.update(p for p in root.glob(pattern) if p.is_file())
    return sorted(str(p) for p in found)


def measure(files: list[str], *, context_window: int = DEFAULT_CONTEXT_WINDOW) -> dict[str, Any]:
    """Deterministic size baseline for the discovered files.

    Computed here rather than asked of a model: a byte count is not a judgment
    call, and grounding the optimisation pass in real numbers is what stops it
    inventing savings.
    """
    rows: list[dict[str, Any]] = []
    for path in files:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            rows.append({"file": path, "error": str(exc)})
            continue
        rows.append(
            {
                "file": path,
                "lines": len(text.splitlines()),
                "chars": len(text),
                "est_tokens": len(text) // CHARS_PER_TOKEN,
            }
        )
    total_tokens = sum(int(r.get("est_tokens", 0)) for r in rows)
    return {
        "file_count": len(files),
        "total_chars": sum(int(r.get("chars", 0)) for r in rows),
        "total_est_tokens": total_tokens,
        "context_window": context_window,
        "context_pct": round(100 * total_tokens / context_window, 2) if context_window else None,
        "files": sorted(rows, key=lambda r: -int(r.get("est_tokens", 0))),
    }


def build_prompt(prompt_name: str, files: list[str], baseline: dict[str, Any], args: Any) -> str:
    """Prompt for one instruction-audit pass."""
    return "\n\n".join(
        [
            prompts.load(prompt_name, prompt_dir=getattr(args, "prompt_dir", None)),
            prompts.file_list_block("INSTRUCTION FILES", files),
            prompts.json_block("MECHANICAL BASELINE", baseline),
            prompts.schema_reminder("the supplied object shape"),
        ]
    )


def write_report(
    *,
    output: Path,
    date: str,
    target_dir: str,
    files: list[str],
    baseline: dict[str, Any],
    results: dict[str, dict[str, Any]],
) -> Path:
    """Render the instruction-audit report; return the path written."""
    gaps = runner.coverage_gaps(results)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        f.write("# Instruction audit report\n\n")
        f.write(f"**Date:** {date} | **Target:** {target_dir} | **Files:** {len(files)}\n\n")

        f.write("## Mechanical baseline\n\n")
        f.write(f"- Files discovered: {baseline.get('file_count', 0)}\n")
        f.write(
            f"- Estimated tokens: {baseline.get('total_est_tokens', 0)} "
            f"({baseline.get('context_pct', '—')}% of a "
            f"{baseline.get('context_window', 0):,}-token window)\n\n"
        )
        if baseline.get("files"):
            f.write("| File | Lines | Est. tokens |\n|---|---|---|\n")
            for row in baseline["files"]:
                f.write(
                    f"| {reporting.cell(row.get('file'))} | {row.get('lines', '—')} "
                    f"| {row.get('est_tokens', '—')} |\n"
                )
            f.write("\n")

        f.write("## Semantic contradictions\n\n")
        contradictions = runner.output(results.get("contradictions", {})).get("findings", [])
        if contradictions:
            f.write("| Severity | Location | Conflicting directives | Resolution |\n")
            f.write("|---|---|---|---|\n")
            for row in contradictions:
                f.write(
                    f"| {reporting.cell(row.get('severity'))} "
                    f"| {reporting.cell(row.get('locations'))} "
                    f"| {reporting.cell(row.get('directives'))} "
                    f"| {reporting.cell(row.get('resolution'))} |\n"
                )
            f.write("\n")
        else:
            f.write("_None reported._\n\n")

        f.write("## Effectiveness scores\n\n")
        effectiveness = runner.output(results.get("effectiveness", {}))
        rows = effectiveness.get("files", [])
        if rows:
            f.write("| File | Clarity | Specificity | Enforceability | Coverage |\n")
            f.write("|---|---|---|---|---|\n")
            for row in rows:
                f.write(
                    f"| {reporting.cell(row.get('file'))} | {row.get('clarity', '—')} "
                    f"| {row.get('specificity', '—')} | {row.get('enforceability', '—')} "
                    f"| {row.get('coverage', '—')} |\n"
                )
            f.write("\n### Top improvements\n\n")
            for improvement in effectiveness.get("top_improvements", []):
                f.write(f"- {improvement}\n")
            f.write("\n")
        else:
            f.write("_No scores returned._\n\n")

        f.write("## Context optimisation\n\n")
        optimization = runner.output(results.get("optimization", {}))
        opportunities = optimization.get("opportunities", [])
        if opportunities:
            f.write("| Category | Opportunity | Est. saving (tokens) |\n|---|---|---|\n")
            for row in opportunities:
                f.write(
                    f"| {reporting.cell(row.get('category'))} "
                    f"| {reporting.cell(row.get('description'))} "
                    f"| {row.get('est_savings_tokens', '—')} |\n"
                )
            total = optimization.get("total_savings_tokens")
            projected = optimization.get("projected_context_pct")
            f.write(f"\n**Total potential saving:** {total if total is not None else '—'} tokens")
            if projected is not None:
                f.write(f" (projected {projected}% of context)")
            f.write("\n\n")
        else:
            f.write("_No opportunities returned._\n\n")

        reporting.write_coverage_gaps(f, gaps)
    return output


def run(args: Any, *, call: Callable[..., dict[str, Any]] = runner.call_claude) -> int:
    """Entry point for the ``instructions`` command."""
    date = reporting.today()
    files = discover_instruction_files(args.target_dir)
    baseline = measure(files, context_window=args.context_window)

    print(f"Discovered {len(files)} instruction file(s) under {args.target_dir}")
    if not files:
        print("Nothing to analyse — no instruction files found.")

    tasks = [
        (key, build_prompt(prompt_name, files, baseline, args), schema)
        for key, prompt_name, schema in PASSES
    ]
    results = runner.fan_out(tasks, budget_usd=args.budget_usd, model=args.model, call=call)

    output = reporting.resolve_output(
        args.output,
        report_dir=args.report_dir,
        target=args.target_dir,
        kind="instruction-audit",
        date=date,
    )
    write_report(
        output=output,
        date=date,
        target_dir=args.target_dir,
        files=files,
        baseline=baseline,
        results=results,
    )
    print(f"Report written: {output}")
    return 0
