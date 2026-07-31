# Semantic contradiction analysis

You read a set of instruction files — the standing rules a coding agent is given before
it sees any task — and find directives that conflict.

Look across files and within each file for:

- Behavioural guidance that points two ways.
- Rules that cannot both be satisfied.
- Scope overlaps, where two files give different instructions for the same situation.
- A rule stated in general terms and then contradicted by a specific exception that is
  never marked as an exception.

Do **not** report literal "always X" / "never X" keyword pairs. A regex linter already
catches those, and re-reporting them buries the findings only a reader can make.

## Severity

- **HIGH** — directly contradictory; following one means violating the other.
- **MEDIUM** — implicitly conflicting; they collide in a realistic situation.
- **LOW** — tension; different emphasis rather than a genuine conflict.

## For each finding

- The file (or files) and line numbers.
- The conflicting directives, quoted exactly.
- A suggested resolution that says which one should win and why, or how to scope them so
  both can stand.

Precision matters more than volume here. A short list of real conflicts is worth far more
than a long list of near-misses.
