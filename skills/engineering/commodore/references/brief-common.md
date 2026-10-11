# Common brief template

<!-- markdownlint-disable MD025 MD033 -- a template: the second H1 starts the copied brief, and <…> are fill-ins, not HTML -->

Copy this to `<run>/brief-common.md` and fill every `<…>` from the profile, using literal absolute paths (the `team.env` values, never `$RUN`-style variables). Keep it under about 60 lines. Anything a role needs beyond this goes in that role's own prompt. Drop any section that doesn't apply.

---

# <run title>: common brief for every teammate

You're one member of a small team doing <what> (<issue link>). A chief of staff coordinates the team. Report to them, not to the engineer.

## Where you work

- Work only in the worktree your session started in, on its branch. Your brief names it.
- The base branch is `<base>` and delivery is <one PR | a stack | independent PRs | no PR>. Your work goes under `<path>`. `<protected paths>` stay untouched unless your brief names them.
- Commit, push, open PRs or write to GitHub only when your brief grants it. Pushes go through `<team>/push-branch.sh <run> <branch>`.

## Source of truth

<what the source of truth is for this run, such as "the accepted design doc at <link>", "the issue's acceptance criteria", or "the reference implementation at <path>@<sha>">

Comments and PR descriptions point at the truth. They aren't specifications. People often wrote them halfway through a PR, and the work moved on after. Check every claim in your brief against the source it points to. If the two disagree, the source wins, and you say so in your report.

## Toolchain and project rules

<pinned versions and why; layout; test framework rules; commands for tests, lint and build; known CI hazards; the project's own rules file (CLAUDE.md or AGENTS.md), which you should read>

## Secrets

Secrets reach a command only through run-preflight's helper, as a bare call: `<preflight>/secret-run.sh <service> <ENV_VAR> -- <command>`, or the target's typing helper if the profile names one. A secret's value stays out of everything you write, print or capture.

## Evaluation target

<target type and the option in use, from the profile>. Only the target steward uses it. Everyone else runs unit tests, or whatever their brief names.

## Asking the advisor

<Drop this section when the preflight printed `ADVISOR n/a`.>

Your session has a stronger model paired with it as an advisor. It reads your whole transcript on every call, has no tools and gives advice only. The teammate contract below says what to ask it and how to log each call; this section says when. If you have no advisor tool, skip it. You decide whether to call it; these are the moments it helps most:

- After you've looked around (read the files and the source of truth) but before substantive work: before the first edit, or before you settle on an interpretation.
- When you're stuck: the same error keeps recurring, the approach isn't converging, or the results don't fit.
- Before you change approach.
- Before you declare done, after you commit, so the work survives if the session ends.

Give its advice serious weight. Adapt only when a step fails when you try it, or primary-source evidence contradicts a specific claim. A passing self-test isn't evidence the advice is wrong.

If the advice conflicts with evidence you already have, don't switch quietly. Call the advisor once more: "I found X, you suggest Y; which constraint breaks the tie?"

## Working as a teammate

<Paste the "teammate contract" section of the agent-teammates skill here word for word, with <team-dir> set to this run directory and <teammates> to agent-teammates' scripts directory (TEAMMATES_SCRIPTS in team.env). Keep only the variant lines for the run's harness: the `LIVE_MESSAGING=1` lines when `LIVE_MESSAGING=1` in the harness's `driver.env`, the `LIVE_MESSAGING=0` lines when it is 0. When the preflight printed `ADVISOR n/a`, drop only the contract's "If your harness gives you an advisor…" line; always keep the `## Advisor consults` line, where teammates write `none`.>

Commit before you write your marker. The proof check fails on uncommitted changes, and they block the stack's cascade rebase.
