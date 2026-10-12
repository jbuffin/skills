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
- The advisor bullet in "Bubbling questions up" doesn't apply. Sort technical questions with the rest.
- Skip "When the advisor is off". It never applies.

## Who is live

Run `<teammates>/drivers/codex/status <run>` when you resume and before any push, stack submit or close. It prints `<thread-id> - <working|done|stopped> <mtime>` per session; map a thread id to a name through column 2 of `<run>/teammates.tsv`. A teammate closed after its turn ended still reads `done`; the registry's `closed` row marks it closed. There's no dashboard. `<teammates>/teammate-tail.sh <run> <name>` shows what one teammate is doing. A teammate whose turn has ended reads `done` until you re-task it.

## Fix rounds

An implementer keeps its context across fix rounds. Write the round's job to `<run>/prompts/<name>.job-<n>.md`, then run `<teammates>/retask.sh <run> <name> <run>/prompts/<name>.job-<n>.md` once its turn has ended. It resumes the same session. Reviewers, security reviewers and brief checkers launch fresh each round, as on any harness.

Run the watchdog as agent-teammates' reference says: `<teammates>/watch-teammates.sh --until-event <max-min> <run>`, as one bare call between jobs, with an explicit long timeout on the call and `<max-min>` under it. Run it again after every exit while anyone is live. `DONE` can arrive before `status` reads `done`: check `status` before you re-task.

## Where commodore says X, on Codex do Y

The rest of the skill is written for Claude Code. On Codex, apply these.

| Where the text says | On Codex |
| --- | --- |
| Use AskUserQuestion | Ask a plain question in your reply, with your recommendation first, and wait for the answer |
| Send searches to a subagent | There are no subagents. Search yourself, narrowly |
| Run `/code-review` or `/security-review` | Those are Claude Code skills. Do the equivalent review the role's section in `references/roles.md` describes, by hand |
| An allow rule is a `Bash(…)` line in settings | Teammates need only the two `git` rules in agent-teammates' reference. They run outside the sandbox on every Codex session on the machine, so writers effectively run with the engineer's permissions (follow-up [#66](https://github.com/jbuffin/skills/issues/66)). Never turn your own calls (`gh`, `push-branch.sh`, `retask.sh`, `launch-teammate.sh`, `close-teammate.sh`, file writes) into user-level `prefix_rule` lines: every writer would inherit them outside its sandbox. The engineer approves them for your session through Codex's own approval, which is unverified from inside a real Codex session. If a rule is unavoidable, limit it to a read-only command (`<teammates>/drivers/codex/status`, `watch-teammates.sh --until-event`, `verify-report.sh`) and check that no argument turns it into a write |
| An exact allow rule for each `evidence.sh` proof, or for each `gh api graphql` reply | Write neither. A prefix rule can't be exact, and `evidence.sh … -- <command>` would run anything. Writers run `evidence.sh` inside their sandbox. You post every GitHub reply, review and push yourself |
| The review mission's PR-controlled-config guard (`CLAUDE.md`, `.claude/`, `.mcp.json`) | Also cover, at least, the project files codex loads: `AGENTS.md` and `AGENTS.override.md` at any depth, and a project `.codex/` directory, plus the tracked hook directories (`.husky/`, `.githooks/`, whatever `core.hooksPath` names) and `.gitattributes`. Which files codex 0.162.0 loads isn't verified, so treat this list as a minimum |
| Run in the background or with the maximum Bash timeout | Use the Codex shell's own limit, and pass an explicit long timeout on the call |
| `ADVISOR OFF` and `harness-claude.md` | Never reached: the advisor is n/a |
| "The engineer can attach to a teammate" | They can't. Point them at `teammate-tail.sh` and `status` |

## Read-only roles have no network

Read-only Codex roles (reviewer, security reviewer, brief checker, triager) launch with their sandbox read-only and the user's rules ignored, so they write nothing and can't run `gh`. Fetch any GitHub data a brief points at (the source-of-truth issue, a PR's diff and body, comments) yourself before the launch, save it to files in the run directory, and name the files in the brief. Before you launch or re-task a read-only role, record its worktree's `git -C <worktree> rev-parse HEAD` and `git -C <worktree> status --short`, and run it only while no writer in that worktree is `working`. After the turn, both must match. A change means the isolation failed: stop and ask the engineer.

A read-only role's teammate contract differs too: see "The teammate contract" in agent-teammates' `SKILL.md`. Its report is its final message, so give it no `.proof`.
