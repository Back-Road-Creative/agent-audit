# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.1.1 - 2026-08-03

### Added

- Windows installer. Pushing a `v*` tag builds a PyInstaller one-file
  executable on `windows-latest`, wraps it with Inno Setup, and attaches the
  installer to that tag's GitHub release. The installer adds the command to
  the machine PATH and registers an uninstaller. `workflow_dispatch` runs the
  same build and publishes nothing, keeping the installer as an artifact.
- The build is unsigned, so Windows SmartScreen warns on first run.
- The Claude Code CLI is required at runtime and is not bundled.

## 0.1.0 — 2026-07-31

First release.

### Added

- `agent-audit skills` — audits skill and agent definitions. Deterministic structural
  checks (frontmatter, naming, stub length, trigger language, dangling file references,
  orphaned assets, complexity budget, external surface) followed by parallel security,
  quality and determinism passes and a cross-skill pass.
- `agent-audit skills manifest` — discovery only, emitted as JSON. No model involved.
- `agent-audit skills diff` — structural comparison of two skill sets. No model involved,
  so it is cheap enough for CI.
- `agent-audit instructions` — audits standing instruction files for semantic
  contradictions, effectiveness (clarity, specificity, enforceability, coverage) and
  context cost, over a measured token baseline.
- `agent-audit maturity` — classifies skills, agents, pipelines and memory files against a
  maturity taxonomy (STAY / GRADUATE_CODE / GRADUATE_AGENT), with pipeline coupling
  assessment and memory staleness signals.
- Report paths default to `./agent-audit-reports/<slug>/<date>-<kind>.md` and are numbered
  on repeat runs, so nothing is overwritten. `--report-dir` and `--output` override.
- Analysis prompts ship as plain markdown and can be overridden per-file with
  `--prompt-dir`.
- A pass that fails, times out or exhausts its budget is reported under "Coverage gaps"
  rather than aborting the run or silently vanishing from the report.
