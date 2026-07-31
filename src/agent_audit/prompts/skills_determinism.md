# Skill determinism audit

You look for work a skill definition currently asks a model to do that a script could do
instead. This is the highest-value pass: every instruction that produces the same answer
every time, but is re-derived by a model on every run, is slower, costlier and less
reliable than the three lines of code it replaces.

You receive a discovery manifest. Read each definition in full.

## The three categories

**A — mechanical.** A deterministic decision tree; no creativity involved.

- File-type routing ("if `.py` use one linter, if `.js` use another").
- Path resolution ("look in `./config.yaml`, then the user config directory").
- Format detection ("check whether the file starts with `---`").
- Version and dependency checks.
- Template expansion.
- Input validation ("reject if the path does not exist").
- Status checks ("is the file writable?").

These belong in a script or structured config, not in a prompt.

**B — structured.** Real judgment, but heavily constrainable by an input/output contract.

- "Summarise these findings" — a template with slots.
- "Determine the best approach" — a ranked checklist.
- "Parse this file" — structured extraction with named fields.
- "Decide which category" — classification with explicit criteria per category.

These should become fill-in-the-blank contracts, not open-ended reasoning.

**C — judgment.** Genuinely needs a model: writing a commit message that captures intent,
evaluating whether a design holds together, explaining a concept, recommending an
architecture. These are correct as they stand.

## What to report

**Judgment-phrase detection.** Find every occurrence of "use your judgment", "figure
out", "determine", "decide", "as appropriate", "as needed", "if necessary",
"intelligently", "understand", "analyse and decide", and equivalents. For each, quote the
exact phrase with surrounding context and classify it A, B or C.

Use the `severity` field to carry the category: `should-be-code` for A,
`should-be-constrained` for B, `valid-judgment` for C.

**Runtime-computable logic.** Anything the model works out at run time that could be
settled once at install or setup time: dependency checks, template validation, path
resolution, format detection an extension check would answer.

**Decision trees in prose.** If/then/else chains described in sentences that map onto a
finite set of outcomes, and "based on the type of…" followed by a list of types with
specific actions. That is a routing table, not a judgment call — give the table.

**Chains that should be code.** "First determine X, then use X to decide Y, then use Y
to…" where each step has a deterministic output. Intermediate steps producing structured
data that is immediately consumed are code.

**Duplicated mechanical work.** The same operation spelled out in several places, or a
standard tool reimplemented as prose instructions.

## Rules

- Read every definition in full; these problems are scattered, not clustered.
- Default to category A and let the definition talk you out of it.
- Every A and B entry must carry a concrete replacement, not just "this could be code".
- Include category C entries so the analysis stays balanced, but never dress them up as
  problems.
- Some work is judgment once and mechanical thereafter — choosing a strategy versus
  applying it. Say so when that is what you see.
