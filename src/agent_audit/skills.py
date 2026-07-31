"""Skill audit — structure, security, quality and determinism of skill definitions.

Flow:

1. Glob the target directories into a manifest (:mod:`.discovery`).
2. Run the deterministic structural checks (:mod:`.structural`).
3. Fan out security / quality / determinism passes in parallel.
4. Run one cross-skill pass over the manifest plus those findings.
5. Aggregate everything into a markdown report.

``manifest`` stops after step 1; ``diff`` compares two skill sets using steps 1
and 2 only, with no model involved at all.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import discovery, prompts, reporting, runner, structural

#: Passes that run in parallel over the whole manifest.
ANALYSIS_PASSES = ["security", "quality", "determinism"]

#: Everything ``--focus`` accepts, including the deterministic-only stages.
FOCUS_CHOICES = [*ANALYSIS_PASSES, "structural", "cross"]

DEFAULT_STALENESS_DAYS = 90

#: One summary line plus a flat list of findings.
FINDINGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string"},
                    "skill": {"type": "string"},
                    "description": {"type": "string"},
                    "fix": {"type": "string"},
                },
                "required": ["severity", "description"],
            },
        },
    },
    "required": ["summary", "findings"],
}

#: Sections, each with a kind; the dependency section also carries a diagram.
CROSS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string"},
                    "mermaid": {"type": "string"},
                    "findings": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["kind"],
            },
        },
    },
    "required": ["sections"],
}


def flags_line(args: Any) -> str:
    """Human-readable summary of the flags that shaped this run."""
    bits = [
        f"--complexity-budget {args.complexity_budget}",
        f"--staleness-days {args.staleness_days}",
    ]
    if getattr(args, "fix_suggestions", False):
        bits.append("--fix-suggestions")
    return "Active flags: " + ", ".join(bits)


def build_analysis_prompt(pass_key: str, manifest: dict[str, Any], args: Any) -> str:
    """Prompt for one per-skill analysis pass."""
    body = prompts.load(f"skills_{pass_key}", prompt_dir=getattr(args, "prompt_dir", None))
    fix_note = (
        "Include a concrete `fix` on every finding."
        if getattr(args, "fix_suggestions", False)
        else "The `fix` field is optional on this run."
    )
    return "\n\n".join(
        [
            body,
            prompts.json_block("SKILL MANIFEST", manifest),
            flags_line(args),
            fix_note,
            prompts.schema_reminder("a summary string and a findings array"),
        ]
    )


def build_cross_prompt(
    manifest: dict[str, Any], analysis: dict[str, dict[str, Any]], args: Any
) -> str:
    """Prompt for the cross-skill pass, fed the per-skill findings."""
    per_pass = {
        key: env.get("structured_output", {"_error": env.get("_error")})
        for key, env in analysis.items()
    }
    return "\n\n".join(
        [
            prompts.load("skills_cross", prompt_dir=getattr(args, "prompt_dir", None)),
            prompts.json_block("SKILL MANIFEST", manifest),
            prompts.json_block("PER-SKILL FINDINGS", per_pass),
            flags_line(args),
            prompts.schema_reminder("a sections array"),
        ]
    )


def select_passes(focus: str | None) -> list[str]:
    """Which parallel passes to run for the given ``--focus``."""
    if focus in {"structural", "cross"}:
        return []
    if focus:
        return [focus]
    return list(ANALYSIS_PASSES)


def findings_by_skill(analysis: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Flatten every pass's findings into ``{skill: [finding, ...]}``."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for pass_key, envelope in sorted(analysis.items()):
        for finding in runner.output(envelope).get("findings", []):
            row = dict(finding)
            row["_pass"] = pass_key
            grouped.setdefault(finding.get("skill", "(unattributed)"), []).append(row)
    return grouped


def write_report(
    *,
    output: Path,
    date: str,
    manifest: dict[str, Any],
    structural_rows: list[dict[str, Any]],
    analysis: dict[str, dict[str, Any]],
    cross: dict[str, Any],
    args: Any,
) -> Path:
    """Render the full skill-audit report; return the path written."""
    by_name = {row["name"]: row for row in structural_rows}
    llm_findings = findings_by_skill(analysis)
    gaps = runner.coverage_gaps(analysis)
    if not cross and getattr(args, "focus", None) in (None, "cross"):
        gaps.append("cross: no parseable sections returned")

    verdicts = [row["verdict"] for row in structural_rows]

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        f.write("# Skill audit report\n\n")
        f.write(f"**Date:** {date}\n\n")
        f.write(f"**Scanned:** {', '.join(manifest.get('directories_scanned', [])) or '—'}\n\n")
        f.write(f"**{flags_line(args)}**\n\n")

        agent_count = manifest.get("agent_count", 0)
        f.write("## Summary\n\n")
        f.write(
            f"- Skills discovered: {manifest.get('skill_count', 0)} "
            f"(plus {agent_count} agent{'' if agent_count == 1 else 's'})\n"
        )
        f.write(
            f"- Structural pass / warn / fail (skills and agents): {verdicts.count('PASS')} / "
            f"{verdicts.count('WARN')} / {verdicts.count('FAIL')}\n\n"
        )

        f.write("## Manifest\n\n| # | Skill | Source | Structural |\n|---|---|---|---|\n")
        for i, skill in enumerate(manifest.get("skills", []), 1):
            name = skill.get("name", "?")
            verdict = by_name.get(name, {}).get("verdict", "—")
            f.write(
                f"| {i} | {reporting.cell(name)} | {reporting.cell(skill.get('source'))} "
                f"| {verdict} |\n"
            )
        f.write("\n")

        f.write("## Per-skill scorecards\n\n")
        for skill in manifest.get("skills", []):
            name = skill.get("name", "?")
            row = by_name.get(name, {})
            f.write(f"### {name}\n\n")
            f.write(
                f"- **Structural:** {row.get('verdict', '—')} — "
                f"{row.get('rationale', 'not evaluated')}\n"
            )
            for evidence in row.get("evidence", []):
                f.write(f"  - {evidence}\n")
            for finding in llm_findings.get(name, []):
                f.write(
                    f"- **{finding.get('_pass', '?')} / {finding.get('severity', '?')}:** "
                    f"{str(finding.get('description', '')).strip()}\n"
                )
                if finding.get("fix"):
                    f.write(f"  - **Fix:** {str(finding['fix']).strip()}\n")
            f.write("\n")

        unattributed = llm_findings.get("(unattributed)", [])
        if unattributed:
            f.write("### Unattributed findings\n\n")
            for finding in unattributed:
                f.write(
                    f"- **{finding.get('_pass', '?')} / {finding.get('severity', '?')}:** "
                    f"{str(finding.get('description', '')).strip()}\n"
                )
            f.write("\n")

        f.write("## Cross-skill findings\n\n")
        sections = cross.get("sections", [])
        if not sections:
            f.write("_No cross-skill sections returned._\n\n")
        for section in sections:
            f.write(f"### {section.get('kind', 'section')}\n\n")
            if section.get("mermaid"):
                f.write(f"```mermaid\n{section['mermaid']}\n```\n\n")
            entries = section.get("findings", [])
            if not entries:
                f.write("_Nothing to report._\n")
            for finding in entries:
                skills = finding.get("skills") or finding.get("skill")
                label = f"`{skills}` — " if skills else ""
                f.write(f"- {label}{reporting.cell(finding.get('description'))}\n")
            f.write("\n")

        reporting.write_coverage_gaps(f, gaps)

    if getattr(args, "as_json", False):
        sidecar = output.with_suffix(".json")
        sidecar.write_text(
            json.dumps(
                {
                    "generated": date,
                    "manifest": manifest,
                    "structural": structural_rows,
                    "analysis": {
                        key: env.get("structured_output", {"_error": env.get("_error")})
                        for key, env in analysis.items()
                    },
                    "cross": cross,
                    "coverage_gaps": gaps,
                },
                indent=2,
                sort_keys=True,
                default=str,
            ),
            encoding="utf-8",
        )
    return output


def write_manifest(manifest: dict[str, Any], output: Path) -> Path:
    """Write the raw manifest as JSON; returns the ``.json`` path actually used."""
    path = output if output.suffix == ".json" else output.with_suffix(".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return path


def diff_skill_sets(
    dir_a: str,
    dir_b: str,
    budget: int,
    *,
    discover: Callable[[list[str]], dict[str, Any]] = discovery.discover,
    check: Callable[..., list[dict[str, Any]]] = structural.check_manifest,
) -> dict[str, Any]:
    """Compare two skill sets by name, structural verdict and line count.

    Deterministic on purpose: no model runs, so this is cheap enough to put in
    CI as a "did our skill set drift" check.
    """
    manifest_a, manifest_b = discover([dir_a]), discover([dir_b])
    rows_a = {r["name"]: r for r in check(manifest_a, search_root=dir_a, budget=budget)}
    rows_b = {r["name"]: r for r in check(manifest_b, search_root=dir_b, budget=budget)}
    lines_a = {s.get("name"): s.get("lines") for s in manifest_a.get("skills", [])}
    lines_b = {s.get("name"): s.get("lines") for s in manifest_b.get("skills", [])}
    names_a = set(lines_a)
    names_b = set(lines_b)

    common = []
    for name in sorted(names_a & names_b):
        verdict_a = rows_a.get(name, {}).get("verdict")
        verdict_b = rows_b.get(name, {}).get("verdict")
        common.append(
            {
                "name": name,
                "verdict1": verdict_a,
                "verdict2": verdict_b,
                "lines1": lines_a.get(name),
                "lines2": lines_b.get(name),
                "changed": verdict_a != verdict_b or lines_a.get(name) != lines_b.get(name),
            }
        )
    return {
        "added": sorted(names_b - names_a),
        "removed": sorted(names_a - names_b),
        "common": common,
    }


def write_diff_report(
    *, output: Path, date: str, dir_a: str, dir_b: str, diff: dict[str, Any]
) -> Path:
    """Render the deterministic diff report."""
    changed = [c for c in diff["common"] if c["changed"]]
    unchanged = [c for c in diff["common"] if not c["changed"]]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        f.write("# Skill diff report\n\n")
        f.write(f"**Date:** {date}\n\n")
        f.write(f"**Comparing:** `{dir_a}` (A) -> `{dir_b}` (B)\n\n")
        f.write(
            f"- Added (B only): {len(diff['added'])} | Removed (A only): {len(diff['removed'])} "
            f"| Changed: {len(changed)} | Unchanged: {len(unchanged)}\n\n"
        )
        f.write("## Added (in B, not A)\n\n")
        f.write("".join(f"- {n}\n" for n in diff["added"]) or "_None._\n")
        f.write("\n## Removed (in A, not B)\n\n")
        f.write("".join(f"- {n}\n" for n in diff["removed"]) or "_None._\n")
        f.write("\n## Changed (present in both)\n\n")
        if changed:
            f.write("| Skill | Verdict A -> B | Lines A -> B |\n|---|---|---|\n")
            for row in changed:
                f.write(
                    f"| {row['name']} | {row['verdict1']} -> {row['verdict2']} "
                    f"| {row['lines1']} -> {row['lines2']} |\n"
                )
        else:
            f.write("_None._\n")
        f.write("\n")
    return output


def run(args: Any, *, call: Callable[..., dict[str, Any]] = runner.call_claude) -> int:
    """Entry point for the ``skills`` command."""
    date = reporting.today()

    if args.action == "diff":
        dir_a, dir_b = args.directories
        output = reporting.resolve_output(
            args.output, report_dir=args.report_dir, target=dir_a, kind="skill-diff", date=date
        )
        diff = diff_skill_sets(dir_a, dir_b, args.complexity_budget)
        write_diff_report(output=output, date=date, dir_a=dir_a, dir_b=dir_b, diff=diff)
        print(f"Diff report written: {output}")
        return 0

    manifest = discovery.discover(args.directories)

    if args.action == "manifest":
        output = reporting.resolve_output(
            args.output,
            report_dir=args.report_dir,
            target=args.directories[0],
            kind="skill-manifest",
            date=date,
        )
        path = write_manifest(manifest, output)
        print(f"Manifest written: {path}")
        return 0

    structural_rows = structural.check_manifest(
        manifest, search_root=args.search_root, budget=args.complexity_budget
    )

    pass_keys = select_passes(args.focus)
    tasks = [
        (key, build_analysis_prompt(key, manifest, args), FINDINGS_SCHEMA) for key in pass_keys
    ]
    analysis = runner.fan_out(tasks, budget_usd=args.budget_usd, model=args.model, call=call)

    cross: dict[str, Any] = {}
    if args.focus in (None, "cross"):
        try:
            envelope = call(
                build_cross_prompt(manifest, analysis, args),
                CROSS_SCHEMA,
                budget_usd=args.budget_usd,
                model=args.model,
            )
            cross = runner.output(envelope)
        except runner.AgentError as exc:
            analysis["cross"] = {"_error": str(exc)}

    output = reporting.resolve_output(
        args.output,
        report_dir=args.report_dir,
        target=args.directories[0],
        kind="skill-audit",
        date=date,
    )
    write_report(
        output=output,
        date=date,
        manifest=manifest,
        structural_rows=structural_rows,
        analysis=analysis,
        cross=cross,
        args=args,
    )
    print(f"Report written: {output}")
    return 0
