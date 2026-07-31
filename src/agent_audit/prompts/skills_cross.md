# Cross-skill analysis

You analyse the relationships *between* skills, not the quality of any one of them. This
runs after the per-skill passes, and you receive their findings alongside the discovery
manifest. Read the definitions you need in order to compare them.

Return one section per analysis below. A section with nothing to report keeps its `kind`
and carries an empty `findings` list — never drop the section.

## 1. Trigger overlap (`kind: "trigger-overlap"`)

Compare every pair of skills' trigger conditions — descriptions, keywords, invocation
language.

- **high** — near-identical triggers; one will shadow the other in practice.
- **medium** — significant overlap; which one fires is ambiguous for plausible inputs.
- **low** — keywords overlap but the purposes are clearly different.

Then run a collision check. For each of these requests, say which skills would plausibly
claim it, and flag every case where two or more would:

"review this code for bugs" · "make a new feature" · "run the tests" · "deploy this to
production" · "check security" · "write documentation" · "format this code" · "create a
PR" · "analyse this project" · "set up CI"

## 2. Dependency graph (`kind: "dependency-graph"`)

Map cross-references: skill A naming skill B, skill A dispatching an agent owned by B,
skill A reading files that live in B's directory.

- **high** — a cycle exists (A → B → A).
- **medium** — a chain deeper than three hops.
- **medium** — a skill depends on something absent from the manifest.

This section additionally carries a `mermaid` string holding a valid `graph TD` diagram
of the edges, with newlines as `\n`.

## 3. Convention consistency (`kind: "convention-consistency"`)

- Naming: inconsistent casing across skill names; agent names that do not follow one
  prefix pattern.
- Structure: some definitions carry frontmatter and others do not; frontmatter fields
  present in some and missing in others; heading structure that varies widely.
- Style: imperative in some, declarative in others; output formats that differ with no
  reason; tool restrictions that vary between agents doing similar work.

Each entry names what to converge on.

## 4. Gap analysis (`kind: "gap-analysis"`)

Check coverage across the categories a working repository usually needs: testing,
linting and formatting, building, deploying, documentation, code review, security, git
operations, debugging, configuration, monitoring, refactoring.

Mark each `covered`, `partial` or `gap`. Gaps are observations, not failures — calibrate
to the project's evident scope, and do not flag a missing deployment skill in a library.

## 5. Merge and decompose candidates (`kind: "merge-decompose"`)

- Merge: two skills close enough in purpose that one would serve, sharing most of their
  logic.
- Decompose: one skill covering several distinct concerns, or one over the complexity
  budget with clearly separable sections.

Be conservative with merges — only when the benefit is obvious.

## 6. Complexity budget (`kind: "complexity-budget"`)

Per skill, the definition's line count and the total across its agents, against the
budget in the active flags. Recommend a specific split where one is warranted.

## Rules

- Trigger overlap is about meaning, not string matching.
- The mermaid diagram must parse.
- These findings are about the *set*. Individual quality belongs to the other passes.
