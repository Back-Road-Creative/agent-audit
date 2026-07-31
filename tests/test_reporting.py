"""Report path resolution and markdown helpers."""

from __future__ import annotations

from agent_audit import reporting

# --- slugify ------------------------------------------------------------------


def test_slug_comes_from_the_final_path_segment(tmp_path):
    target = tmp_path / "My Project"
    target.mkdir()
    assert reporting.slugify(str(target)) == "my-project"


def test_slug_collapses_punctuation_runs(tmp_path):
    target = tmp_path / "weird__name!!v2"
    target.mkdir()
    assert reporting.slugify(str(target)) == "weird-name-v2"


def test_root_like_targets_fall_back_to_a_default():
    assert reporting.slugify("/") == "audit"


# --- next_report_path ---------------------------------------------------------


def test_first_report_of_the_day_is_unsuffixed(tmp_path):
    path = reporting.next_report_path(tmp_path, "proj", "2026-01-02", "skill-audit")
    assert path.name == "2026-01-02-skill-audit.md"
    assert path.parent.is_dir()  # created for the caller
    assert not path.exists()  # but not the file itself


def test_second_report_of_the_day_becomes_2(tmp_path):
    first = reporting.next_report_path(tmp_path, "proj", "2026-01-02", "skill-audit")
    first.write_text("x")
    second = reporting.next_report_path(tmp_path, "proj", "2026-01-02", "skill-audit")
    assert second.name == "2026-01-02-skill-audit-2.md"


def test_numbering_continues_past_the_highest_existing_suffix(tmp_path):
    directory = tmp_path / "proj"
    directory.mkdir()
    for name in (
        "2026-01-02-skill-audit.md",
        "2026-01-02-skill-audit-2.md",
        "2026-01-02-skill-audit-7.md",
    ):
        (directory / name).write_text("x")
    nxt = reporting.next_report_path(tmp_path, "proj", "2026-01-02", "skill-audit")
    assert nxt.name == "2026-01-02-skill-audit-8.md"


def test_a_different_kind_or_date_starts_over(tmp_path):
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "2026-01-02-skill-audit.md").write_text("x")
    assert reporting.next_report_path(tmp_path, "proj", "2026-01-02", "instruction-audit").name == (
        "2026-01-02-instruction-audit.md"
    )
    assert reporting.next_report_path(tmp_path, "proj", "2026-01-03", "skill-audit").name == (
        "2026-01-03-skill-audit.md"
    )


def test_non_numeric_suffixes_are_ignored(tmp_path):
    directory = tmp_path / "proj"
    directory.mkdir()
    (directory / "2026-01-02-skill-audit-draft.md").write_text("x")
    nxt = reporting.next_report_path(tmp_path, "proj", "2026-01-02", "skill-audit")
    assert nxt.name == "2026-01-02-skill-audit.md"


# --- resolve_output -----------------------------------------------------------


def test_explicit_output_wins_over_the_report_directory(tmp_path):
    resolved = reporting.resolve_output(
        str(tmp_path / "exact.md"), report_dir=tmp_path / "unused", target=".", kind="x"
    )
    assert resolved == tmp_path / "exact.md"
    assert not (tmp_path / "unused").exists()


def test_without_output_the_report_directory_is_used(tmp_path):
    target = tmp_path / "thing"
    target.mkdir()
    resolved = reporting.resolve_output(
        None,
        report_dir=tmp_path / "reports",
        target=str(target),
        kind="skill-audit",
        date="2026-01-02",
    )
    assert resolved == tmp_path / "reports" / "thing" / "2026-01-02-skill-audit.md"


# --- markdown helpers ---------------------------------------------------------


def test_cell_neutralises_pipes_and_newlines():
    assert reporting.cell("a | b\nc") == "a / b c"


def test_cell_renders_none_as_empty():
    assert reporting.cell(None) == ""


def test_coverage_gaps_section_is_written_even_when_clean(tmp_path):
    path = tmp_path / "r.md"
    with path.open("w") as handle:
        reporting.write_coverage_gaps(handle, [])
    assert "every pass returned parseable output" in path.read_text()


def test_coverage_gaps_section_lists_failures(tmp_path):
    path = tmp_path / "r.md"
    with path.open("w") as handle:
        reporting.write_coverage_gaps(handle, ["security: timed out"])
    assert "- security: timed out" in path.read_text()
