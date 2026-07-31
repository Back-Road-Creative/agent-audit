"""The workflow-maturity auditor: discovery, signals, domain scoping, report."""

from __future__ import annotations

import os
import time
from pathlib import Path

from agent_audit import maturity


def _populate(root: Path) -> None:
    skill = root / ".claude" / "skills" / "foo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# skill\n")
    agents = root / "agents"
    agents.mkdir()
    (agents / "helper.md").write_text("# agent\n")
    (root / "pipeline_main.py").write_text("# pipeline\n")
    (root / "orchestrator.py").write_text("# orchestrator\n")
    (root / "MEMORY.md").write_text("# memory\n")
    (root / ".mcp.json").write_text("{}")


# --- discovery ----------------------------------------------------------------


def test_components_are_bucketed_by_domain(tmp_path):
    _populate(tmp_path)
    components = maturity.discover_components(str(tmp_path))
    assert any(p.endswith("SKILL.md") for p in components["skills"])
    assert any(p.endswith("helper.md") for p in components["agents"])
    assert {Path(p).name for p in components["pipelines"]} == {
        "pipeline_main.py",
        "orchestrator.py",
    }
    assert any(p.endswith("MEMORY.md") for p in components["memory"])
    assert any(p.endswith(".mcp.json") for p in components["config"])


def test_an_empty_target_yields_empty_domains(tmp_path):
    assert all(v == [] for v in maturity.discover_components(str(tmp_path)).values())


def test_backups_and_fixtures_are_excluded(tmp_path):
    live = tmp_path / ".claude" / "skills" / "foo"
    live.mkdir(parents=True)
    (live / "SKILL.md").write_text("# live\n")
    for stale in (
        tmp_path / "backups" / "snap" / "SKILL.md",
        tmp_path / ".claude" / "skills" / "foo.bak-144205" / "SKILL.md",
        tmp_path / "evals" / "fixture" / "SKILL.md",
        tmp_path / "node_modules" / "pkg" / "SKILL.md",
    ):
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text("# stale\n")

    skills = maturity.discover_components(str(tmp_path))["skills"]
    assert len(skills) == 1
    assert skills[0].endswith(".claude/skills/foo/SKILL.md")


# --- mechanical signals -------------------------------------------------------


def test_signals_count_every_domain(tmp_path):
    _populate(tmp_path)
    signals = maturity.mechanical_signals(maturity.discover_components(str(tmp_path)))
    assert signals["counts"]["skills"] == 1
    assert signals["counts"]["pipelines"] == 2


def test_an_oversized_definition_is_flagged(tmp_path):
    skill = tmp_path / ".claude" / "skills" / "big"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("line\n" * (maturity.LONG_DEFINITION_LINES + 5))
    signals = maturity.mechanical_signals(maturity.discover_components(str(tmp_path)))
    assert signals["definitions"][0]["over_budget"] is True


def test_a_short_definition_is_not_flagged(tmp_path):
    skill = tmp_path / ".claude" / "skills" / "small"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("line\n" * 5)
    signals = maturity.mechanical_signals(maturity.discover_components(str(tmp_path)))
    assert signals["definitions"][0]["over_budget"] is False


def test_old_memory_is_flagged_as_unverified(tmp_path):
    memory = tmp_path / "MEMORY.md"
    memory.write_text("# memory\n")
    old = time.time() - (maturity.STALE_MEMORY_DAYS + 10) * 86400
    os.utime(memory, (old, old))
    signals = maturity.mechanical_signals(maturity.discover_components(str(tmp_path)))
    assert signals["memory"][0]["unverified_for"] is True
    assert signals["memory"][0]["age_days"] > maturity.STALE_MEMORY_DAYS


def test_fresh_memory_is_not_flagged(tmp_path):
    (tmp_path / "MEMORY.md").write_text("# memory\n")
    signals = maturity.mechanical_signals(maturity.discover_components(str(tmp_path)))
    assert signals["memory"][0]["unverified_for"] is False


# --- domain scoping -----------------------------------------------------------


def test_each_pass_sees_only_its_own_domains(parse, tmp_path):
    components = {
        "skills": ["/x/SKILL.md"],
        "agents": ["/x/agents/a.md"],
        "pipelines": ["/x/pipeline_a.py"],
        "memory": ["/x/MEMORY.md"],
        "config": [],
    }
    tasks = dict(
        (key, prompt)
        for key, prompt, _schema in maturity.build_tasks(
            components, {}, parse(["maturity", str(tmp_path)])
        )
    )
    assert "/x/SKILL.md" in tasks["graduation"]
    assert "/x/agents/a.md" in tasks["graduation"]
    assert "/x/pipeline_a.py" not in tasks["graduation"]
    assert "/x/pipeline_a.py" in tasks["pipeline"]
    assert "/x/MEMORY.md" in tasks["memory"]


def test_a_pass_with_no_files_says_so_rather_than_sending_an_empty_list(parse, tmp_path):
    tasks = dict(
        (key, prompt)
        for key, prompt, _schema in maturity.build_tasks(
            {"pipelines": []}, {}, parse(["maturity", str(tmp_path)])
        )
    )
    assert "no files discovered in this domain" in tasks["pipeline"]


# --- report -------------------------------------------------------------------


def test_report_contains_every_section(tmp_path, boxed_envelope):
    results = {
        "graduation": boxed_envelope(
            [
                {
                    "name": "discover-things",
                    "currentCategory": "skill",
                    "verdict": "GRADUATE_CODE",
                    "rationale": "pure glob, no judgment",
                }
            ]
        ),
        "pipeline": boxed_envelope(
            [
                {
                    "file": "pipeline_main.py",
                    "stages": 16,
                    "couplingRisk": "high",
                    "subPipelineCandidates": ["ingest", "encode"],
                }
            ]
        ),
        "memory": {"_error": "ceiling reached"},
    }
    output = tmp_path / "r.md"
    maturity.write_report(
        output=output,
        date="2026-01-02",
        target_dir="/proj",
        components={"skills": ["a"], "agents": [], "pipelines": ["b"], "memory": [], "config": []},
        signals={
            "definitions": [{"file": "a", "lines": 400, "over_budget": True}],
            "memory": [],
            "long_definition_lines": 200,
            "stale_memory_days": 180,
        },
        results=results,
    )
    text = output.read_text()
    assert "# Workflow maturity audit" in text
    assert "skills: 1" in text
    assert "Definitions over 200 lines: 1" in text
    assert "| discover-things | skill | GRADUATE_CODE | pure glob, no judgment |" in text
    assert "| pipeline_main.py | 16 | high | ingest, encode |" in text
    assert "memory: ceiling reached" in text


def test_empty_results_render_as_explicit_nothing(tmp_path, boxed_envelope):
    output = tmp_path / "r.md"
    maturity.write_report(
        output=output,
        date="2026-01-02",
        target_dir=".",
        components={"skills": [], "agents": [], "pipelines": [], "memory": [], "config": []},
        signals=maturity.mechanical_signals({}),
        results={
            "graduation": boxed_envelope([]),
            "pipeline": boxed_envelope([]),
            "memory": boxed_envelope([]),
        },
    )
    text = output.read_text()
    assert "_No assessments returned._" in text
    assert "_No pipelines assessed._" in text
    assert "_No memory files assessed._" in text
    assert "every pass returned parseable output" in text


# --- schema shape -------------------------------------------------------------


def test_every_pass_schema_survives_object_boxing():
    from agent_audit import runner

    for key, _prompt, schema, _domains in maturity.PASSES:
        assert runner.as_object_schema(schema)["type"] == "object", f"{key} is not boxable"


# --- run ----------------------------------------------------------------------


def test_run_writes_a_report_without_touching_the_cli(parse, tmp_path, boxed_envelope):
    target = tmp_path / "proj"
    target.mkdir()
    _populate(target)
    calls = []

    def fake(prompt, schema, **kwargs):
        calls.append(prompt)
        return boxed_envelope([])

    args = parse(["maturity", str(target), "--report-dir", str(tmp_path / "reports")])
    assert maturity.run(args, call=fake) == 0
    assert len(calls) == 3
    report = next((tmp_path / "reports").rglob("*-workflow-maturity.md"))
    assert "# Workflow maturity audit" in report.read_text()
