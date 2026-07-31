# Contributing

Bug reports, prompt improvements and new checks are all welcome.

## Getting set up

```bash
cd agent-audit
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

The suite runs in under a second and needs no network access, no API key, and no `claude`
CLI installed.

## The one rule that matters

**Ask whether the model needs to be involved at all.** Before adding a check to a prompt,
work out whether Python could answer it instead. A file's length, whether a referenced path
exists, how many headings a document has, when it was last modified — those are
measurements. Putting them in a prompt makes them slower, costlier and non-reproducible for
no gain.

The prompts exist for the questions that genuinely need judgment: is this instruction
ambiguous, is this attack realistic, would these two skills collide. If your check has one
correct answer, it belongs in `structural.py`, `discovery.py`, or a `measure` function.

## Pull requests

- One logical change per pull request.
- Tests come with behaviour changes. For a bug fix, write the failing test first and watch
  it fail before you fix it.
- Never subprocess the `claude` CLI from a test. Every auditor takes its `call` function as
  a keyword argument; inject a fake.
- Update the README in the same change if you alter a flag, a default, or a limit.
- Add a `CHANGELOG.md` entry under an `## Unreleased` heading.
- Keep lines under 100 characters. `ruff check .` and `ruff format --check .` should be
  clean.

## Changing a prompt

Prompt files under `src/agent_audit/prompts/` are part of the public surface — people fork
them with `--prompt-dir`. Say in the pull request what behaviour you expect to change and
why, and note if you have run it against a real project.

## Reporting a bug

Include the command you ran, what you expected, what happened, your Python version, and
your `claude --version`. If a report came out wrong, an abridged copy of it helps — with
anything private removed.

Security issues do not go in the issue tracker; see [SECURITY.md](SECURITY.md).
