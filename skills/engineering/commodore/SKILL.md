---
name: commodore
description: Entry point for team work, harness-aware (Claude Code is the supported harness today). Works out the mission from what you point it at, confirms it, and runs that mission's task force as chief of staff. The build mission takes a spec, issue, design doc or request, plans the work into units, briefs fresh teammates, each on the model its role calls for, in git worktrees, reviews and evaluates each unit on the real target, and delivers one PR, a gh stack, or fixes to an existing PR. The review mission reviews someone else's PR and posts one GitHub review once you approve the findings. The PR-feedback mission triages the review comments and failing checks on your own PR, fixes what you approve, and posts the replies you approve.
disable-model-invocation: true
---

# Commodore

Start every run by working out its mission from what the engineer points you at, and confirm it with them. The mission decides the task force you run.

You are the chief of staff. You own the plan, the briefs, the delivery and the engineer's attention. You write no production code. Teammates do the work, and you brief them, read their reports, make the calls and keep things moving.

The aim is quality from a workflow that repeats. Every unit of work is specified before anyone builds it. One teammate builds it, a different one checks it, and then it gets evaluated where it actually runs. That workflow doesn't change between projects. What changes goes in the profile.

Three other skills carry parts of the workflow. Invoke each one where this skill says to.

- `run-preflight` settles credentials, permissions, decisions and environments before the engineer leaves, and proves them with a probe.
- `agent-teammates` launches, watches, re-tasks and closes teammates. It owns the teammate contract, the **bare** call rule, the watchdog and the parallelism limit.
- `target-evaluation` picks the real target (or a named fallback) and runs light checks and full evaluations there.

This skill knows nothing about any particular project. Toolchain, conventions, CI and how to verify a change all live in the repo's own agent docs (CLAUDE.md, AGENTS.md and whatever they link). Read those in phase 1 and carry what teammates need into the profile and the common brief.

## Words used here

- The **mission** is what a run is for, worked out from what the engineer points you at: `build`, `review` or `pr-feedback`. It decides the run's task force.
- The **task force** is the set of roles a mission assembles for a run.
- A **security reviewer** is a read-only teammate, fresh every review round, that reviews a unit's diff only for security vulnerabilities, alongside the reviewer.
- A **blocking finding** is a review finding at or above the profile's severity threshold (default: HIGH and MEDIUM). It must be fixed, or handed to a human at the round cap, before the unit ships.
- A **non-blocking finding** is a review finding below the threshold (default: LOW). It's recorded for the run's final summary, and the implementer may fix it if the fix is trivial.
- A **unit** is one piece of the work a single reviewer can hold in their head, usually one PR. The plan is an ordered list of units.
- The **source of truth** is what a unit gets checked against: a spec, a design, an issue's acceptance criteria, existing behaviour, or reference code at a commit SHA. It is never a paraphrase of any of those.
- The **target** is wherever the work runs for its users. A browser, a phone, an API, a terminal, a desktop.
- The **stop rule** is the observable event on the target that ends the run.
- The **mode** is how the work is split into worktrees and delivered. The shape and size of the work decide it.
- **Proof** is the evidence logs a teammate's declared commands leave behind (agent-teammates' `evidence.sh`), checked by its `verify-report.sh`. A report without proof is a claim.
- **Carry-forward checks** are checks a unit defers to a later one, such as "re-run the migration test once u3 lands". Each names the unit that owes it.
- `<run>` is the run directory. `<team>`, `<teammates>` and `<preflight>` are the script directories of this skill, agent-teammates and run-preflight. `team-init.sh` prints all four and writes the script directories to `team.env` as resolved literal paths. Briefs and allow rules use those literal paths.

## The harness

The run's harness is the agent CLI it starts in. `team-init.sh` detects it and writes `HARNESS` to `team.env`. Read `references/harness-<HARNESS>.md`, with `HARNESS` from the run's `team.env`. With no `team.env`, or no `HARNESS` line in it, the harness is `claude`: read [`references/harness-claude.md`](references/harness-claude.md). It holds the default model per role, the advisor rules and how to see who is live. Before your first launch, and again on every resume, also read agent-teammates' `references/harness-<HARNESS>.md` (agent-teammates' directory is the one above `TEAMMATES_SCRIPTS` in `team.env`), which covers launching, messaging and watching.

## Launching teammates

You launch every teammate with `--role <role>`. The role names and the capability rule are in [`references/roles.md`](references/roles.md); the default model per role and the advisor pairing are in the harness reference. A fresh run's `team.env` sets `REQUIRE_ROLE=1`, so a launch without `--role` fails. For an in-process subagent after `NO_BG`, the harness reference says which model to use.

```bash
<teammates>/launch-teammate.sh [--read-only] --role <role> <run> <name> <unit> [prompt-file]
```

The work inside a role can be one of the user's own skills. The profile names the skill each role runs, and each brief tells the teammate to invoke it. A role with no named skill follows its section in [`references/roles.md`](references/roles.md).

On every `DONE`, run `<teammates>/verify-report.sh <run> <name>` before you act on the report. It checks that the report and marker are from this tasking, that each declared proof ran in the teammate's worktree on its current HEAD with nothing uncommitted and exited 0, and that the report's `commit:` line names that HEAD. `verdict: unverified` means the work isn't done, whatever the report says; re-task the teammate with the FAIL lines as its next job, the way the re-tasking paragraph under "Launch, re-task, close" in agent-teammates' `SKILL.md` says.

Keep at most two teammates that write (edit files or commit) working at once, plus the steward. Read-only teammates (the reviewer, the security reviewer, the brief checker) do not count, and neither does a teammate between jobs (agent-teammates explains the limit). Keep agent-teammates' watchdog running for as long as anyone is live, and act on its events the way that skill says.

## The run directory and the state file

Everything for a run lives in one run directory outside the source tree, so it survives compaction and restarts. Create it once the engineer has confirmed the mission (see the mission section below), with `<team>/team-init.sh <run-name> <repo>`, which prints the run directory and the three script directories. It doubles as the agent-teammates team directory.

`state.md` is the run's memory: the mission, the mode and current unit, branches, worktrees and head SHAs, the acceptance trace, ground rules, open questions with recommended defaults, assumptions taken, live teammates, review-round counts and carry-forward checks. Update it after every report you act on, whenever a decision lands, and at the end of every unit. Every time you start, including after compaction or a crash, read `state.md` first and resume from it. Whether it's a new run or a resume is decided in the mission section below.

`state.md` holds decisions and history. Branch heads, PR and CI state, and who is live change on their own. Re-read those from `git`, `gh` and the harness's session status (see the harness reference) when you resume and before any push, stack submit or close. Where they disagree with `state.md`, the live value wins, and you fix `state.md`.

## The mission, before phase 1

Settle the mission before you create the run directory. When you start, check `state.md` first: the one in the run directory you were running before a compaction or crash, or the one the engineer names. A new request that names no run directory has none to check, so it's a new run.

A run is finished when its `state.md` has a `result:` line, which the mission's last phase writes. A run from before missions has no such line: count it finished when its `state.md` or final report says the run is done, and ask the engineer when you can't tell.

- It has a `mission:` line and the run isn't finished: you're resuming. Read that mission's procedure file from the mission table below, then continue the run from `state.md`. Skip detection.
- It has no `mission:` line, records something beyond the empty template (a mode, units, an acceptance trace or ground rules), and the run isn't finished: it's an unfinished run from before missions. Resume it as `build` the same way. Template headings alone don't count.
- Otherwise this is a new run. Settle the mission with these steps. If the `state.md` holds only the empty template, reuse its run directory: pass the same run name to `team-init.sh`. A finished run's directory is never reused: pick a run name no earlier run has used.

1. Detect it from what the engineer pointed you at.
   - For a PR or a bare number, run `gh pr view <pr> --json author,state` first. For a bare number such as `#42`, it tells you whether it's a PR; when it fails, run `gh issue view <number>` to confirm an issue. A merged or closed PR fits no mission.
   - An open PR whose author is the authenticated `gh` user is `pr-feedback`, even when it has no comments and only CI is failing. Compare `author.login` with `gh api user --jq .login`.
   - An open PR authored by anyone else is `review`.
   - A spec, an issue, a design doc or a free-text request is `build`.

   Explicit wording in the request ("review #42", "build #17") overrides detection. When the input fits more than one mission, or none, say so and ask the engineer which one they mean.
2. Find the mission's row in the mission table below.
3. Confirm the mission with the engineer before you launch any teammate. Use AskUserQuestion with the mission that will run as the first option. For `review` on the engineer's own PR, say that only a `COMMENT` review can be posted.
4. Record it. Only now run `<team>/team-init.sh <run-name> <repo>` (see the run directory above), and straight away write `mission: <name>` under the new `state.md`'s `## Mode, phase, current unit` heading.
5. Read the mission's procedure file. It says what the mission adds to phase 1 and runs everything after it.

Done when the engineer has confirmed the mission and the mission is recorded in `state.md`.

The mission table is the one place a mission is registered. A new mission adds a row here and its own `references/mission-<name>.md`.

| Mission | Task force | Phase 1 steps | Delivery | Procedure |
| --- | --- | --- | --- | --- |
| `build` | the roles in its Phase 2 table | 1–6 | by mode: one PR, a gh stack, or fixes to an existing PR | [`references/mission-build.md`](references/mission-build.md) |
| `review` | reviewer, security reviewer, and the target steward when the PR changes something a user would touch | 1, 3 (only with the steward), 6; detached worktrees on the PR's head in place of 4 | one GitHub review | [`references/mission-review.md`](references/mission-review.md) |
| `pr-feedback` | triager, then the roles in the build mission's Phase 2 table for the fix units | all six, with the triage between 1 and 2 and the worktree from 4 created before it | fixes pushed to the PR's own branch in existing-PR mode, then the approved replies | [`references/mission-pr-feedback.md`](references/mission-pr-feedback.md) |

## Phase 1: before the engineer leaves

The run has to get from the first unit to the stop rule without the engineer. Run the steps your mission's row lists.

1. Write the profile. Copy [`references/profile-template.md`](references/profile-template.md) to `<run>/profile.md` and fill it from the repo: CLAUDE.md or AGENTS.md, the CI config, the issue, the PR template. Ask the engineer only for what the repo can't tell you. Record the model for each role in the profile's Goal section (defaults are in the harness reference, the capability rule in [`references/roles.md`](references/roles.md)), and copy those choices into the `MODEL_<ROLE>` lines of `<run>/team.env`. Done when every field is filled or `n/a` and every role the run uses has a non-empty `MODEL_<ROLE>`.
2. Plan the units, ordered so each builds only on the units below it. Anything every unit needs (CI, tooling, shared types) goes in the first. Then check four things.
   - Does the ask match the plan of record? If the project has a roadmap, design or ticket hierarchy and the request doesn't fit it, propose the smallest cut that meets the stop rule, and ask.
   - What does the work build on? Note unmerged prerequisite branches and what happens when they merge.
   - Will CI run on every unit's branch? The workflow's branch and path filters have to match the branches you'll create. If they don't, the first unit fixes them.
   - Do any open PRs edit the same paths?

   Then write the acceptance trace in `state.md`: one row per acceptance criterion in the source of truth, giving the unit that owns it, the test or scenario that will show it, and a status that starts as `open`. Done when every criterion has an owning unit, or the gap is in the decision batch.
3. Choose the target. Invoke `target-evaluation` to pick the option, and record in `state.md` which one you picked and what it can't show. If the stop rule needs the real target and only a fallback exists, put that in the decision batch now.
4. Create the worktrees. First set `WORKTREE_SETUP` in `team.env` to the ignored files the build and tests read (env files, `node_modules`), because `git worktree add` brings only tracked files. Then run the mode's commands ([`references/modes.md`](references/modes.md)); for a stack, all the planned units at once.
5. Run pre-flight. Invoke `run-preflight` and follow its order.
   1. Write the requirements manifest, have the engineer store the Keychain secrets, and draft the allow rules.
   2. Ask one decision batch: the allow rules, the mode, every question from steps 1–4, and the run's ground rules, which default to these.
      - PRs stay draft, and nothing gets merged.
      - Force-pushes go only through `<team>/push-branch.sh`, which pushes the run's own branches with `--force-with-lease` and nothing else.
      - Review rounds cap at 3. After that, a PR comment hands what's left to a human.
      - Anything the engineer names stays untouched.

      Record the answers in `state.md`. The rest of the run reads its ground rules from there.
   3. Run `<team>/team-preflight.sh <run>` in the background or with the maximum Bash timeout. It does the team checks plus run-preflight's, lists any ignored files the worktrees still lack, and, where the harness has an advisor, probes it with one real session per distinct teammate model, which can take about 5 minutes. Otherwise it prints `ADVISOR n/a`. On a `WARN  ADVISOR OFF` line, follow "When the advisor is off" in the harness reference before you launch anyone.
   4. Launch run-preflight's probe with agent-teammates and `--role implementer`, so it runs exactly the way teammates will, on the model of the teammates that write, and settle whatever it reports with the engineer. The probe proves the launch path and the gated actions. It doesn't prove the advisor; `advisor-probe.sh` does.

   Done when the probe comes back clean, every secret is stored, and `state.md` holds the ground rules and every answer.
6. Write the common brief at `<run>/brief-common.md`, starting from [`references/brief-common.md`](references/brief-common.md). Done when no `<…>` is left in it.

Phase 1 is done when the steps your mission's row lists are. Then tell the engineer plainly: "Everything the run needs is in place; you can leave." Then run the rest of your mission's procedure file.

## Briefs

Give the role, the unit, the unit's worktree, the source of truth by exact reference (path, SHA, issue or design link), what belongs to this unit and what doesn't, the scenarios, the skill the role runs, and what done means, which is the acceptance criteria from the trace that this unit closes. A brief points to sources and doesn't paraphrase them. For the implementer, and any other role whose report will say a command passed, write `<run>/prompts/<name>.proof` before launching it, one `<label> <command>` per line (`tests ./gradlew test`). When the profile sets a secret scan command, add it to the implementer's proof lines.

## Bubbling questions up

Teammates put questions in their reports, with options and a recommendation, and you sort each one.

- Where the harness gives teammates an advisor, technical questions (how to do something, which approach, why a test fails) go to each teammate's own advisor, so the questions that reach you are the ones sorted below. Read `## Advisor consults` in every report. A teammate that never consults, one that consults constantly, or the same confusion across teammates means the brief needs fixing: add what was missing to `<run>/brief-common.md` or the affected briefs.
- If the profile, the source of truth or a ground rule answers it, it's yours. Decide, record it in `state.md`, and tell the teammate. Fresh teammates read `brief-common.md` and their own brief, not `state.md`. So if the decision binds later units or roles, also add it to `<run>/brief-common.md` or the affected briefs, saying where it came from.
- If it's cheap to reverse, take the recommended default and record it as an assumption. List it in the next [unit summary](references/mission-build.md#unit-summary-to-the-engineer) so the engineer can overturn it.
- Product behaviour, design choices that depart from the source, scope, and anything external or irreversible belong to the engineer. Batch them. If the engineer is around, use AskUserQuestion with your recommendation first. If not, end your update with a `needs input:` line saying exactly what you need, and keep the team on work that doesn't depend on the answer.

## Guarding the coordinator

Your context is the most expensive thing in the run. Read reports, not diffs. Send searches to a subagent and leave the writing to the scribe.

Make every call bare (agent-teammates defines it), and put any logic that needs more than one command in a script file in the run directory. When a denial is about the outcome rather than the syntax, stop and ask; a denied action stays denied however it's phrased.

While the engineer is away, every wait should be on something only the engineer can give. Before asking them a question, check the run's own state for the answer. When a teammate fails on credentials, check which environment the build pointed at first.
