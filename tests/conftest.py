"""Shared fixtures.

No test in this suite subprocesses the `claude` CLI. Every auditor takes its
`call` function as a keyword argument, so the tests inject a fake and exercise
the real prompt-building, aggregation and report-writing code paths without
spending tokens or requiring the CLI to be installed.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_audit.cli import build_parser, normalize_skills_argv


@pytest.fixture
def parse():
    """Parse an argv list exactly as the console script would."""

    def _parse(argv: list[str]):
        return build_parser().parse_args(normalize_skills_argv(argv))

    return _parse


@pytest.fixture
def envelope():
    """Build the result envelope a successful `claude -p --json-schema` run returns."""

    def _envelope(structured: Any) -> dict[str, Any]:
        return {"is_error": False, "result": "ok", "structured_output": structured}

    return _envelope


@pytest.fixture
def boxed_envelope(envelope):
    """Envelope for a schema that was array-wrapped into `{"items": [...]}`."""

    def _boxed(items: list[Any]) -> dict[str, Any]:
        return envelope({"items": items})

    return _boxed
