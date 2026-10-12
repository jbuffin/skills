# Commodore on Codex

Read this when the run's `HARNESS` is `codex`. agent-teammates has its own `references/harness-codex.md` for launching, re-tasking, the rule lines and watching.

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

Run `<teammates>/drivers/codex/status <run>` when you resume and before any push, stack submit or close. agent-teammates' reference says how to read its lines and map a thread id to a name. There's no dashboard. `<teammates>/teammate-tail.sh <run> <name>` shows what one teammate is doing.

## Fix rounds

An implementer keeps its context across fix rounds. Write the round's job to `<run>/prompts/<name>.job-<n>.md`, then run `<teammates>/retask.sh <run> <name> <run>/prompts/<name>.job-<n>.md` once its turn has ended. It resumes the same session. Reviewers, security reviewers and brief checkers launch fresh each round, as on any harness.

Run the watchdog in its bounded mode, as agent-teammates' "Run the watchdog" says. `DONE` can arrive before `status` reads `done`, so check `status` before you re-task.

## Where commodore says X, on Codex do Y

The rest of the skill is written for Claude Code. On Codex, apply these.

| Where the text says | On Codex |
| --- | --- |
| Use AskUserQuestion | Ask a plain question in your reply, with your recommendation first, and wait for the answer |
| Send searches to a subagent | There are no subagents. Search yourself, narrowly |
| Run `/code-review` or `/security-review` | Those are Claude Code skills. Do the equivalent review the role's section in `references/roles.md` describes, by hand |
| An allow rule is a `Bash(…)` line in settings | Teammates need only the two `git` rules in agent-teammates' "The `~/.codex/rules` lines". Your own calls (`gh`, the `<teammates>` and `<team>` scripts, file writes) stay out of `~/.codex/rules`, for the reason that section gives; the engineer approves them for your session through Codex's own approval |
| A read-only role runs `gh` (`gh pr diff`, `gh pr view`, `gh issue view`) | Read-only Codex roles have no network. You fetch that data into files in the run directory and name them in the brief (see "Read-only roles have no network") |
| An exact allow rule for each `evidence.sh` proof, or for each `gh api graphql` reply | Write neither. A prefix rule can't be exact, and `evidence.sh … -- <command>` would run anything. Writers run `evidence.sh` inside their sandbox. You post every GitHub reply, review and push yourself |
| The review mission's PR-controlled-config guard (`CLAUDE.md`, `.claude/`, `.mcp.json`) | Also cover, at least, the project files codex loads: `AGENTS.md` and `AGENTS.override.md` at any depth, and a project `.codex/` directory, plus the tracked hook directories (`.husky/`, `.githooks/`, whatever `core.hooksPath` names) and `.gitattributes`. Which files codex 0.162.0 loads isn't verified, so treat this list as a minimum |
| Run in the background or with the maximum Bash timeout | Use the Codex shell's own limit, and pass an explicit long timeout on the call |
| `ADVISOR OFF` and `harness-claude.md` | Never reached: the advisor is n/a |
| "The engineer can attach to a teammate" | They can't. Point them at `teammate-tail.sh` and `status` |

## Read-only roles have no network

Launch the reviewer, security reviewer, brief checker and triager with both `--role` and `--read-only`; on Codex the sandbox follows the flag, not the role. Their shell can't run `gh`, so fetch the GitHub data a brief points at (the source-of-truth issue, a PR's diff and body, comments) before the launch, save it to files in the run directory, and name the files in the brief. agent-teammates' "Sandbox per role" gives the HEAD and `git status` check to run around each read-only turn, and "How a read-only teammate reports" covers its report. Give it no `.proof`.

## Caveats to settle before a Codex run

Put every item in agent-teammates' "Known limits" to the engineer in the decision batch, and record each answer in `state.md`. Only start a Codex run whose writers you'd trust with the engineer's own shell. List the MCP servers in `~/.codex/config.toml` by name, and have the engineer disable for the run any that can write or post, or accept the risk.

The review mission raises the stakes, because the PR is someone else's and its text and code are untrusted:

- The reviewers read text an attacker wrote, with MCP tools in reach. Settle the MCP question before launching them.
- The target steward is a writer that runs the PR's code, with network, the `git` rules and write access to `<run>/reports`. On Codex, launch it only when the engineer trusts the PR's author. Otherwise skip it and list the light check as not done.
- Check both reviewers' reports against their events logs before you merge the findings, whether or not the steward ran.
