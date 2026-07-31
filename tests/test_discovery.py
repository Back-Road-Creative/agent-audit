"""Deterministic discovery of skills and agents."""

from __future__ import annotations

from pathlib import Path

from agent_audit import discovery


def _skill(root: Path, name: str, body: str = "", *, front: str | None = None) -> Path:
    directory = root / ".claude" / "skills" / name
    directory.mkdir(parents=True, exist_ok=True)
    header = front if front is not None else f"---\nname: {name}\nversion: 1.0.0\n---\n"
    path = directory / "SKILL.md"
    path.write_text(f"{header}{body}")
    return path


# --- frontmatter --------------------------------------------------------------


def test_frontmatter_is_split_from_the_body():
    front, body = discovery.parse_frontmatter("---\nname: a\ndescription: 'x'\n---\n# Head\ntext")
    assert front == {"name": "a", "description": "x"}
    assert body == ["# Head", "text"]


def test_missing_frontmatter_returns_the_whole_file_as_body():
    front, body = discovery.parse_frontmatter("# Head\ntext")
    assert front == {}
    assert body == ["# Head", "text"]


def test_unterminated_frontmatter_is_treated_as_missing():
    front, _ = discovery.parse_frontmatter("---\nname: a\n# never closed")
    assert front == {}


def test_frontmatter_lines_without_a_colon_are_skipped():
    front, _ = discovery.parse_frontmatter("---\nname: a\njust-a-line\n---\n")
    assert front == {"name": "a"}


# --- body extraction ----------------------------------------------------------


def test_sections_are_the_markdown_headings():
    assert discovery.extract_sections(["# One", "text", "## Two"]) == ["One", "Two"]


def test_referenced_files_are_extracted_and_sorted():
    refs = discovery.extract_referenced_files(["run helper.sh then check config.yaml"])
    assert refs == ["config.yaml", "helper.sh"]


def test_urls_do_not_masquerade_as_file_references():
    refs = discovery.extract_referenced_files(["see https://example.com/docs.html for details"])
    assert refs == []


# --- source classification ----------------------------------------------------


HOME = Path("/users/someone")


def test_config_under_the_users_home_is_a_user_definition():
    path = HOME / ".claude" / "skills" / "a" / "SKILL.md"
    assert discovery.categorize_source(path, home=HOME) == "user"


def test_the_same_layout_inside_a_repo_is_a_project_definition():
    # The distinction is what it sits under, not the substring: a naive
    # `/.claude/skills/` match calls both of these "user".
    path = Path("/repo/.claude/skills/a/SKILL.md")
    assert discovery.categorize_source(path, home=HOME) == "project"


def test_agents_and_commands_directories_also_count_as_project_config():
    assert discovery.categorize_source(Path("/repo/.claude/agents/a.md"), home=HOME) == "project"
    assert discovery.categorize_source(Path("/repo/.claude/commands/a.md"), home=HOME) == "project"


def test_samples_are_samples_even_inside_the_home_config():
    path = HOME / ".claude" / "skills" / "examples" / "a" / "SKILL.md"
    assert discovery.categorize_source(path, home=HOME) == "example"


def test_staging_directories_are_marked_as_such():
    assert discovery.categorize_source(Path("/repo/staging/a/SKILL.md"), home=HOME) == "staging"


def test_anything_else_is_unknown():
    assert discovery.categorize_source(Path("/somewhere/else/SKILL.md"), home=HOME) == "unknown"


# --- manifest -----------------------------------------------------------------


def test_manifest_counts_skills_and_agents(tmp_path):
    _skill(tmp_path, "alpha", "# Alpha\nUse when auditing.\n")
    _skill(tmp_path, "beta", "# Beta\n")
    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "alpha-helper.md").write_text("---\nname: alpha-helper\n---\n# Helper\n")

    manifest = discovery.discover([str(tmp_path)])
    assert manifest["skill_count"] == 2
    assert manifest["agent_count"] == 1


def test_agents_associate_with_their_skill_by_name_prefix(tmp_path):
    _skill(tmp_path, "alpha")
    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "alpha-helper.md").write_text("---\nname: alpha-helper\n---\n")
    (agents / "unrelated.md").write_text("---\nname: unrelated\n---\n")

    manifest = discovery.discover([str(tmp_path)])
    skill = manifest["skills"][0]
    assert skill["associated_agents"] == ["alpha-helper"]
    by_name = {a["name"]: a for a in manifest["agents"]}
    assert by_name["alpha-helper"]["associated_skill"] == "alpha"
    assert by_name["unrelated"]["associated_skill"] is None


def test_skill_name_falls_back_to_its_directory(tmp_path):
    _skill(tmp_path, "gamma", front="")  # no frontmatter at all
    manifest = discovery.discover([str(tmp_path)])
    assert manifest["skills"][0]["name"] == "gamma"
    assert manifest["skills"][0]["has_frontmatter"] is False


def test_sibling_files_are_listed_but_boilerplate_is_ignored(tmp_path):
    path = _skill(tmp_path, "delta")
    (path.parent / "helper.sh").write_text("#!/bin/sh\n")
    (path.parent / "README.md").write_text("ignored")
    manifest = discovery.discover([str(tmp_path)])
    assert manifest["skills"][0]["sibling_files"] == ["helper.sh"]


def test_a_missing_directory_is_skipped_not_fatal(tmp_path):
    manifest = discovery.discover([str(tmp_path / "nope")])
    assert manifest["skill_count"] == 0
    assert manifest["agent_count"] == 0


def test_scanning_the_same_agents_dir_twice_does_not_duplicate(tmp_path):
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "one.md").write_text("---\nname: one\n---\n")
    manifest = discovery.discover([str(tmp_path)])
    assert manifest["agent_count"] == 1
