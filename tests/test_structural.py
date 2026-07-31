"""The deterministic structural checks."""

from __future__ import annotations

from pathlib import Path

from agent_audit import discovery, structural


def _write(root: Path, name: str, text: str) -> Path:
    directory = root / ".claude" / "skills" / name
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "SKILL.md"
    path.write_text(text)
    return path


def _entry(path: Path, **overrides):
    entry = discovery.parse_file(path)
    entry["name"] = entry.get("frontmatter", {}).get("name") or path.parent.name
    entry.setdefault("sibling_files", [])
    entry.setdefault("associated_agents", [])
    entry.update(overrides)
    return entry


def _evaluate(path: Path, *, is_agent=False, budget=200, search_root=None):
    return structural.evaluate_entity(
        _entry(path),
        is_agent=is_agent,
        search_root=Path(search_root or path.parent),
        budget=budget,
    )


BODY = "# Title\n\nUse when auditing things.\n" + "\nfiller\n" * 10


# --- verdict ranking ----------------------------------------------------------


def test_worst_picks_the_highest_severity():
    assert structural.worst(["PASS", "WARN", "FAIL"]) == "FAIL"
    assert structural.worst(["PASS", "WARN"]) == "WARN"
    assert structural.worst([]) == "PASS"


# --- frontmatter --------------------------------------------------------------


def test_missing_frontmatter_fails(tmp_path):
    path = _write(tmp_path, "alpha", BODY)
    row = _evaluate(path)
    assert row["verdict"] == "FAIL"
    assert any("frontmatter-missing" in e for e in row["evidence"])


def test_missing_description_and_version_warn(tmp_path):
    path = _write(tmp_path, "alpha", f"---\nname: alpha\n---\n{BODY}")
    row = _evaluate(path)
    assert row["verdict"] == "WARN"
    evidence = " ".join(row["evidence"])
    assert "frontmatter-description-missing" in evidence
    assert "frontmatter-version-missing" in evidence


def test_agents_are_not_required_to_carry_a_version(tmp_path):
    path = _write(tmp_path, "alpha", f"---\nname: alpha\ndescription: d\n---\n{BODY}")
    assert not any("version" in e for e in _evaluate(path, is_agent=True)["evidence"])


def test_name_disagreeing_with_the_directory_warns(tmp_path):
    front = "---\nname: not-alpha\ndescription: d\nversion: 1\n---\n"
    path = _write(tmp_path, "alpha", f"{front}{BODY}")
    assert any("name-mismatch" in e for e in _evaluate(path)["evidence"])


# --- content ------------------------------------------------------------------


def test_a_stub_definition_fails_immediately(tmp_path):
    path = _write(tmp_path, "alpha", "---\nname: alpha\ndescription: d\nversion: 1\n---\ntiny\n")
    row = _evaluate(path)
    assert row["verdict"] == "FAIL"
    assert any("content-too-short" in e for e in row["evidence"])
    # The short-circuit means the later content checks are not also reported.
    assert not any("no-trigger-language" in e for e in row["evidence"])


def test_no_trigger_language_warns(tmp_path):
    body = "# Title\n\nDoes some things.\n" + "\nfiller\n" * 10
    path = _write(tmp_path, "alpha", f"---\nname: alpha\ndescription: d\nversion: 1\n---\n{body}")
    assert any("no-trigger-language" in e for e in _evaluate(path)["evidence"])


def test_a_definition_with_no_headings_warns(tmp_path):
    body = "Use when auditing.\n" + "\nfiller\n" * 10
    path = _write(tmp_path, "alpha", f"---\nname: alpha\ndescription: d\nversion: 1\n---\n{body}")
    assert any("no-sections" in e for e in _evaluate(path)["evidence"])


# --- references and orphans ---------------------------------------------------

CLEAN_FRONT = "---\nname: alpha\ndescription: d\nversion: 1\n---\n"


def test_a_referenced_file_that_exists_is_not_flagged(tmp_path):
    path = _write(tmp_path, "alpha", f"{CLEAN_FRONT}{BODY}\nRun helper.sh.\n")
    (path.parent / "helper.sh").write_text("#!/bin/sh\n")
    assert not any("referenced-file-not-found" in e for e in _evaluate(path)["evidence"])


def test_a_missing_referenced_file_warns(tmp_path):
    path = _write(tmp_path, "alpha", f"{CLEAN_FRONT}{BODY}\nRun ghost.sh.\n")
    assert any("referenced-file-not-found" in e for e in _evaluate(path)["evidence"])


def test_conventional_filenames_are_not_treated_as_references(tmp_path):
    path = _write(tmp_path, "alpha", f"{CLEAN_FRONT}{BODY}\nSee CLAUDE.md and AGENTS.md.\n")
    assert not any("referenced-file-not-found" in e for e in _evaluate(path)["evidence"])


def test_an_unmentioned_sibling_is_an_orphan(tmp_path):
    path = _write(tmp_path, "alpha", f"{CLEAN_FRONT}{BODY}")
    entry = _entry(path, sibling_files=["orphan.sh"])
    row = structural.evaluate_entity(entry, is_agent=False, search_root=path.parent, budget=200)
    assert any("orphan-sibling" in e for e in row["evidence"])


def test_an_unmentioned_owned_agent_is_an_orphan(tmp_path):
    path = _write(tmp_path, "alpha", f"{CLEAN_FRONT}{BODY}")
    entry = _entry(path, associated_agents=["alpha-helper"])
    row = structural.evaluate_entity(entry, is_agent=False, search_root=path.parent, budget=200)
    assert any("orphan-agent" in e for e in row["evidence"])


def test_orphan_and_reference_checks_are_skipped_for_agents(tmp_path):
    path = _write(tmp_path, "alpha", f"{CLEAN_FRONT}{BODY}\nRun ghost.sh.\n")
    entry = _entry(path, sibling_files=["orphan.sh"])
    row = structural.evaluate_entity(entry, is_agent=True, search_root=path.parent, budget=200)
    evidence = " ".join(row["evidence"])
    assert "orphan-sibling" not in evidence
    assert "referenced-file-not-found" not in evidence


# --- external surface ---------------------------------------------------------


def test_urls_env_vars_and_binaries_are_reported(tmp_path):
    body = f"{BODY}\nFetch https://example.com, read $API_TOKEN, run git status.\n"
    path = _write(tmp_path, "alpha", f"{CLEAN_FRONT}{body}")
    evidence = " ".join(_evaluate(path)["evidence"])
    assert "external-urls" in evidence
    assert "API_TOKEN" in evidence
    assert "external-binaries" in evidence


# --- complexity ---------------------------------------------------------------


def test_exceeding_the_complexity_budget_warns(tmp_path):
    path = _write(tmp_path, "alpha", CLEAN_FRONT + BODY + "\nline\n" * 300)
    assert any("complexity-budget" in e for e in _evaluate(path, budget=50)["evidence"])


def test_a_raised_budget_silences_it(tmp_path):
    path = _write(tmp_path, "alpha", CLEAN_FRONT + BODY + "\nline\n" * 300)
    assert not any("complexity-budget" in e for e in _evaluate(path, budget=10_000)["evidence"])


# --- unreadable ---------------------------------------------------------------


def test_an_unreadable_entry_fails_without_raising():
    row = structural.evaluate_entity(
        {"path": "/nope/SKILL.md", "readable": False, "error": "boom", "name": "x"},
        is_agent=False,
        search_root=Path("/"),
        budget=200,
    )
    assert row["verdict"] == "FAIL"
    assert "unreadable: boom" in row["evidence"][0]


def test_a_file_deleted_between_discovery_and_checking_fails_cleanly(tmp_path):
    row = structural.evaluate_entity(
        {"path": str(tmp_path / "gone.md"), "readable": True, "name": "gone", "lines": 50},
        is_agent=False,
        search_root=tmp_path,
        budget=200,
    )
    assert row["verdict"] == "FAIL"
    assert "read-failed" in row["evidence"][0]


# --- whole manifest -----------------------------------------------------------


def test_check_manifest_returns_a_row_per_entity(tmp_path):
    _write(tmp_path, "alpha", f"{CLEAN_FRONT}{BODY}")
    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "solo.md").write_text(f"---\nname: solo\ndescription: d\n---\n{BODY}")

    manifest = discovery.discover([str(tmp_path)])
    rows = structural.check_manifest(manifest, search_root=tmp_path)
    assert {r["name"] for r in rows} == {"alpha", "solo"}
    assert {r["kind"] for r in rows} == {"skill", "agent"}


def test_a_clean_definition_passes(tmp_path):
    _write(tmp_path, "alpha", f"{CLEAN_FRONT}{BODY}")
    manifest = discovery.discover([str(tmp_path)])
    row = structural.check_manifest(manifest, search_root=tmp_path)[0]
    assert row["verdict"] == "PASS"
    assert row["rationale"] == "All structural checks passed"
