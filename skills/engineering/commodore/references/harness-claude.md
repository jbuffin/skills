# Commodore on Claude Code

Read this when the run's `HARNESS` is `claude`, which is the default when `team.env` has no `HARNESS` line. agent-teammates has its own `references/harness-claude.md` for launching, messaging and watching.

## Default model per role

Launch every teammate with `--role <role>`. A fresh `team.env` from `team-init.sh` holds these defaults, and the profile overrides them:

| `--role` | Default model |
| --- | --- |
| `implementer`, `test-writer`, `target-steward` | sonnet |
| `reviewer`, `security-reviewer`, `brief-checker`, `triager` | opus |
| `scribe` | sonnet (haiku allowed) |

For an in-process subagent after `NO_BG`, use the model the `NO_BG` message names. An in-process agent launched without a model runs on the coordinator's model.

## The capability rule on Claude

The rule is in [`roles.md`](roles.md#models). On Claude, a coordinator above Opus sets the four roles to the coordinator's model, and `ADVISOR` has to rank at or above it too (see below).

## The advisor

Every role launches with the advisor: implementers, test writers, the target steward and the scribe, and also reviewers, security reviewers, brief checkers and the triager. The launcher passes `--advisor $ADVISOR` (default opus) on every launch, read-only ones included, and `brief-common.md` tells each teammate when to consult it. A teammate's advisor sees only that teammate's own transcript. It never sees the work a reviewer judges, so reviewers stay independent of the implementer.

The advisor must rank at or above the teammate's model, and a pairing that doesn't hold starts without it and no error. `MODEL_REVIEWER=opus` with `ADVISOR=sonnet` leaves the reviewer without an advisor. A Fable teammate needs `ADVISOR=fable`, since a Fable main model accepts only a Fable advisor. The preflight probes every distinct model and reports `ADVISOR OFF` for each one that fails.

### When the advisor is off

A `WARN  ADVISOR OFF: <model> (<roles>): <reason>` line from `team-preflight.sh` means those roles would start without the advisor, and nothing else would tell you.

1. Before you launch any teammate, tell the engineer which roles are affected and why. If they've already left, put it in your next update and carry on.
2. Record it in `state.md` under Decisions and assumptions, and on the unit summary's `Advisor:` line.
3. Fix the cause only when it's cheap, then rerun the preflight:
   - `ADVISOR` ranks below the model: set `ADVISOR=fable` for a Fable teammate, otherwise `ADVISOR=opus`.
   - The probe's hint names a variable such as `DISABLE_TELEMETRY`: unset it for the run.

Otherwise those roles still launch as background sessions, without the advisor. An in-process subagent wouldn't bring it back.

## Who is live

Re-read who is live with `claude agents --json` when you resume and before any push, stack submit or close.
