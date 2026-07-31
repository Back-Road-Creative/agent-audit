"""The `claude` CLI boundary: command construction, failure detection, fan-out."""

from __future__ import annotations

import json
import subprocess

import pytest

from agent_audit import runner


def _proc(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=["claude"], returncode=returncode, stdout=stdout, stderr=stderr
    )


# --- schema shaping -----------------------------------------------------------


def test_array_schema_is_boxed_in_an_object():
    # A top-level array is rejected as a tool input schema; the model then
    # retries forever and the run dies with a bare non-zero exit.
    wrapped = runner.as_object_schema({"type": "array", "items": {"type": "object"}})
    assert wrapped["type"] == "object"
    assert wrapped["required"] == ["items"]
    assert wrapped["properties"]["items"]["type"] == "array"


def test_object_schema_passes_through_untouched():
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    assert runner.as_object_schema(schema) is schema


def test_build_command_boxes_the_schema_it_sends():
    cmd = runner.build_command("hi", {"type": "array"}, budget_usd=1.0)
    schema = json.loads(cmd[cmd.index("--json-schema") + 1])
    assert schema["type"] == "object"


def test_build_command_omits_schema_and_model_when_unset():
    cmd = runner.build_command("hi", None, budget_usd=1.0)
    assert "--json-schema" not in cmd
    assert "--model" not in cmd
    assert "--no-session-persistence" in cmd


def test_build_command_passes_model_through():
    cmd = runner.build_command("hi", None, budget_usd=1.0, model="some-model")
    assert cmd[cmd.index("--model") + 1] == "some-model"


# --- failure detection --------------------------------------------------------


def test_clean_exit_is_not_a_failure():
    assert runner.failure_detail(_proc(0, json.dumps({"is_error": False}))) is None


def test_is_error_on_stdout_beats_a_zero_exit_code():
    # The trap this guards: a budget stop returns exit 0 with is_error set.
    detail = runner.failure_detail(_proc(0, json.dumps({"is_error": True, "subtype": "budget"})))
    assert detail is not None
    assert "subtype=budget" in detail


def test_error_envelope_details_beat_empty_stderr():
    # The other trap: stderr is empty, so a stderr-only message says nothing.
    envelope = json.dumps(
        {"is_error": True, "terminal_reason": "max_budget", "errors": ["ceiling reached"]}
    )
    detail = runner.failure_detail(_proc(1, envelope, stderr=""))
    assert "terminal_reason=max_budget" in detail
    assert "ceiling reached" in detail


def test_non_json_stdout_falls_back_to_stderr():
    detail = runner.failure_detail(_proc(1, "not json", stderr="boom"))
    assert "exit 1" in detail
    assert "boom" in detail


def test_no_output_at_all_still_says_something_useful():
    detail = runner.failure_detail(_proc(1, "", ""))
    assert "no stderr" in detail


# --- call_claude --------------------------------------------------------------


def test_missing_cli_raises_an_actionable_error(monkeypatch):
    def explode(*args, **kwargs):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(runner.subprocess, "run", explode)
    with pytest.raises(runner.AgentError, match="not found on PATH"):
        runner.call_claude("prompt", None)


def test_timeout_becomes_an_agent_error(monkeypatch):
    def explode(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=1)

    monkeypatch.setattr(runner.subprocess, "run", explode)
    with pytest.raises(runner.AgentError, match="timed out"):
        runner.call_claude("prompt", None, timeout_s=1)


def test_unparseable_success_becomes_an_agent_error(monkeypatch):
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: _proc(0, "{nope"))
    with pytest.raises(runner.AgentError, match="non-JSON"):
        runner.call_claude("prompt", None)


def test_successful_call_returns_the_parsed_envelope(monkeypatch):
    stdout = json.dumps({"structured_output": {"a": 1}})
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: _proc(0, stdout))
    assert runner.call_claude("prompt", None)["structured_output"] == {"a": 1}


# --- output unwrapping --------------------------------------------------------


def test_output_returns_dicts_and_swallows_anything_else():
    assert runner.output({"structured_output": {"a": 1}}) == {"a": 1}
    assert runner.output({"structured_output": [1, 2]}) == {}
    assert runner.output({}) == {}


def test_rows_unwraps_the_items_box():
    assert runner.rows({"structured_output": {"items": [{"n": 1}]}}) == [{"n": 1}]


def test_rows_still_accepts_a_bare_list():
    assert runner.rows({"structured_output": [{"n": 1}]}) == [{"n": 1}]


def test_rows_of_a_failed_pass_is_empty():
    assert runner.rows({"_error": "boom"}) == []


# --- fan_out ------------------------------------------------------------------


def test_fan_out_keys_results_by_task_name(envelope):
    def fake(prompt, schema, **kwargs):
        return envelope({"seen": prompt})

    results = runner.fan_out([("a", "prompt-a", None), ("b", "prompt-b", None)], call=fake)
    assert set(results) == {"a", "b"}
    assert results["a"]["structured_output"]["seen"] == "prompt-a"


def test_one_failing_pass_does_not_abort_the_others(envelope):
    def flaky(prompt, schema, **kwargs):
        if prompt == "prompt-a":
            raise runner.AgentError("ceiling reached")
        return envelope({"ok": True})

    results = runner.fan_out([("a", "prompt-a", None), ("b", "prompt-b", None)], call=flaky)
    assert "ceiling reached" in results["a"]["_error"]
    assert results["b"]["structured_output"] == {"ok": True}


def test_fan_out_forwards_budget_and_model():
    seen = {}

    def fake(prompt, schema, *, budget_usd, model):
        seen.update(budget_usd=budget_usd, model=model)
        return {}

    runner.fan_out([("a", "p", None)], budget_usd=2.5, model="m", call=fake)
    assert seen == {"budget_usd": 2.5, "model": "m"}


def test_fan_out_with_no_tasks_is_a_no_op():
    assert runner.fan_out([]) == {}


def test_coverage_gaps_lists_only_failures_in_stable_order(envelope):
    results = {"z": {"_error": "z broke"}, "a": {"_error": "a broke"}, "m": envelope({})}
    assert runner.coverage_gaps(results) == ["a: a broke", "z: z broke"]
