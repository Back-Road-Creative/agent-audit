# Instruction effectiveness scoring

You score each instruction file on how well it will actually steer an agent. Read every
file in full.

Score each 0-100 on four dimensions:

**Clarity** — is each directive actionable and unambiguous? Could a competent reader
follow it without guessing? Vague verbs, undefined terms and implied context all cost
points.

**Specificity** — are the criteria measurable? "Keep changes small" scores low; "keep
diffs under 300 changed lines" scores high. A rule you cannot tell you have broken is
not a rule.

**Enforceability** — can the agent verify its own compliance? Is there a hook, a check,
a command, or a mechanical gate behind the rule, or does it rely entirely on the agent
remembering? Rules with a backstop score high.

**Coverage** — for files that govern general behaviour: do they address security, testing,
version control, filesystem boundaries and approval flow? A file with a narrow, stated
scope is not penalised for staying inside it.

For any dimension below 60, give a specific improvement — the sentence to change and what
to change it to, not "improve clarity".

Finally, rank the files by overall effectiveness (the mean of the four dimensions) and
name the three most impactful improvements across the whole set. Impact means how much
agent behaviour would change, not how easy the edit is.
