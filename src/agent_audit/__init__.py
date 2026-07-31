"""agent-audit — code-orchestrated auditors for AI-agent configuration.

Three auditors share one architecture:

1. Deterministic Python checks run first and produce a mechanical baseline.
2. Independent analysis passes run in parallel as `claude -p` subprocesses,
   each constrained by a JSON schema so the reply is data, not prose.
3. A code aggregator merges both into a markdown report.

The LLM never decides control flow, never picks a file path, and never
formats the report. It answers one scoped question per pass and returns JSON.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
