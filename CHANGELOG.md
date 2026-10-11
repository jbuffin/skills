# jasonbuffin-skills

## 0.3.0

### Minor Changes

- [#19](https://github.com/jbuffin/skills/pull/19) [`3dc121b`](https://github.com/jbuffin/skills/commit/3dc121bb0d96da37d02ab9196b6515b2aac22289) Thanks [@jbuffin](https://github.com/jbuffin)! - Choose each teammate's model by role. `launch-teammate.sh` takes `--model` and `--role` in any order, reads `MODEL_<ROLE>` from `team.env`, and refuses a launch with no model for its role. `REQUIRE_ROLE=1` makes a forgotten flag fail. `agent-team-build` records a model per role in the profile and writes the defaults into `team.env`.

- [#19](https://github.com/jbuffin/skills/pull/19) [`3dc121b`](https://github.com/jbuffin/skills/commit/3dc121bb0d96da37d02ab9196b6515b2aac22289) Thanks [@jbuffin](https://github.com/jbuffin)! - `agent-team-build` adds a security reviewer that runs in every review round alongside the reviewer, with merged, source-labelled findings, blocking and non-blocking severities, new profile security fields, and a `MODEL_SECURITY_REVIEWER` default in `team.env`. Both `agent-team-build` and `agent-teammates` now limit concurrency to two teammates that write, plus the steward; read-only teammates don't count.

- [#19](https://github.com/jbuffin/skills/pull/19) [`3dc121b`](https://github.com/jbuffin/skills/commit/3dc121bb0d96da37d02ab9196b6515b2aac22289) Thanks [@jbuffin](https://github.com/jbuffin)! - Give every teammate Claude Code's built-in advisor. In `agent-teammates`, `launch-teammate.sh` passes `--advisor $ADVISOR` (default `opus`, `none` turns it off) on every launch. The teammate contract asks for an `## Advisor consults` section in every report, and the common brief says when to consult. `team-preflight.sh` probes the advisor once per distinct teammate model with the new `advisor-probe.sh` and warns `ADVISOR OFF` where it didn't come on; `agent-team-build` tells the engineer before launching and reads the consults.

## 0.2.2

### Patch Changes

- [#5](https://github.com/jbuffin/skills/pull/5) [`803252f`](https://github.com/jbuffin/skills/commit/803252f8a8c65c80477062ac8d234d140ca7a88e) Thanks [@jbuffin](https://github.com/jbuffin)! - The skills are now MIT licensed ([#4](https://github.com/jbuffin/skills/pull/4)). Versions and this changelog are now managed with Changesets.

## 0.2.1

Versions up to here were bumped by hand, before Changesets.

- [#3](https://github.com/jbuffin/skills/pull/3): authoring guidelines in `AGENTS.md`, lint CI (shell, Markdown, Python, workflows, plugin, discovery) and a local denylist pre-commit hook.
- [#2](https://github.com/jbuffin/skills/pull/2): the engineering team skills explain themselves when one is used without the others.
- [#1](https://github.com/jbuffin/skills/pull/1): adds `agent-team-build`, `agent-teammates`, `run-preflight` and `target-evaluation`.
