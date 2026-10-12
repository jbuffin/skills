# Commodore on Copilot CLI

Read this when the run's `HARNESS` is `copilot`. agent-teammates has its own `references/harness-copilot.md` for launching, re-tasking, the security caveats, session storage and watching.

## Default model per role

Launch every teammate with `--role <role>`. A fresh `team.env` from `team-init.sh` holds these defaults, and the profile overrides them:

| `--role` | Default model |
| --- | --- |
| `implementer`, `test-writer`, `target-steward` | `claude-sonnet-5.5` |
| `reviewer`, `security-reviewer`, `brief-checker`, `triager` | `claude-opus-5.5` |
| `scribe` | `claude-haiku-5.5` |

Efforts default to empty. Set one in the profile only for a model that takes it; see the `EFFORT_<ROLE>` row in agent-teammates' settings. `MODEL` in `team.env` is `claude-sonnet-5.5`, the fallback for a launch without `--role`.

When a launch fails, see agent-teammates' "Fallback when a launch fails".

## The capability rule on Copilot

The reviewer, the security reviewer, the brief checker and the triager run `claude-opus-5.5`, whatever model the coordinator runs on. Nothing has ranked the Copilot models against each other or against a coordinator's model, so this rule is a default and unmeasured. If the engineer names a stronger model for these roles, put it in the profile.

## The advisor

There is no advisor on Copilot. The preflight prints `ADVISOR n/a (copilot)`, and Copilot teammates aren't told to use a custom agent through `task` as a stand-in. So:

- Drop "Asking the advisor" from `<run>/brief-common.md`, and drop the contract's "If your harness gives you an advisor…" line.
- Teammates write `none` under `## Advisor consults`. Don't expect consults, and don't read their absence as a brief problem.
- The advisor bullet in "Bubbling questions up" doesn't apply. Sort technical questions with the rest.

## Who is live

Run `<teammates>/drivers/copilot/status <run>` when you resume and before any push, stack submit or close. agent-teammates' reference says how to read its lines. There's no dashboard. `<teammates>/teammate-tail.sh <run> <name>` shows what one teammate is doing.

## Fix rounds

An implementer keeps its context across fix rounds. Write the round's job to `<run>/prompts/<name>.job-<n>.md`, then run `<teammates>/retask.sh <run> <name> <run>/prompts/<name>.job-<n>.md` once its turn has ended. It resumes the same session. Reviewers, security reviewers and brief checkers launch fresh each round.

A read-only teammate's surprising report stays unverified until `teammate-tail.sh` shows the turn that produced it.

Run the watchdog in its bounded mode, as agent-teammates' "Run the watchdog" says. `DONE` can arrive before `status` reads `done`, so check `status` before you re-task.

## Sessions and closing

Close teammates with `close-teammate.sh`. Sessions stay in `~/.copilot/session-state/`. See agent-teammates' "Closing".

## Where commodore says X, on Copilot do Y

The rest of the skill is written for Claude Code. On Copilot, apply these.

| Where the text says | On Copilot |
| --- | --- |
| Use AskUserQuestion | Ask a plain question in your reply, with your recommendation first, and wait for the answer |
| `ADVISOR OFF` and `harness-claude.md` | Never reached: the advisor is n/a |
| "The engineer can attach to a teammate" | They can't. Point them at `teammate-tail.sh` and `status` |

## Read-only roles

Launch the reviewer, security reviewer, brief checker and triager with both `--role` and `--read-only`; on Copilot the flag set follows `--read-only`, not the role. Their shell may run `gh pr view`, `gh pr diff` and `gh issue view`, plus `git log`, `git show`, `git diff` and `git status`, with any arguments, so `--output=<file>` writes a file (see "Security caveats" in agent-teammates' reference). agent-teammates' "How a read-only teammate reports" covers their report. Give them no `.proof`.

Before an unattended run on Copilot, tell the engineer in the decision batch that until Copilot's OS sandbox (#49) lands, any teammate that reads text from people other than the engineer is unsafe: read-only teammates can write any path, and writers run as the engineer. That rules out the review mission (someone else's PR) and the PR-feedback mission's triager and fix units on comments from untrusted people. Record the answer in `state.md`. Agent-teammates' "Security caveats" has the detail.
