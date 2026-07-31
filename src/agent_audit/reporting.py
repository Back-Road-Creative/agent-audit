"""Where reports go, and shared markdown helpers.

The report directory is a flag, never a constant baked into the auditors:
``--report-dir`` (default ``./agent-audit-reports``) plus ``--output`` when you
want to name one exact file. Repeat runs on the same day do not overwrite each
other — the second becomes ``-2``, the third ``-3``, and so on.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

#: Written under the current working directory unless ``--report-dir`` says otherwise.
DEFAULT_REPORT_DIR = "./agent-audit-reports"

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def today() -> str:
    """Local date as ``YYYY-MM-DD``."""
    return dt.date.today().isoformat()


def slugify(target: str) -> str:
    """Turn a path or name into a short directory-safe slug.

    ``"/srv/projects/My Repo/"`` -> ``"my-repo"``. A path that reduces to
    nothing (``"."``, ``"/"``) falls back to ``"audit"``.
    """
    name = Path(target).expanduser().resolve().name or ""
    slug = _SLUG_STRIP.sub("-", name.lower()).strip("-")
    return slug or "audit"


def next_report_path(base_dir: str | Path, slug: str, date: str, kind: str) -> Path:
    """First free ``<base_dir>/<slug>/<date>-<kind>[-N].md``.

    The unsuffixed name counts as N=1, so a second run the same day lands on
    ``-2``. The directory is created; the file is not — the caller writes it.
    """
    project_dir = Path(base_dir).expanduser() / slug
    project_dir.mkdir(parents=True, exist_ok=True)

    unsuffixed = project_dir / f"{date}-{kind}.md"
    highest = 0
    for existing in project_dir.glob(f"{date}-{kind}-*.md"):
        suffix = existing.name[len(f"{date}-{kind}-") : -len(".md")]
        if suffix.isdigit():
            highest = max(highest, int(suffix))

    if not unsuffixed.exists() and highest == 0:
        return unsuffixed
    return project_dir / f"{date}-{kind}-{max(highest, 1) + 1}.md"


def resolve_output(
    explicit: str | None,
    *,
    report_dir: str | Path,
    target: str,
    kind: str,
    date: str | None = None,
) -> Path:
    """``--output`` when given, else the next free dated path under the report dir."""
    if explicit:
        return Path(explicit).expanduser()
    return next_report_path(report_dir, slugify(target), date or today(), kind)


def cell(text: object) -> str:
    """Make a value safe to drop into a markdown table cell."""
    return str(text if text is not None else "").replace("|", "/").replace("\n", " ").strip()


def write_coverage_gaps(handle, gaps: list[str]) -> None:
    """Standard trailing section, present in every report even when empty."""
    handle.write("## Coverage gaps\n\n")
    if gaps:
        for gap in gaps:
            handle.write(f"- {gap}\n")
    else:
        handle.write("_None — every pass returned parseable output._\n")
    handle.write("\n")
