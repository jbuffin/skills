# jasonbuffin-skills

## 1.2.0

### Minor Changes

- [#44](https://github.com/jbuffin/skills/pull/44) [`83df522`](https://github.com/jbuffin/skills/commit/83df5225e597d8ddff3bdaf8e926038f5fe45c3d) Thanks [@jbuffin](https://github.com/jbuffin)! - `agent-teammates` and `commodore` are now harness-aware, with Claude Code the supported harness today (Codex and Copilot CLI are planned, [#9](https://github.com/jbuffin/skills/issues/9)). `team-init.sh` detects the harness from where the run starts and writes `HARNESS` to `team.env`, and the Claude calls live in a driver under `agent-teammates/scripts/drivers/claude/`. The skill text is harness-neutral and reads `references/harness-<HARNESS>.md` for anything Claude-specific: sending work with SendMessage, running the watchdog under Monitor, the default model per role, and the advisor. The teammate contract has `LIVE_MESSAGING=1` and `LIVE_MESSAGING=0` variants. Claude runs behave as before.

## 1.1.0

### Minor Changes

- [#34](https://github.com/jbuffin/skills/pull/34) [`cd56724`](https://github.com/jbuffin/skills/commit/cd56724014ac7789d4498f4b281a086646567fda) Thanks [@jbuffin](https://github.com/jbuffin)! - `commodore` now works out the run's mission (`build`, `review` or `pr-feedback`) from what you point it at, confirms it with you before launching any teammate, and records it in `state.md`. Explicit wording such as "build [#17](https://github.com/jbuffin/skills/issues/17)" overrides detection. The existing flow is now the build mission, unchanged, and lives in `references/mission-build.md`.

- [#34](https://github.com/jbuffin/skills/pull/34) [`cd56724`](https://github.com/jbuffin/skills/commit/cd56724014ac7789d4498f4b281a086646567fda) Thanks [@jbuffin](https://github.com/jbuffin)! - `commodore` now runs a PR-feedback mission when you point it at your own open PR, even when only CI is failing; it no longer runs your own PR as a build mission. A new read-only `triager` role (`--role triager`, `MODEL_TRIAGER=opus` in a fresh `team.env`) sorts every unresolved review thread, top-level review comment and failing check into fix, push back, needs your call or already done, and drafts the push-back replies. You see people's and bots' feedback grouped separately, approve the fixes, answer every needs-your-call item and approve every reply before you leave. The fixes then run through the usual review loop and CI in existing-PR mode and are pushed with the run's push wrapper. After that, the approved replies are posted, fixed items cite their commit, fixed bot threads are resolved, and people's threads stay open. Nothing else is posted, not even at the review-round cap. Feedback that arrives during the run is listed in the final report and not acted on.

- [#34](https://github.com/jbuffin/skills/pull/34) [`cd56724`](https://github.com/jbuffin/skills/commit/cd56724014ac7789d4498f4b281a086646567fda) Thanks [@jbuffin](https://github.com/jbuffin)! - `commodore` now runs a review mission when you point it at someone else's open PR, including one from a fork. It creates detached worktrees on the PR's head (read-only for the reviewers), stops for your go-ahead when the repo's Claude Code project settings set anything beyond `permissions` deny and ask rules, when it defines MCP server commands, or when the PR changes agent config such as `CLAUDE.md` or `.claude/`, launches a fresh reviewer and security reviewer for one round on the PR's full range, who never run the PR's code, and adds the target steward only when the PR changes something a user would touch. Phase 1 skips Keychain secrets, push allow rules and the implementer probe. You get merged findings and a recommended verdict first, and nothing is posted until you approve. It then posts one GitHub review with inline comments, as `COMMENT` unless you choose `APPROVE` or `REQUEST_CHANGES`. The run never commits or pushes to the PR's branch. A finding on a file whose path contains a quote or a newline is kept in the review body, unverified and with the file name flagged.

### Patch Changes

- [#34](https://github.com/jbuffin/skills/pull/34) [`cd56724`](https://github.com/jbuffin/skills/commit/cd56724014ac7789d4498f4b281a086646567fda) Thanks [@jbuffin](https://github.com/jbuffin)! - `commodore` now writes a `result:` line into `state.md` when a run ends, and treats a run with that line as finished: it doesn't resume it, and a new run never reuses its directory. A new request checks only a run directory you name.

## 1.0.0

### Major Changes

- [#27](https://github.com/jbuffin/skills/pull/27) [`412f924`](https://github.com/jbuffin/skills/commit/412f924ee74594c3cfdafa84f75168b53c5e1ee1) Thanks [@jbuffin](https://github.com/jbuffin)! - Rename the `agent-team-build` skill to `commodore`. `/agent-team-build` (`/jasonbuffin:agent-team-build`) no longer exists, so call `/jasonbuffin:commodore`. The skill's behaviour, scripts and references are unchanged. A run started before the rename keeps the old resolved paths in its `team.env` (`SKILL=…/agent-team-build`, `TEAM_SCRIPTS=…`), because plugin installs are versioned.

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
