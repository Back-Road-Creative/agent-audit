# agent-audit

Three auditors for the configuration you give AI coding agents — the skill files, the
standing instruction files, and the overall shape of your setup. Deterministic checks run
first in Python; the parts that genuinely need a language model run as parallel,
schema-constrained passes; a code aggregator writes the report.

```
agent-audit skills .          # audit skill and agent definitions
agent-audit instructions .    # audit CLAUDE.md / AGENTS.md style instruction files
agent-audit maturity .        # classify components and emit graduation signals
```

## Why

Agent configuration is code that nothing compiles. A skill file can tell an agent to pipe
untrusted input into a shell, and nothing objects. Two instruction files can give opposite
orders, and the agent will follow whichever it read last. A memory file can assert a fact
that stopped being true in March. None of this shows up in a test run, a linter, or a code
review — it shows up as the agent behaving strangely, months later, in a way nobody can
reproduce.

The obvious fix is "ask a model to review it", and that fails in a specific way: the review
is different every time, it hallucinates file paths, and you cannot diff last month's
findings against this month's. So this tool inverts the split. Anything mechanical — which
files exist, how long they are, whether a referenced script is actually on disk, how many
tokens the instruction set costs — is computed in Python and is identical on every run.
The model is asked only the questions that need judgment, one scoped question per
subprocess, and must answer inside a JSON schema. It never decides control flow, never
picks a path, and never writes a line of the report.

## What each auditor does

### `skills` — skill and agent definitions

Globs every `SKILL.md` and every `*.md` under an `agents/` directory, then:

- **Structural (code, no model)** — missing or malformed frontmatter, a `name` that
  disagrees with its directory, stub-length files, no statement of when to invoke,
  referenced scripts that do not exist, bundled files nothing mentions, definitions over
  the complexity budget, and the external surface each one touches (URLs, environment
  variables, binaries it shells out to).
- **Security (model)** — code execution from untrusted input, credential handling, writes
  to sensitive paths, prompt-injection vectors, safety-rail bypasses, unpinned
  dependencies, agents holding tools their purpose does not need.
- **Quality (model)** — trigger specificity, self-contradiction, error handling,
  portability, undocumented dependencies, staleness.
- **Determinism (model)** — the highest-value pass. Every instruction that asks a model to
  do the same thing every time, with the concrete script that should replace it.
- **Cross-skill (model)** — trigger collisions between skills, dependency cycles,
  convention drift, coverage gaps, merge and decompose candidates.

Two sub-commands skip the model entirely: `manifest` dumps discovery as JSON, and `diff`
compares two skill sets structurally — cheap enough to run in CI as a drift check.

### `instructions` — standing instruction files

Finds the files loaded before every request (`AGENTS.md`, `CLAUDE.md`, `.cursorrules`,
`.windsurfrules`, `.clinerules`, `.continuerules`, `copilot-instructions.md`, skill and
command definitions, memory files), measures them, and runs three passes:

- **Contradictions** — directives that conflict across files or within one, with the
  conflicting text quoted and a suggested resolution.
- **Effectiveness** — each file scored 0-100 on clarity, specificity, enforceability and
  coverage, with a specific improvement for anything under 60.
- **Context optimisation** — what to cut, grounded in the measured token cost rather than
  guessed.

### `maturity` — is each piece in the right form?

Classifies skills, agents, pipelines and memory files against a maturity taxonomy:

- **STAY** — genuinely needs a model between runs.
- **GRADUATE_CODE** — does the same thing every time; should be a script.
- **GRADUATE_AGENT** — needs its own context window or tool autonomy; is being squeezed
  into a prompt.

Plus pipeline stage counts and coupling risk, and a staleness read on memory files.

## Install

```bash
pip install agent-audit
```

From a checkout:

```bash
pip install -e '.[dev]'
```

Requires Python 3.11 or newer. No third-party Python dependencies — the standard library
only.

### Runtime prerequisite: the `claude` CLI

The analysis passes shell out to the [Claude Code](https://www.anthropic.com/claude-code)
CLI, which must be installed and on your `PATH`. It uses whatever authentication that CLI
already has; this package never reads an API key, never opens a network socket of its own,
and passes no credentials of any kind.

```bash
claude --version   # must succeed before the model-backed passes will run
```

If the CLI is missing you get one clear error rather than a traceback. The deterministic
parts — `skills manifest`, `skills diff`, `--focus structural`, and the mechanical baseline
in every report — work without it.

Point `AGENT_AUDIT_CLAUDE_BIN` at a different executable if yours is not called `claude`.

### Windows installer

Each release also carries `agent-audit-setup-<version>.exe` on its
[releases page](https://github.com/Back-Road-Creative/agent-audit/releases) — agent-audit
frozen into one executable, so it needs no Python. It installs into Program Files, appends
that directory to the system `PATH`, and registers an uninstaller in Add/Remove Programs.
Open a *new* terminal afterwards; one that was already open still holds the old `PATH`.

Two things to know before downloading it.

**The `claude` CLI is not bundled.** The installer contains agent-audit and nothing else,
so the prerequisite above still applies: install [Claude Code](https://www.anthropic.com/claude-code)
separately and have `claude` on `PATH` before the model-backed passes will run. It is
separately distributed and separately authenticated, and no copy of it belongs inside this
installer. The deterministic commands — `skills manifest`, `skills diff`, `--focus
structural` — work without it.

**The build is not code-signed.** There is no code-signing certificate for this project, so
Windows cannot show you a publisher. Expect the blue *"Windows protected your PC"* box —
"Microsoft Defender SmartScreen prevented an unrecognized app from starting" — which runs
the installer only after **More info** → **Run anyway**, and expect your browser to warn
during the download. That is simply what an unsigned binary looks like; it is not evidence
the file is safe. If you would rather not make that call, `pip install agent-audit` needs no
installer.

## Usage

```bash
# Full skill audit of the current repository, with suggested fixes
agent-audit skills . --fix-suggestions

# Just the determinism pass, and a machine-readable sidecar
agent-audit skills . --focus determinism --json

# Structural checks only — no model, no cost, safe in CI
agent-audit skills . --focus structural

# Did our skill set drift? Compare two checkouts
agent-audit skills diff ./main-checkout ./branch-checkout

# Instruction files, measured against a smaller context window
agent-audit instructions . --context-window 100000

# Workflow maturity, written somewhere specific
agent-audit maturity . --output ./maturity.md
```

### Where reports go

By default, `./agent-audit-reports/<target-slug>/<date>-<kind>.md`. A second run on the
same day writes `-2`, a third `-3` — nothing is overwritten, so you can diff this week's
findings against last week's.

- `--report-dir DIR` moves the whole tree.
- `--output PATH` writes one exact file and ignores `--report-dir`.

### Cost control

`--budget-usd` is a runaway-loop ceiling per pass, not a spending target. A pass that trips
it returns nothing and its section of the report comes out empty, so setting it low does
not save money — it silently produces a worse report. The default is deliberately generous.

`--model` is passed straight through to the CLI, so you can run the cheap passes on a small
model.

### Forking the prompts

Every analysis prompt is plain markdown inside the package. Copy the ones you want to
change into a directory and pass `--prompt-dir`; same-named files win, and anything you did
not override falls back to the packaged copy.

```bash
agent-audit skills . --prompt-dir ./my-prompts
```

## Example output

Abridged, from a synthetic two-skill project:

```markdown
# Skill audit report

**Date:** 2026-01-15

## Summary

- Skills discovered: 2 (plus 1 agent)
- Structural pass / warn / fail (skills and agents): 0 / 3 / 0

## Per-skill scorecards

### deploy-service

- **Structural:** WARN — 1 clean, 2 warn, 0 fail
  - referenced-file-not-found: `rollback.sh` not found locally or under the root
  - external-binaries: Calls binaries: docker, git
- **security / high:** Builds a shell command from the user-supplied environment name
  with no escaping; a name of `staging; rm -rf /` runs as written.
  - **Fix:** Validate the name against an allow-list before interpolating it.
- **determinism / should-be-code:** "Figure out which environment file applies" is a
  three-branch lookup on the environment name.
  - **Fix:** A dict from environment name to config path.

## Cross-skill findings

### trigger-overlap

- `['deploy-service', 'release-notes']` — both fire on "ship it"; whichever loads
  second wins.

## Coverage gaps

_None — every pass returned parseable output._
```

## Limits

Worth knowing before you rely on it:

- **The model-backed passes are not reproducible.** Two runs over an unchanged repository
  will not produce identical findings. The structural checks and the mechanical baseline
  are exactly reproducible; treat those as the regression surface and the model findings as
  a prompt for human attention.
- **Findings are unverified.** Nothing checks that a reported line number exists or that a
  described attack is real. Read them as leads, not as facts.
- **Token counts are estimated** at four characters per token. Good enough to rank files by
  cost; not a substitute for a real tokeniser if you need an exact figure.
- **Discovery follows conventions.** `SKILL.md`, `agents/*.md`, and the instruction
  filenames listed above. A setup that names things differently will come back empty, and
  the report will say so rather than guessing.
- **Backups and fixtures are skipped** by path fragment (`/backups/`, `.bak`, `/evals/`,
  `/fixtures/`, `/node_modules/`). A backup directory named something else will be audited
  as if it were live.
- **`--focus structural` is the only genuinely free mode.** Everything else spends model
  time proportional to how much configuration you have.

## Development

```bash
pip install -e '.[dev]'
pytest
```

The suite never subprocesses the CLI. Every auditor takes its `call` function as a keyword
argument, so tests inject a fake and exercise the real prompt-building, aggregation and
report-writing paths without spending anything.

## Licence

MIT — see [LICENSE](LICENSE).
