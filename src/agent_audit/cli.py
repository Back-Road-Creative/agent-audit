"""Command-line surface: ``agent-audit skills | instructions | maturity``.

One executable rather than three, because the three auditors share their whole
runtime surface — the same report-directory conventions, the same budget and
model flags, the same ``claude`` CLI boundary — and one ``--help`` is where you
find out the other two exist.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from . import __version__, instructions, maturity, reporting, runner, skills, structural

SKILL_ACTIONS = {"scan", "manifest", "diff"}


def add_common(parser: argparse.ArgumentParser) -> None:
    """Flags every subcommand shares."""
    parser.add_argument(
        "--report-dir",
        default=reporting.DEFAULT_REPORT_DIR,
        help=f"Directory reports are written under (default: {reporting.DEFAULT_REPORT_DIR}). "
        "Reports land at <report-dir>/<target-slug>/<date>-<kind>.md, numbered on repeat runs.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write to this exact path instead, ignoring --report-dir.",
    )
    parser.add_argument(
        "--budget-usd",
        type=float,
        default=runner.DEFAULT_BUDGET_USD,
        help=f"Runaway-loop ceiling per analysis pass (default: {runner.DEFAULT_BUDGET_USD}). "
        "A pass that trips it returns nothing, so lowering this empties report sections.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model passed through to the CLI for every pass (default: the CLI's own default).",
    )
    parser.add_argument(
        "--prompt-dir",
        default=None,
        help="Directory of same-named .md files that override the packaged pass prompts.",
    )


def build_parser() -> argparse.ArgumentParser:
    """Assemble the full argument parser."""
    parser = argparse.ArgumentParser(
        prog="agent-audit",
        description="Audit AI-agent configuration: skills, instruction files, workflow maturity.",
    )
    parser.add_argument("--version", action="version", version=f"agent-audit {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    # -- skills ---------------------------------------------------------------
    skills_cmd = commands.add_parser(
        "skills",
        help="Audit skill and agent definitions.",
        description="Audit skill and agent definitions for structure, security, quality "
        "and determinism. The action defaults to `scan`.",
    )
    add_common(skills_cmd)
    skills_cmd.add_argument(
        "action",
        choices=sorted(SKILL_ACTIONS),
        help="scan (full audit), manifest (discovery only), or diff (compare two sets). "
        "Omit it and `scan` is assumed.",
    )
    skills_cmd.add_argument(
        "directories",
        nargs="+",
        help="Directories to scan. `diff` takes exactly two.",
    )
    skills_cmd.add_argument(
        "--focus",
        choices=skills.FOCUS_CHOICES,
        default=None,
        help="Run a single pass instead of all of them.",
    )
    skills_cmd.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Also write a machine-readable JSON sidecar next to the report.",
    )
    skills_cmd.add_argument(
        "--fix-suggestions",
        action="store_true",
        help="Ask each pass for a concrete fix alongside every finding.",
    )
    skills_cmd.add_argument(
        "--complexity-budget",
        type=int,
        default=structural.DEFAULT_COMPLEXITY_BUDGET,
        help=f"Lines before a definition is flagged as oversized "
        f"(default: {structural.DEFAULT_COMPLEXITY_BUDGET}).",
    )
    skills_cmd.add_argument(
        "--staleness-days",
        type=int,
        default=skills.DEFAULT_STALENESS_DAYS,
        help=f"Age before a definition counts as stale (default: {skills.DEFAULT_STALENESS_DAYS}).",
    )
    skills_cmd.add_argument(
        "--search-root",
        default=".",
        help="Root used to resolve files a definition references by relative path.",
    )

    # -- instructions ---------------------------------------------------------
    instructions_cmd = commands.add_parser(
        "instructions",
        help="Audit instruction files for contradictions, effectiveness and context cost.",
        description="Audit standing instruction files — agent instructions, rule files, "
        "memory — for contradictions, weak enforceability and wasted context.",
    )
    add_common(instructions_cmd)
    instructions_cmd.add_argument(
        "target_dir", nargs="?", default=".", help="Directory to audit (default: cwd)."
    )
    instructions_cmd.add_argument(
        "--context-window",
        type=int,
        default=instructions.DEFAULT_CONTEXT_WINDOW,
        help=f"Token budget the context percentage is measured against "
        f"(default: {instructions.DEFAULT_CONTEXT_WINDOW}).",
    )

    # -- maturity -------------------------------------------------------------
    maturity_cmd = commands.add_parser(
        "maturity",
        help="Classify components against the workflow-maturity taxonomy.",
        description="Classify skills, agents, pipelines and memory files against an "
        "AI-development maturity taxonomy and emit graduation signals.",
    )
    add_common(maturity_cmd)
    maturity_cmd.add_argument(
        "target_dir", nargs="?", default=".", help="Directory to audit (default: cwd)."
    )

    return parser


def normalize_skills_argv(argv: list[str]) -> list[str]:
    """Let ``skills <dir>`` mean ``skills scan <dir>``.

    An optional positional in front of a variadic one is ambiguous to
    ``argparse``, so the action is made mandatory and the default is inserted
    here instead. The action must lead, which keeps the rewrite a single
    unambiguous check rather than a guess about which token was meant.
    """
    if len(argv) < 2 or argv[0] != "skills":
        return argv
    if argv[1] in SKILL_ACTIONS or argv[1] in {"-h", "--help"}:
        return argv
    return ["skills", "scan", *argv[1:]]


def validate(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Reject argument combinations the parser cannot express on its own."""
    if args.command == "skills" and args.action == "diff" and len(args.directories) != 2:
        parser.error("`skills diff` takes exactly two directories")


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and dispatch. Returns a process exit code."""
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(normalize_skills_argv(raw))
    validate(args, parser)

    handlers = {
        "skills": skills.run,
        "instructions": instructions.run,
        "maturity": maturity.run,
    }
    try:
        return handlers[args.command](args)
    except runner.AgentError as exc:
        print(f"agent-audit: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
