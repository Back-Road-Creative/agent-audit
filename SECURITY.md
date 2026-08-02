# Security policy

## Supported versions

The latest released version is supported. Fixes land there; older versions are not
backported.

## Reporting a vulnerability

Report privately, not in the public issue tracker.

- Use GitHub's [private vulnerability
  reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
  on this repository, or
- email **backroadcreativeco@gmail.com** with `agent-audit security` in the subject.

Please include what you found, how to reproduce it, and what an attacker could achieve.
Expect an acknowledgement within a few days. This is a small project maintained in spare
time — there is no bounty, and no formal service level.

## What this tool touches

Useful context when judging severity:

- **It reads files you point it at.** Discovery is read-only; the only thing it writes is
  the report, at the path you chose.
- **It shells out to the `claude` CLI** and passes prompts as an argument. It never reads,
  stores or transmits API keys, and it makes no network requests of its own.
- **Prompts carry file *paths*, never file *contents*.** The analysis passes are told to
  open the files themselves, and everything untrusted is wrapped in an explicit data frame
  saying it is data rather than instructions. This is a mitigation for prompt injection
  from an audited file, not a guarantee against it.

## Known limits, not vulnerabilities

- **`--prompt-dir` executes prompts you supply.** That is its purpose. Do not point it at a
  directory you do not control.
- **Findings are unverified.** A report may name a line that does not exist or describe an
  attack that is not real. Treat findings as leads.
- **The audited files are untrusted input.** A hostile skill definition could try to
  influence a pass through its content. The data framing makes that harder; assume it is
  possible, and read reports on unfamiliar repositories with that in mind.
- **Reports may quote the files audited.** If you audit something sensitive, the report is
  as sensitive as its source. Do not publish reports you have not read.
