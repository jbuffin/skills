# Commodore on Codex

Read this when the run's `HARNESS` is `codex`. agent-teammates has its own `references/harness-codex.md` for launching, re-tasking, the rule lines and watching. Read it too, before your first launch and on every resume.

## Default model per role

Launch every teammate with `--role <role>`. A fresh `team.env` from `team-init.sh` holds these defaults, and the profile overrides them:

| `--role` | Default model | Default effort |
| --- | --- | --- |
| `implementer`, `test-writer`, `target-steward` | `gpt-6.1-sol` | medium |
| `reviewer`, `security-reviewer`, `brief-checker`, `triager` | `gpt-6-astra` | high |
| `scribe` | `gpt-6-luna` | medium |

The efforts weren't measured against each other. Treat them as a starting point, and change one in the profile (and `EFFORT_<ROLE>` in `team.env`) if a role's reports show it needs more or less. An empty `EFFORT_<ROLE>` passes no effort.

A launch that fails to start has no fallback on Codex: there's no `NO_BG` and no in-process subagent. agent-teammates' harness reference says what to do on exit 1.

## The capability rule on Codex

The reviewer, the security reviewer, the brief checker and the triager run `gpt-6-astra` at high effort, whatever model the coordinator runs on. Nothing has ranked the Codex models against each other or against a coordinator's model, so this rule is a default and unmeasured. If the engineer names a stronger model for these roles, put it in the profile.

## The advisor

There is no advisor on Codex. The preflight prints `ADVISOR n/a (codex)`, and Codex teammates get no `spawn_agent` stand-in. So:

- Drop "Asking the advisor" from `<run>/brief-common.md`, and drop the contract's "If your harness gives you an advisor…" line.
- Teammates write `none` under `## Advisor consults`. Don't expect consults, and don't read their absence as a brief problem.
- Skip the advisor sorting in "Bubbling questions up": every question that isn't answered by the profile, the source or a ground rule reaches you. Take the technical ones as the cheap-to-reverse defaults the section describes.
- Skip "When the advisor is off". It never applies.

## Who is live

Run `<teammates>/drivers/codex/status <run>` when you resume and before any push, stack submit or close. It prints `<thread-id> - <working|done|stopped> <mtime>` per session. There's no dashboard. `<teammates>/teammate-tail.sh <run> <name>` shows what one teammate is doing. A teammate whose turn has ended reads `done` until you re-task it.

## Fix rounds

An implementer keeps its context across fix rounds. Write the round's job to `<run>/prompts/<name>.job-<n>.md`, then run `<teammates>/retask.sh <run> <name> <run>/prompts/<name>.job-<n>.md` once its turn has ended. It resumes the same session. Reviewers, security reviewers and brief checkers launch fresh each round, as on any harness.

Run the watchdog as agent-teammates' reference says: `<teammates>/watch-teammates.sh --until-event <max-min> <run>`, as one bare call between jobs. Run it again after every exit while anyone is live.

## Where commodore says X, on Codex do Y

The rest of the skill is written for Claude Code. On Codex, apply these.

| Where the text says | On Codex |
| --- | --- |
| Use AskUserQuestion | Ask a plain question in your reply, with your recommendation first, and wait for the answer |
| Send searches to a subagent | There are no subagents. Search yourself, narrowly |
| Run `/code-review` or `/security-review` | Those are Claude Code skills. Do the equivalent review the role's section in `references/roles.md` describes, by hand |
| An allow rule is a `Bash(…)` line in settings | An allow rule is a `prefix_rule(pattern=[…], decision="allow")` line in `~/.codex/rules/*.rules`. Commodore needs only the five in agent-teammates' reference |
| An exact allow rule for each `evidence.sh` proof, or for each `gh api graphql` reply | Write neither. A prefix rule can't be exact, and `evidence.sh … -- <command>` would run anything. Writers run `evidence.sh` inside their sandbox. You post every GitHub reply, review and push yourself |
| The review mission's PR-controlled-config guard (`CLAUDE.md`, `.claude/`, `.mcp.json`) | Also cover, at least, the project files codex loads: `AGENTS.md` and `AGENTS.override.md` at any depth, and a project `.codex/` directory. Which files codex 0.162.0 loads isn't verified, so treat this list as a minimum |
| Run in the background or with the maximum Bash timeout | Use the Codex shell's own limit. Anything that can run longer than it (`team-preflight.sh`, `watch-ci.sh`) gets its own bare call and is re-run until it finishes |
| `ADVISOR OFF` and `harness-claude.md` | Never reached: the advisor is n/a |
| "The engineer can attach to a teammate" | They can't. Point them at `teammate-tail.sh` and `status` |

A read-only role's teammate contract differs too: see "The teammate contract" in agent-teammates' `SKILL.md`. Its report is its final message, so give it no `.proof`.
