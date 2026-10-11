# Commodore is one skill with missions, not a set of narrow team skills

Commodore is the single entry point for any work that needs a team. It works out the mission (build, review, PR feedback) from what the engineer points it at, confirms it, and assembles that mission's task force. We kept it as one skill, despite AGENTS.md's "keep skills narrow", because the hard parts are shared by every mission: phase 1 pre-flight, the run directory and `state.md`, briefs, launching and watching teammates, fresh reviewers and the round cap. Splitting into a router plus per-mission skills would mean duplicating that machinery or extracting it into yet another skill that every mission depends on.

## Considered options

- **Thin router skill plus narrow per-mission team skills**: rejected; every mission skill would need the same phase 1 and run lifecycle.
- **Separate skills with no router**: rejected; the engineer would have to pick the right skill, which is the job commodore is meant to do.

## Consequences

Each mission's procedure lives in its own reference file next to the skill, the way delivery modes already do, so `SKILL.md` stays focused. If a mission grows into an unrelated job, split it out then.
