# Commodore on Copilot CLI

Read this when the run's `HARNESS` is `copilot`. agent-teammates has its own `references/harness-copilot.md` for launching, re-tasking, the read-only checks, session storage and watching. Read it too, before your first launch and on every resume.

## Default model per role

Launch every teammate with `--role <role>`. A fresh `team.env` from `team-init.sh` holds these defaults, and the profile overrides them:

| `--role` | Default model | Default effort |
| --- | --- | --- |
| `implementer`, `test-writer`, `target-steward` | `claude-sonnet-5.5` | empty |
| `reviewer`, `security-reviewer`, `brief-checker`, `triager` | `claude-opus-5.5` | empty |
| `scribe` | `claude-haiku-5.5` | empty |

Every `EFFORT_<ROLE>` is empty, so a launch passes no `--reasoning-effort`. The driver passes the flag on launch and resume only when the role's effort is set, because some models reject it. Set one in the profile (and `EFFORT_<ROLE>` in `team.env`) only for a model that takes it. `MODEL` in `team.env` is `claude-sonnet-5.5`, the fallback for a launch without `--role`.

A launch that fails to start has no fallback on Copilot: there's no `NO_BG` and no in-process subagent. agent-teammates' harness reference says what to do on exit 1.

## The capability rule on Copilot

The reviewer, the security reviewer, the brief checker and the triager run `claude-opus-5.5`, whatever model the coordinator runs on. Nothing has ranked the Copilot models against each other or against a coordinator's model, so this rule is a default and unmeasured. If the engineer names a stronger model for these roles, put it in the profile.

## The advisor

There is no advisor on Copilot. The preflight prints `ADVISOR n/a (copilot)`, and Copilot teammates aren't told to use a custom agent through `task` as a stand-in. So:

- Drop "Asking the advisor" from `<run>/brief-common.md`, and drop the contract's "If your harness gives you an advisor…" line.
- Teammates write `none` under `## Advisor consults`. Don't expect consults, and don't read their absence as a brief problem.
- The advisor bullet in "Bubbling questions up" doesn't apply. Sort technical questions with the rest.
- Skip "When the advisor is off". It never applies.

## Who is live

Run `<teammates>/drivers/copilot/status <run>` when you resume and before any push, stack submit or close. agent-teammates' reference says how to read its lines. There's no dashboard. `<teammates>/teammate-tail.sh <run> <name>` shows what one teammate is doing.

## Fix rounds

An implementer keeps its context across fix rounds. Write the round's job to `<run>/prompts/<name>.job-<n>.md`, then run `<teammates>/retask.sh <run> <name> <run>/prompts/<name>.job-<n>.md` once its turn has ended. It resumes the same session. Reviewers, security reviewers and brief checkers launch fresh each round, as on any harness.

Run the three checks in agent-teammates' "Security caveats" (the state file, the `team.env` checksum and `git status --porcelain`) before each read-only re-task and any `close-teammate.sh`, and again after each read-only turn before you act on its report. The checks are the state-file checksum, the `team.env` checksum and the git config checksum, then `git status --porcelain`. Hold the baselines in your own context, not in the run directory, and launch read-only teammates in a linked worktree (the default). If one check fails, the run stops and you tell the engineer.

Run the watchdog in its bounded mode, as agent-teammates' "Run the watchdog" says. `DONE` can arrive before `status` reads `done`, so check `status` before you re-task.

## Sessions and closing

Sessions stay in `~/.copilot/session-state/`, stopping keeps them, and Copilot has no delete command. Close teammates with `close-teammate.sh`, and never run in its place any of the commands agent-teammates' "Closing" lists. Don't delete a session by hand.

## Where commodore says X, on Copilot do Y

The rest of the skill is written for Claude Code. On Copilot, apply these.

| Where the text says | On Copilot |
| --- | --- |
| Use AskUserQuestion | Ask a plain question in your reply, with your recommendation first, and wait for the answer |
| `ADVISOR OFF` and `harness-claude.md` | Never reached: the advisor is n/a |
| "The engineer can attach to a teammate" | They can't. Point them at `teammate-tail.sh` and `status` |

## Read-only roles

Launch the reviewer, security reviewer, brief checker and triager with both `--role` and `--read-only`; on Copilot the flag set follows `--read-only`, not the role. Their shell may run `gh pr view`, `gh pr diff` and `gh issue view`, plus `git log`, `git show`, `git diff` and `git status`, with any arguments, so `--output=<file>` writes a file (see "Security caveats" in agent-teammates' reference). agent-teammates' "How a read-only teammate reports" covers their report. Give them no `.proof`.

The flags are guardrails, not a sandbox, and a writer runs as the engineer. Read agent-teammates' "Security caveats" and put them to the engineer in the decision batch before an unattended run, then record the answer in `state.md`. The review mission raises the stakes, because the PR is someone else's and its text and code are untrusted: the reviewers read hostile text with a shell in reach, and the target steward is a writer that runs the PR's code.
