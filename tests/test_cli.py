"""Argument parsing, defaults, and dispatch."""

from __future__ import annotations

import pytest

from agent_audit import cli, instructions, reporting, runner, skills, structural

# --- action normalisation -----------------------------------------------------


def test_a_bare_directory_means_scan(parse):
    args = parse(["skills", "/x", "/y"])
    assert args.action == "scan"
    assert args.directories == ["/x", "/y"]


def test_an_explicit_action_is_left_alone(parse):
    assert parse(["skills", "manifest", "/x"]).action == "manifest"
    assert parse(["skills", "diff", "/a", "/b"]).action == "diff"


def test_a_leading_flag_still_gets_the_default_action(parse):
    args = parse(["skills", "--focus", "security", "/x"])
    assert args.action == "scan"
    assert args.focus == "security"
    assert args.directories == ["/x"]


def test_normalisation_leaves_other_commands_untouched():
    assert cli.normalize_skills_argv(["instructions", "/x"]) == ["instructions", "/x"]
    assert cli.normalize_skills_argv(["skills"]) == ["skills"]
    assert cli.normalize_skills_argv(["skills", "--help"]) == ["skills", "--help"]


# --- defaults -----------------------------------------------------------------


def test_shared_defaults_are_sane(parse):
    args = parse(["skills", "/x"])
    assert args.report_dir == reporting.DEFAULT_REPORT_DIR
    assert args.output is None
    assert args.budget_usd == runner.DEFAULT_BUDGET_USD
    assert args.model is None
    assert args.prompt_dir is None


def test_the_report_directory_is_not_hardcoded_to_a_hidden_folder(parse):
    # The default must be visible and overridable, not buried in a dotfile.
    assert not parse(["skills", "/x"]).report_dir.lstrip("./").startswith(".")


def test_skill_defaults(parse):
    args = parse(["skills", "/x"])
    assert args.complexity_budget == structural.DEFAULT_COMPLEXITY_BUDGET
    assert args.staleness_days == skills.DEFAULT_STALENESS_DAYS
    assert args.focus is None
    assert args.as_json is False
    assert args.fix_suggestions is False


def test_instruction_defaults(parse):
    args = parse(["instructions"])
    assert args.target_dir == "."
    assert args.context_window == instructions.DEFAULT_CONTEXT_WINDOW


def test_maturity_defaults(parse):
    assert parse(["maturity"]).target_dir == "."


def test_flags_override_defaults(parse):
    args = parse(
        [
            "skills",
            "/x",
            "--json",
            "--fix-suggestions",
            "--complexity-budget",
            "150",
            "--staleness-days",
            "30",
            "--output",
            "/tmp/report.md",
            "--report-dir",
            "/tmp/reports",
            "--budget-usd",
            "1.5",
            "--model",
            "some-model",
        ]
    )
    assert args.as_json is True
    assert args.fix_suggestions is True
    assert args.complexity_budget == 150
    assert args.staleness_days == 30
    assert args.output == "/tmp/report.md"
    assert args.report_dir == "/tmp/reports"
    assert args.budget_usd == 1.5
    assert args.model == "some-model"


# --- rejection ----------------------------------------------------------------


def test_an_unknown_focus_is_rejected(parse):
    with pytest.raises(SystemExit):
        parse(["skills", "/x", "--focus", "nonsense"])


def test_a_missing_command_is_rejected(parse):
    with pytest.raises(SystemExit):
        parse([])


def test_diff_demands_exactly_two_directories():
    with pytest.raises(SystemExit):
        cli.main(["skills", "diff", "/only-one"])


def test_top_level_help_lists_all_three_auditors(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "skills" in out and "instructions" in out and "maturity" in out


def test_version_is_reported(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert "agent-audit" in capsys.readouterr().out


# --- dispatch -----------------------------------------------------------------


@pytest.mark.parametrize(
    "argv, module",
    [
        (["skills", "/x"], "skills"),
        (["instructions", "/x"], "instructions"),
        (["maturity", "/x"], "maturity"),
    ],
)
def test_each_command_dispatches_to_its_module(monkeypatch, argv, module):
    seen = {}

    def fake_run(args):
        seen["command"] = args.command
        return 0

    monkeypatch.setattr(getattr(cli, module), "run", fake_run)
    assert cli.main(argv) == 0
    assert seen["command"] == module


def test_a_missing_cli_exits_with_a_message_not_a_traceback(monkeypatch, capsys):
    def explode(args):
        raise runner.AgentError("`claude` not found on PATH")

    monkeypatch.setattr(cli.skills, "run", explode)
    assert cli.main(["skills", "/x"]) == 2
    assert "not found on PATH" in capsys.readouterr().err
