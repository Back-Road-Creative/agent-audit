"""Deterministic discovery of skill and agent definition files.

A skill is a ``SKILL.md`` with YAML frontmatter. An agent is a ``*.md`` sitting
directly inside an ``agents/`` directory. Both conventions come from Claude
Code's on-disk layout, but nothing here requires that layout — point the
scanner at any directory and it globs what is there.

Output is a single manifest dict. This step is pure glob, frontmatter parse and
shared-prefix association: no judgment, so no model.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Path fragments that mark a definition as not-really-live, checked before
# anything else because a sample living inside a config directory is still a
# sample.
SOURCE_MARKERS: list[tuple[str, str]] = [
    ("/staging/", "staging"),
    ("/stage/", "staging"),
    ("/examples/", "example"),
    ("/example/", "example"),
]

#: Directory names that hold agent configuration inside a project or a home dir.
CONFIG_DIRS = ("skills", "agents", "commands")

# `path/file.ext`, `script.sh`, and friends. Conservative on purpose: at least
# one dot, no whitespace, not a URL. Only used to spot referenced files.
PATH_REF_RE = re.compile(r"(?<![a-zA-Z0-9_/])([\w./-]+\.[a-zA-Z0-9]{1,8})(?![a-zA-Z0-9_])")
URL_RE = re.compile(r"https?://\S+")

#: Sibling files that are never treated as skill assets.
IGNORED_SIBLINGS = {"README.md", "LICENSE", ".gitkeep", "__pycache__"}


def parse_frontmatter(text: str) -> tuple[dict[str, str], list[str]]:
    """Split ``---`` frontmatter from the body.

    Returns ``({}, all_lines)`` when the block is missing or unterminated. The
    parser is deliberately flat — one ``key: value`` per line, quotes stripped —
    because skill frontmatter is flat and a YAML dependency would be the only
    third-party package in the project.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, lines
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, lines
    front: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        front[key.strip()] = value.strip().strip('"').strip("'")
    return front, lines[end + 1 :]


def categorize_source(path: Path, *, home: Path | None = None) -> str:
    """Classify a definition path as user / project / staging / example.

    "User" means the definition lives in the invoking user's own config
    directory and therefore applies to every project they touch; "project"
    means it is checked into one repository. Telling those apart needs the home
    directory, not a substring: ``/home/u/.claude/skills/`` and
    ``/repo/.claude/skills/`` differ only in what they are *under*.
    """
    text = str(path)
    for needle, category in SOURCE_MARKERS:
        if needle in text:
            return category

    home_config = (home or Path.home()) / ".claude"
    try:
        path.relative_to(home_config)
    except ValueError:
        pass
    else:
        return "user"

    parts = path.parts
    for index, part in enumerate(parts[:-1]):
        if part == ".claude" and parts[index + 1] in CONFIG_DIRS:
            return "project"
    return "unknown"


def extract_sections(body_lines: list[str]) -> list[str]:
    """Markdown headings, stripped of their leading hashes."""
    return [line.lstrip("#").strip() for line in body_lines if line.startswith("#")]


def extract_referenced_files(body_lines: list[str]) -> list[str]:
    """File-ish tokens mentioned in the body, URLs removed first."""
    seen: set[str] = set()
    for line in body_lines:
        if "://" in line:
            line = URL_RE.sub(" ", line)
        seen.update(match.group(1) for match in PATH_REF_RE.finditer(line))
    return sorted(seen)


def list_siblings(skill_path: Path) -> list[str]:
    """Files alongside a ``SKILL.md`` — its scripts, templates and references."""
    try:
        entries = list(skill_path.parent.iterdir())
    except OSError:
        return []
    return sorted(
        p.name for p in entries if p.name != skill_path.name and p.name not in IGNORED_SIBLINGS
    )


def find_skills(root: Path) -> list[Path]:
    """Every ``SKILL.md`` under ``root``."""
    return sorted(root.rglob("SKILL.md"))


def find_agents(root: Path) -> list[Path]:
    """Every ``*.md`` directly inside an ``agents/`` directory under ``root``."""
    found: list[Path] = []
    for directory in sorted(root.rglob("agents")):
        if directory.is_dir():
            found.extend(sorted(p for p in directory.glob("*.md") if p.is_file()))
    if root.name == ".claude":
        agents_dir = root / "agents"
        if agents_dir.is_dir():
            found.extend(sorted(agents_dir.glob("*.md")))
    return sorted(set(found))


def parse_file(path: Path) -> dict[str, Any]:
    """Read and describe one definition file; unreadable files are recorded, not raised."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"path": str(path), "readable": False, "error": str(exc)}
    front, body = parse_frontmatter(text)
    return {
        "path": str(path),
        "readable": True,
        "frontmatter": front,
        "has_frontmatter": bool(front),
        "lines": len(text.splitlines()),
        "sections": extract_sections(body),
        "referenced_files": extract_referenced_files(body),
    }


def associate(skill_name: str, agents: list[dict[str, Any]]) -> list[str]:
    """Agents owned by a skill, matched on the ``<skill>-<role>`` name convention."""
    return sorted(
        agent["name"] for agent in agents if agent.get("name", "").startswith(f"{skill_name}-")
    )


def build_manifest(roots: list[Path], *, home: Path | None = None) -> dict[str, Any]:
    """Scan every root and return the manifest the later stages consume."""
    skill_paths: list[Path] = []
    agent_paths: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        skill_paths.extend(find_skills(root))
        agent_paths.extend(find_agents(root))

    agents: list[dict[str, Any]] = []
    for path in agent_paths:
        entry = parse_file(path)
        entry["name"] = entry.get("frontmatter", {}).get("name") or path.stem
        agents.append(entry)

    skills: list[dict[str, Any]] = []
    for path in skill_paths:
        entry = parse_file(path)
        entry["source"] = categorize_source(path, home=home)
        entry["name"] = entry.get("frontmatter", {}).get("name") or path.parent.name
        entry["sibling_files"] = list_siblings(path) if entry["readable"] else []
        entry["associated_agents"] = associate(entry["name"], agents) if entry["readable"] else []
        skills.append(entry)

    for agent in agents:
        agent["associated_skill"] = next(
            (s["name"] for s in skills if agent["name"] in s["associated_agents"]), None
        )

    return {
        "directories_scanned": [str(r) for r in roots],
        "skill_count": len(skills),
        "agent_count": len(agents),
        "skills": skills,
        "agents": agents,
    }


def discover(directories: list[str], *, home: Path | None = None) -> dict[str, Any]:
    """Build a manifest from user-supplied directory strings."""
    return build_manifest([Path(d).expanduser().resolve() for d in directories], home=home)
