# The build mission

The build mission turns a spec, an issue, a design doc or a free-text request into delivered work: planned into units, each built, reviewed and evaluated on the real target. Its task force is the roles in the Phase 2 table below.

Read this file before phase 1 in [`SKILL.md`](../SKILL.md). Phase 1 runs all six steps and picks the mode below. Then run Phase 2 and Phase 3 from this file.

## Autopilot mode

In autopilot mode ([Autopilot mode](../SKILL.md#autopilot-mode)), plan (phase 1 steps 1–4), draft the allow rules and list the secrets (step 5.1). Then put the whole decision batch, the secrets and step 2's cut question in one question item, report `partial` and stop. Resume and the push approval before each push follow [Autopilot mode](../SKILL.md#autopilot-mode) (Resume, No unattended pushes). This holds until autopilot builds land. With autopilot off, nothing here applies.

## Mode, sized to the work

| The work | Mode | Delivery |
| --- | --- | --- |
| One unit | single unit | one worktree, one draft PR |
| Several phases or passes, or related issues worked in order where each builds on the last | stack | one worktree per unit, a gh stack of draft PRs |
| Several issues that don't build on each other | independent units | one worktree and one PR each |
| Fixes to an existing PR: the [PR-feedback mission](mission-pr-feedback.md)'s delivery, or a PR the engineer explicitly asked to build on | existing PR | one worktree on its branch, no new PR |

Pick the mode in phase 1 and say which one and why in the decision batch. If the work turns out bigger or smaller than it looked, change it and tell the engineer. The chosen mode's section of [`modes.md`](modes.md) has its worktree commands and procedure.

## Phase 2: work, unit by unit

The workflow is fixed, but the task force changes with the work. Pick each unit's team from this table, and give each role its section of [`roles.md`](roles.md).

| Role | Does | Use when |
| --- | --- | --- |
| Brief checker | verifies every claim in a brief against the source of truth | always |
| Test writer | writes the unit's failing tests (or checks, for non-code work) from the source of truth | the behaviour can be pinned by tests or scripted checks |
| Implementer | builds the unit, then stays alive to fix its own findings | always |
| Reviewer | reviews the diff against the source of truth in round 1 and checks the fixes in round 2, fresh each round | always |
| Security reviewer | reviews the same diff for security vulnerabilities only, in round 1 | the run has a security role skill (without one, the engineer approved skipping it in the decision batch) |
| Target steward | owns the target for the whole run, does a light check each unit and full evaluations on target-evaluation's cadence | the work runs somewhere a user would touch it |
| Scribe | PR bodies, round-cap PR comments, notes | unless the run is tiny |

Every re-task of a live teammate follows the re-tasking paragraph under "Launch, re-task, close" in agent-teammates' `SKILL.md`: a fix round, a steward request, a CI fix, a late finding sent back to the implementer. That paragraph picks between `<teammates>/retask.sh` and `<teammates>/retasked.sh` for the run's harness. Write the new job to its [job file](../SKILL.md#re-task-job-files) first.

For each unit:

1. Write the brief, following [Briefs](../SKILL.md#briefs) in SKILL.md. Done when the brief checker reports no contradicted or unsourced claims.
2. The test writer goes red. Its tests all fail, and for the right reason.
3. The implementer goes green. Its suites and lint pass, the work is committed in the unit's worktree, and its proof verifies. Once it commits, start the next unit's test writer, as long as the next unit's source doesn't depend on this unit's review.
4. Review round 1 and evaluation run in parallel. First run `<team>/review-round.sh <run> <unit>`; it starts round 1 and names the reviewers to launch.
   - A fresh reviewer, launched `--read-only --role reviewer`, reviews the diff with its role skills, or its fallback when it has none.
   - A fresh security reviewer, launched `--read-only --role security-reviewer`, runs its role skills. Its brief gives the profile's security settings and the exact range to review: `<unit base>...HEAD`, where the unit base is the previous unit's branch, or the base branch for the first unit and in other modes. It's the unit's only security review.
   - The steward does the light check, and a full evaluation when target-evaluation's cadence calls for one (each unit counts as one change).
   - Record the reviewed SHA in `state.md`, and keep a list of unfixed non-blocking findings there: add each round's, and drop the ones the fix round resolves.

   Done when every report is in: the reviewer's, the security reviewer's when the run has one, and the light check's. If neither reviewer reported a blocking finding and the light check passed, go to step 6.
5. Run one fix round, then review round 2, the last. Merge both reviewers' blocking findings into one numbered list, label each with its source (reviewer / security), and write it to the [job file](../SKILL.md#re-task-job-files) the Phase 2 rule points to. Re-task the unit's implementer with that file, the way the re-tasking paragraph in agent-teammates' `SKILL.md` says (`retask.sh` or `retasked.sh`).
   - When fixes conflict, the security fix wins, and you record the decision in `state.md`.
   - The implementer may also fix trivial non-blocking findings in the same job. Trivial means a few lines inside the unit's own files with no other change in behaviour. Its report lists which non-blocking findings it fixed.
   - Then run `<team>/review-round.sh <run> <unit>`, which starts round 2, and launch one fresh reviewer, `--read-only --role reviewer`, on the fix range only: `<reviewed SHA>..HEAD`. Its brief gives the fix job and round 2's rules from its contract in [`roles.md`](roles.md#reviewer). No security reviewer runs in round 2; the reviewer checks that the security items were fixed. The steward re-checks anything user-visible.
   - Never start a round 3. When `review-round.sh` exits 1, launch no more reviewers for the unit, however the last round went.
   - Done when round 2's report and the light check are in. Anything left (a fix-job item not fixed, a round-2 finding, HIGH included, a failing light check) goes to a human: record it in `state.md` and list it in the round-cap PR comment, HIGH findings first.
6. Ship the way the mode says. The scribe writes the PR body first, and when the review left anything for a human, the round-cap PR comment listing it, posted once the PR exists. Then open a draft PR, run `gh stack submit --auto` or `gh stack push`, or run `<team>/push-branch.sh <run> <branch>` for the existing PR's branch. Run `<team>/watch-ci.sh <run> <branch>` in the background; it exits non-zero on red. Red CI gets fixed before anything builds on the unit.
7. Close the unit once CI is green. Mark the unit's trace rows, update `state.md`, close the unit's teammates and send the engineer the unit summary. Close the implementer last, because until then a finding from the reviewer, the security reviewer, the target or CI goes back to it.

## Unit summary to the engineer

```text
Unit N: <unit> (<PR or branch>, <state>)
Built: <one line>   Tests: <counts>   Target (<option used>): <light check passed/failed; full eval yes/no>
Advisor: <on | off for <roles>: <reason> | n/a (<harness>)>
Review: round k of 2, <fixed / left for human, HIGH first>
Security: <fixed / left for human / none / not reviewed: no security role skill>   Non-blocking: <n recorded>
Proof: <verify-report verdict>   Criteria closed: <ids from the trace>
CI: <green / red / running>
Not checked: <what nobody ran or looked at, and why | nothing>
Assumptions taken: <list | none>
Questions for you: <batched, with recommendation | none>
Next: <unit, role>
```

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
4. Leave the delivery the way the ground rules say. Every PR whose review left anything for a human has its round-cap comment.
5. Write the final report: units and PRs, "no security review: no security role skill" when the run had no security reviewer, the unfixed non-blocking findings from `state.md`, when and where the stop rule was observed, the acceptance trace with evidence, what wasn't checked, misses (where one of your briefs or decisions was wrong), open questions, carry-forward checks, approvals pending, and the next safe action. End it with a `result:` line: `done` only when the gate passed, otherwise `partial` and why. [Ending a run](../SKILL.md#ending-a-run) writes it into `state.md` and publishes the Admiral report; the run can also end `failed`.
6. Lessons go to the repo's own docs, as a proposed edit for the engineer to accept, whenever the run tripped over a missing or wrong instruction there.
