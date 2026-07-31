# Pipeline and orchestration assessment

You assess each pipeline or orchestrator file for size and coupling, and identify where
it should be split.

For each file report:

**Stage count.** How many distinct stages does the pipeline run? A stage is a step with a
name, an input and an output — not every function call.

**Coupling risk.**

- **low** — stages talk through well-defined interfaces or files. Any one could be rerun
  on its own given its inputs.
- **medium** — stages share mutable state, or the order matters implicitly and nothing
  enforces it.
- **high** — stages are interleaved; you cannot reorder or rerun one without breaking
  correctness, and the ordering constraint is not written down anywhere.

**Sub-pipeline candidates.** Clusters of two or more consecutive stages that are
independently testable and rerunnable, or that address a distinct concern from their
neighbours. Name each cluster by what it does.

## Hard signals

A pipeline with fifteen or more stages should be split regardless of how clean the
coupling looks. At that length nobody holds the whole thing in their head, and the
failure mode is a stage that silently stops running.

A pipeline where a late stage validates something an early stage produced — after an
expensive or irreversible step in between — has its gate in the wrong place. Report that
as a sub-pipeline boundary, because it is the split that saves the most.

## Rules

Read the files; do not infer structure from names. If a file named like a pipeline is
really a single linear function, say so — one stage and low coupling is a valid answer.
