"""Deterministic structural checks over a discovery manifest.

These are the findings that never need a model: missing frontmatter, a name
that disagrees with its directory, a referenced file that is not on disk, a
sibling script nothing mentions, a definition longer than its budget. Running
them first means the paid analysis passes spend their attention on judgment
calls instead of re-deriving facts a glob already knows.

One row per skill or agent, with ``verdict`` in ``PASS`` / ``WARN`` / ``FAIL``
and one ``check: detail`` evidence line per finding.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

VERDICT_RANK = {"PASS": 0, "WARN": 1, "FAIL": 2}

#: A definition longer than this is flagged as a decomposition candidate.
DEFAULT_COMPLEXITY_BUDGET = 200

#: Below this it is a stub, not a definition.
MIN_USEFUL_LINES = 10

URL_RE = re.compile(r"https?://\S+")
ENV_VAR_RE = re.compile(r"\$\{?([A-Z][A-Z0-9_]{2,})\}?")

# External binaries worth declaring as a requirement when a definition uses one.
BINARY_RE = re.compile(
    r"(?<![\w/])(ffmpeg|gh|git|jq|claude|pytest|ruff|mypy|node|npm|docker|python3?)(?:\b|$)"
)

# Any of these in the body satisfies "says when to invoke me".
TRIGGER_RE = re.compile(
    r"\b(invoke when|use when|trigger|auto-?detect|auto-?invoke|use this skill)", re.IGNORECASE
)

# Referenced names that are conventions rather than real relative paths.
GENERIC_REFERENCES = {"SKILL.md", "MEMORY.md", "CLAUDE.md", "AGENTS.md", "README.md"}

Finding = tuple[str, str, str]  # (verdict, check, detail)


def worst(verdicts: list[str]) -> str:
    """Highest-severity verdict in the list; ``PASS`` when empty."""
    if not verdicts:
        return "PASS"
    return max(verdicts, key=lambda v: VERDICT_RANK.get(v, 0))


def check_frontmatter(entry: dict[str, Any], *, is_agent: bool) -> list[Finding]:
    """Frontmatter presence, required keys, and name/directory agreement."""
    if not entry.get("has_frontmatter"):
        return [("FAIL", "frontmatter-missing", "No YAML frontmatter block")]
    front = entry.get("frontmatter", {})
    out: list[Finding] = []
    if not front.get("name"):
        out.append(("WARN", "frontmatter-name-missing", "Frontmatter has no `name`"))
    if not front.get("description"):
        out.append(("WARN", "frontmatter-description-missing", "Frontmatter has no `description`"))
    if not is_agent and not front.get("version"):
        out.append(("WARN", "frontmatter-version-missing", "Frontmatter has no `version`"))
    if not is_agent and front.get("name"):
        directory = Path(entry["path"]).parent.name
        if front["name"] != directory:
            out.append(
                (
                    "WARN",
                    "frontmatter-name-mismatch",
                    f"Frontmatter name `{front['name']}` != directory `{directory}`",
                )
            )
    return out


def check_content(entry: dict[str, Any], body: str) -> list[Finding]:
    """Length floor, trigger language, and presence of any headings."""
    lines = entry.get("lines", 0)
    if lines < MIN_USEFUL_LINES:
        return [("FAIL", "content-too-short", f"Only {lines} lines — likely a placeholder")]
    out: list[Finding] = []
    if not TRIGGER_RE.search(body):
        out.append(("WARN", "no-trigger-language", "Nothing states when to invoke this"))
    if not entry.get("sections"):
        out.append(("WARN", "no-sections", "No markdown headings — likely no usage instructions"))
    return out


def check_referenced_files(entry: dict[str, Any], search_root: Path) -> list[Finding]:
    """Files named in the body that exist neither locally nor under the search root."""
    definition_dir = Path(entry["path"]).parent
    out: list[Finding] = []
    for ref in entry.get("referenced_files", []):
        if ref.startswith(".") or ref in GENERIC_REFERENCES:
            continue
        if (definition_dir / ref).exists() or (search_root / ref).exists():
            continue
        # Many references are illustrative, so this warns rather than fails.
        out.append(
            ("WARN", "referenced-file-not-found", f"`{ref}` not found locally or under the root")
        )
    return out


def check_orphans(entry: dict[str, Any], body: str) -> list[Finding]:
    """Bundled assets and owned agents the definition never mentions."""
    out: list[Finding] = []
    for sibling in entry.get("sibling_files", []):
        if sibling not in body:
            out.append(("WARN", "orphan-sibling", f"`{sibling}` is never referenced"))
    for agent in entry.get("associated_agents", []):
        if agent not in body:
            out.append(("WARN", "orphan-agent", f"Owned agent `{agent}` is never mentioned"))
    return out


def check_external_deps(body: str) -> list[Finding]:
    """Outside surface: URLs, environment variables, and shelled-out binaries."""
    out: list[Finding] = []
    urls = sorted(set(URL_RE.findall(body)))
    if urls:
        out.append(("WARN", "external-urls", f"References {len(urls)} URL(s); first: {urls[0]}"))
    env_vars = sorted(set(ENV_VAR_RE.findall(body)))
    if env_vars:
        out.append(("WARN", "env-vars", f"Reads env vars: {', '.join(env_vars[:5])}"))
    binaries = sorted(set(BINARY_RE.findall(body)))
    if binaries:
        out.append(("WARN", "external-binaries", f"Calls binaries: {', '.join(binaries[:5])}"))
    return out


def check_complexity(entry: dict[str, Any], budget: int) -> list[Finding]:
    """Definition length against the complexity budget."""
    lines = entry.get("lines", 0)
    if lines > budget:
        return [("WARN", "complexity-budget", f"{lines} lines exceeds the budget of {budget}")]
    return []


def evaluate_entity(
    entry: dict[str, Any], *, is_agent: bool, search_root: Path, budget: int
) -> dict[str, Any]:
    """Run every check against one definition and fold the results into a verdict row."""
    name = entry.get("name") or Path(entry["path"]).stem
    if not entry.get("readable"):
        return {
            "name": name,
            "kind": "agent" if is_agent else "skill",
            "path": entry.get("path", ""),
            "verdict": "FAIL",
            "rationale": "File unreadable",
            "evidence": [f"unreadable: {entry.get('error', 'unknown')}"],
            "counts": {"warn": 0, "fail": 1},
        }

    try:
        body = Path(entry["path"]).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {
            "name": name,
            "kind": "agent" if is_agent else "skill",
            "path": entry["path"],
            "verdict": "FAIL",
            "rationale": "Read failed during content checks",
            "evidence": [f"read-failed: {exc}"],
            "counts": {"warn": 0, "fail": 1},
        }

    findings: list[Finding] = []
    findings += check_frontmatter(entry, is_agent=is_agent)
    findings += check_content(entry, body)
    if not is_agent:
        findings += check_referenced_files(entry, search_root)
        findings += check_orphans(entry, body)
    findings += check_external_deps(body)
    findings += check_complexity(entry, budget)

    verdicts = [verdict for verdict, _, _ in findings]
    warn = verdicts.count("WARN")
    fail = verdicts.count("FAIL")
    rationale = (
        f"{len(findings) - warn - fail} clean, {warn} warn, {fail} fail"
        if findings
        else "All structural checks passed"
    )
    return {
        "name": name,
        "kind": "agent" if is_agent else "skill",
        "path": entry["path"],
        "verdict": worst(verdicts),
        "rationale": rationale,
        "evidence": [f"{check}: {detail}" for _, check, detail in findings],
        "counts": {"warn": warn, "fail": fail},
    }


def check_manifest(
    manifest: dict[str, Any],
    *,
    search_root: str | Path = ".",
    budget: int = DEFAULT_COMPLEXITY_BUDGET,
) -> list[dict[str, Any]]:
    """Structural verdict rows for every skill and agent in a manifest."""
    root = Path(search_root).expanduser().resolve()
    rows = [
        evaluate_entity(s, is_agent=False, search_root=root, budget=budget)
        for s in manifest.get("skills", [])
    ]
    rows += [
        evaluate_entity(a, is_agent=True, search_root=root, budget=budget)
        for a in manifest.get("agents", [])
    ]
    return rows
