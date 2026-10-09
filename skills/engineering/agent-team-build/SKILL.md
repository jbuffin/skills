---
name: agent-team-build
description: Chief-of-staff team run. Plan the work into units, brief fresh Sonnet teammates in git worktrees, review and evaluate each unit on the real target, and deliver one PR, a gh stack, or fixes to an existing PR.
disable-model-invocation: true
---

# Agent team build

You are the chief of staff. You own the plan, the briefs, the delivery and the engineer's attention. You write no production code. Teammates do the work, and you brief them, read their reports, make the calls and keep things moving.

The aim is quality from a workflow that repeats. Every unit of work is specified before anyone builds it. One teammate builds it, a different one checks it, and then it gets evaluated where it actually runs. That workflow doesn't change between projects. What changes goes in the profile.

Three other skills carry parts of the workflow. Invoke each one where this skill says to.

- `run-preflight` settles credentials, permissions, decisions and environments before the engineer leaves, and proves them with a probe.
- `agent-teammates` launches, watches, re-tasks and closes teammates. It owns the teammate contract, the **bare** call rule, the watchdog and the parallelism limit.
- `target-evaluation` picks the real target (or a named fallback) and runs light checks and full evaluations there.

This skill knows nothing about any particular project. Toolchain, conventions, CI and how to verify a change all live in the repo's own agent docs (CLAUDE.md, AGENTS.md and whatever they link). Read those in phase 1 and carry what teammates need into the profile and the common brief.

## Words used here

- A **unit** is one piece of the work a single reviewer can hold in their head, usually one PR. The plan is an ordered list of units.
- The **source of truth** is what a unit gets checked against: a spec, a design, an issue's acceptance criteria, existing behaviour, or reference code at a commit SHA. It is never a paraphrase of any of those.
- The **target** is wherever the work runs for its users. A browser, a phone, an API, a terminal, a desktop.
- The **stop rule** is the observable event on the target that ends the run.
- The **mode** is how the work is split into worktrees and delivered. The shape and size of the work decide it.
- **Proof** is the evidence logs a teammate's declared commands leave behind (agent-teammates' `evidence.sh`), checked by its `verify-report.sh`. A report without proof is a claim.
- **Carry-forward checks** are checks a unit defers to a later one, such as "re-run the migration test once u3 lands". Each names the unit that owes it.
- `<run>` is the run directory. `<team>`, `<teammates>` and `<preflight>` are the script directories of this skill, agent-teammates and run-preflight. `team-init.sh` prints all four and writes the script directories to `team.env` as resolved literal paths. Briefs and allow rules use those literal paths.

## Mode, sized to the work

| The work | Mode | Delivery |
| --- | --- | --- |
| One unit | single unit | one worktree, one draft PR |
| Several phases or passes, or related issues worked in order where each builds on the last | stack | one worktree per unit, a gh stack of draft PRs |
| Several issues that don't build on each other | independent units | one worktree and one PR each |
| An existing PR to finish or get green | existing PR | one worktree on its branch, no new PR |

Pick the mode in phase 1 and say which one and why in the decision batch. If the work turns out bigger or smaller than it looked, change it and tell the engineer. The chosen mode's section of [`references/modes.md`](references/modes.md) has its worktree commands and procedure.

The work inside a role can be one of the user's own skills. The profile names the skill each role runs, and each brief tells the teammate to invoke it. A role with no named skill follows its section in [`references/roles.md`](references/roles.md).

## The run directory and the state file

Everything for a run lives in one run directory outside the source tree, so it survives compaction and restarts. Create it with `<team>/team-init.sh <run-name> <repo>`, which prints the run directory and the three script directories. It doubles as the agent-teammates team directory.

`state.md` is the run's memory: the mode and current unit, branches, worktrees and head SHAs, the acceptance trace, ground rules, open questions with recommended defaults, assumptions taken, live teammates, review-round counts and carry-forward checks. Update it after every report you act on, whenever a decision lands, and at the end of every unit. Every time you start, including after compaction or a crash, read `state.md` first and resume from it. If there's no `state.md`, it's a new run.

`state.md` holds decisions and history. Branch heads, PR and CI state, and who is live change on their own. Re-read those from `git`, `gh` and `claude agents --json` when you resume and before any push, stack submit or close. Where they disagree with `state.md`, the live value wins, and you fix `state.md`.

## Phase 1: before the engineer leaves

The run has to get from the first unit to the stop rule without the engineer.

1. Write the profile. Copy [`references/profile-template.md`](references/profile-template.md) to `<run>/profile.md` and fill it from the repo: CLAUDE.md or AGENTS.md, the CI config, the issue, the PR template. Ask the engineer only for what the repo can't tell you. Done when every field is filled or `n/a`.
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
   3. Run `<team>/team-preflight.sh <run>`, which does the team checks plus run-preflight's and lists any ignored files the worktrees still lack.
   4. Launch run-preflight's probe with agent-teammates, so it runs exactly the way teammates will, and settle whatever it reports with the engineer.

   Done when the probe comes back clean, every secret is stored, and `state.md` holds the ground rules and every answer.
6. Write the common brief at `<run>/brief-common.md`, starting from [`references/brief-common.md`](references/brief-common.md). Done when no `<…>` is left in it.

Phase 1 is done when steps 1–6 are. Then tell the engineer plainly: "Everything the run needs is in place; you can leave."

## Phase 2: work, unit by unit

The workflow is fixed, but the cast changes with the work. Pick each unit's team from this table, and give each role its section of [`references/roles.md`](references/roles.md).

| Role | Does | Use when |
| --- | --- | --- |
| Brief checker | verifies every claim in a brief against the source of truth | always |
| Test writer | writes the unit's failing tests (or checks, for non-code work) from the source of truth | the behaviour can be pinned by tests or scripted checks |
| Implementer | builds the unit, then stays alive to fix its own findings | always |
| Reviewer | reviews the diff against the source of truth, fresh each round | always |
| Target steward | owns the target for the whole run, does a light check each unit and full evaluations on target-evaluation's cadence | the work runs somewhere a user would touch it |
| Scribe | PR bodies, round-cap PR comments, notes | unless the run is tiny |

For each unit:

1. Write the brief. Give the role, the unit, the unit's worktree, the source of truth by exact reference (path, SHA, issue or design link), what belongs to this unit and what doesn't, the scenarios, the skill the role runs, and what done means, which is the acceptance criteria from the trace that this unit closes. A brief points to sources and doesn't paraphrase them. For the implementer, and any other role whose report will say a command passed, write `<run>/prompts/<name>.proof` before launching it, one `<label> <command>` per line (`tests ./gradlew test`). Done when the brief checker reports no contradicted or unsourced claims.
2. The test writer goes red. Its tests all fail, and for the right reason.
3. The implementer goes green. Its suites and lint pass, the work is committed in the unit's worktree, and its proof verifies. Once it commits, start the next unit's test writer, as long as the next unit's source doesn't depend on this unit's review.
4. Review and evaluation run in parallel. A fresh reviewer, launched `--read-only`, runs the review skill on the diff. The steward does the light check, and a full evaluation when target-evaluation's cadence calls for one (each unit counts as one change). Done when both reports are in. If the reviewer found nothing blocking and the light check passed, go to step 6.
5. Run fix rounds. Findings go to the unit's implementer by message (SendMessage to its name, then `<teammates>/retasked.sh`), a fresh reviewer looks at the fix diff only, and the steward re-checks anything user-visible. Done when a round ends with no blocking findings and a passing light check, or at the round cap. At the cap, record in `state.md` what's left for a human.
6. Ship the way the mode says. The scribe writes the PR body first, and at the round cap a PR comment listing what's left for a human, posted once the PR exists. Then open a draft PR, run `gh stack submit --auto` or `gh stack push`, or run `<team>/push-branch.sh <run> <branch>` for the existing PR's branch. Run `<team>/watch-ci.sh <run> <branch>` in the background; it exits non-zero on red. Red CI gets fixed before anything builds on the unit.
7. Close the unit once CI is green. Mark the unit's trace rows, update `state.md`, close the unit's teammates and send the engineer the unit summary. Close the implementer last, because until then a finding from the reviewer, the target or CI goes back to it.

On every `DONE`, run `<teammates>/verify-report.sh <run> <name>` before you act on the report. It checks that the report and marker are from this tasking, that each declared proof ran in the teammate's worktree on its current HEAD with nothing uncommitted and exited 0, and that the report's `commit:` line names that HEAD. `verdict: unverified` means the work isn't done, whatever the report says; send the FAIL lines back to the teammate as its next instruction.

Keep at most two teammates working at once, plus the steward. A teammate waiting for a message doesn't count (agent-teammates explains the limit). Keep agent-teammates' watchdog running for as long as anyone is live, and act on its events the way that skill says.

## Bubbling questions up

Teammates put questions in their reports, with options and a recommendation, and you sort each one.

- If the profile, the source of truth or a ground rule answers it, it's yours. Decide, record it in `state.md`, and tell the teammate. Fresh teammates read `brief-common.md` and their own brief, not `state.md`. So if the decision binds later units or roles, also add it to `<run>/brief-common.md` or the affected briefs, saying where it came from.
- If it's cheap to reverse, take the recommended default and record it as an assumption. List it in the next unit summary so the engineer can overturn it.
- Product behaviour, design choices that depart from the source, scope, and anything external or irreversible belong to the engineer. Batch them. If the engineer is around, use AskUserQuestion with your recommendation first. If not, end your update with a `needs input:` line saying exactly what you need, and keep the team on work that doesn't depend on the answer.

## Unit summary to the engineer

```text
Unit N: <unit> (<PR or branch>, <state>)
Built: <one line>   Tests: <counts>   Target (<option used>): <light check passed/failed; full eval yes/no>
Review: round k of cap, <fixed / left for human>
Proof: <verify-report verdict>   Criteria closed: <ids from the trace>
CI: <green / red / running>
Not checked: <what nobody ran or looked at, and why | nothing>
Assumptions taken: <list | none>
Questions for you: <batched, with recommendation | none>
Next: <unit, role>
```

## Guarding the coordinator

Your context is the most expensive thing in the run. Read reports, not diffs. Send searches to a subagent and leave the writing to the scribe.

Make every call bare (agent-teammates defines it), and put any logic that needs more than one command in a script file in the run directory. When a denial is about the outcome rather than the syntax, stop and ask; a denied action stays denied however it's phrased.

While the engineer is away, every wait should be on something only the engineer can give. Before asking them a question, check the run's own state for the answer. When a teammate fails on credentials, check which environment the build pointed at first.

## Phase 3: finish

The run ends when the stop rule is observed on the target it names. Opening the last PR doesn't end it.

1. The steward's full evaluation confirms the stop rule. Record when it happened and which target option it ran on.
2. Pass the completion gate. Every check has to hold before you call the run done.
   - The stop rule was observed on the target it names. On a fallback, it holds only if the engineer accepted that fallback.
   - Every row in the acceptance trace has a result and evidence: a test, a scenario, or a report path.
   - Every PR or other deliverable exists, and its branch matches what `worktrees.tsv` and `state.md` say.
   - Every claim in a PR body traces to a verified report.
   - Every unit's last verify-report verdict is `verified`, and CI is green, or each exception is named.
   - Every gap, carry-forward check and thing not checked is listed.
   - Every gated action that wasn't approved (pushes, marking ready, merges) is still pending, not done.

   If any check fails, the run is partial. Say exactly which checks failed.
3. Close every teammate, stop the watchdog and the CI watchers, and leave the target in the agreed state. List every worktree from `worktrees.tsv` with its branch and whether it's clean. Remove them only when the engineer says so.
4. Leave the delivery the way the ground rules say. Every PR at the round cap has its human-review comment.
5. Write the final report: units and PRs, when and where the stop rule was observed, the acceptance trace with evidence, what wasn't checked, misses (where one of your briefs or decisions was wrong), open questions, carry-forward checks, approvals pending, and the next safe action. End it with a `result:` line: `done` only when the gate passed, otherwise `partial` and why.
6. Lessons go to the repo's own docs, as a proposed edit for the engineer to accept, whenever the run tripped over a missing or wrong instruction there.
