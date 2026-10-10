# Profile template

Copy this to `<run>/profile.md`. Fill in every field, or write `n/a`. The profile is the only place project-specific facts live. The skill and the briefs point to it.

## Goal

- What's being done (feature, fix, refactor, migration, investigation, docs), the issue or epic link, and the work item if the project uses a tracker.
- Mode: single unit (one PR), stack (multi-phase, or related issues in order), independent units (one PR each), or existing PR (its number and what to do on it). Why this mode. The base branch.
- The skill each role runs, from the user's own skills. For example implementer `/tdd`, reviewer `/code-review`, PR body `/pr`. Leave a role blank to have it follow its section in roles.md.
- The model for each role (`MODEL_<ROLE>` in `team.env`): brief checker, test writer, implementer, reviewer, target steward, scribe. Defaults and the capability rule are in roles.md; write the role's model even when it is the default.
- The stop rule. That's the observable event that ends the run, and the build and target it happens on. It should be something a person could watch happen, not "the PRs are open".

## Units

| # | Unit | Branch | Source of truth (spec / issue / design / code @ SHA) | Roles (test writer? steward?) | Visible on the target? |
| --- | --- | --- | --- | --- | --- |

## Repository

- The repository checkout (`REPO` in `team.env`; nobody works in it), the base branch, and the branch prefix for the run's branches.
- `WORKTREE_SETUP`: the ignored files each worktree needs from the checkout (`copy:.env`, `clone:node_modules`), and why.
- Paths this work touches, reference paths if there are any, and protected paths nobody touches.
- Commands for unit tests, lint, instrumented or UI tests, and the release build. These become the proof lines in each teammate's `<run>/prompts/<name>.proof`.
- Toolchain pins and the reason for each.
- Project rules teammates have to follow, from CLAUDE.md or similar.
- The PR template, any required PR sections, and the title format (a work-item prefix, say).

## CI

- Workflow name and file, its jobs, and what triggers it (paths too).
- Known CI hazards and how to fix them.

## Evaluation target (the target-evaluation skill)

- The type, or several if the run spans more than one, and how the repo's docs say to run and verify on it.
- Options in order of preference, real thing first, and which one the stop rule needs.
- What identifies the target: a URL, a device id, an environment, a test tenant.
- The build or deployment used for testing, and why, if it isn't production's. Which environment it points at, where that comes from (an env file, a flag), and how to confirm it on the target before signing in.
- Who else uses it, and what stays untouched on it (production, the engineer's own sign-ins, shared data).
- The state to leave it in after each request.

## Secrets and accounts

- Keychain service names (`agent-team/<project>/<name>`) and what each one is for. Never the values.
- Test accounts, which environment they exist in, what data they have (tenants, record counts), and which scenarios that data supports.

## External systems

- Any system outside the repo that the run reads or writes, and the repo's doc for it.
- What the run may write there, as approved in pre-flight.

## Ground rules (from the engineer)

- The answers to the ground rules in SKILL.md phase 1, step 5, and anything the engineer added.
- When the engineer is and isn't available.
