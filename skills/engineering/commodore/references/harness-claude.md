# Commodore on Claude Code

Read this when the run's `HARNESS` is `claude`, which is the default when `team.env` has no `HARNESS` line. agent-teammates has its own `references/harness-claude.md` for launching, messaging and watching.

## Default model per role

Launch every teammate with `--role <role>`. A fresh `team.env` from `team-init.sh` holds these defaults, and the profile overrides them:

| `--role` | Default model |
| --- | --- |
| `implementer`, `test-writer`, `target-steward` | sonnet |
| `reviewer`, `security-reviewer`, `brief-checker`, `triager` | opus |
| `scribe` | sonnet (haiku allowed) |

Outside an Admiral ship, for an in-process subagent after `NO_BG`, use the model the `NO_BG` message names. An in-process agent launched without a model runs on the coordinator's model.

## The capability rule on Claude

The rule is in [`roles.md`](roles.md#models). On Claude, if the coordinator runs above Opus, the profile sets the four roles to the coordinator's model, and `ADVISOR` has to rank at or above it too, or be in its family (see below).

## The advisor

A teammate launches with the advisor unless its model is in the same family as `ADVISOR` (default opus): then it has no advisor by design, because an advisor of the same family has no stronger judgement to offer and each consult re-reads the teammate's transcript. The rule follows models, not roles. On the default models the implementers, test writers, the target steward and the scribe (Sonnet) have the advisor, and the reviewers, security reviewers, brief checkers and the triager (Opus) have none by design. Unless `ADVISOR=none`, the launcher passes `--advisor $ADVISOR` on every other launch, read-only ones included, and `brief-common.md` tells each teammate when to consult it, or that it has none. A teammate's advisor sees only that teammate's own transcript. It never sees the work a reviewer judges, so reviewers stay independent of the implementer.

Three states, kept apart: **off** is a teammate that should have the advisor and doesn't, **n/a** is a harness with none, and **none by design** is a model in the same family as `ADVISOR`. Outside the same family, the advisor must rank at or above the teammate's model, and a pairing that doesn't hold starts without it and no error: that is off. `MODEL_REVIEWER=opus` with `ADVISOR=sonnet` leaves the reviewer without an advisor. A Fable main model accepts only a Fable advisor, so no setting gives a Fable teammate one: with `ADVISOR=fable` it has none by design, and with any other `ADVISOR` except `none` it gets `ADVISOR OFF`. Don't set `ADVISOR=fable` to get one. The preflight probes each distinct model that isn't in the same family as `ADVISOR` and reports `ADVISOR OFF` for each one that fails. For each model in the same family it starts no probe and prints `OK    no advisor for <model> (<roles>): same family as ADVISOR=<advisor>, by design`.

### When the advisor is off

A `WARN  ADVISOR OFF: <model> (<roles>): <reason>` line from `team-preflight.sh` means those roles would start without the advisor, and nothing else would tell you. A model with no advisor by design gets an `OK` line instead and needs none of this.

1. Before you launch any teammate, tell the engineer which roles are affected and why. If they've already left, put it in your next update and carry on.
2. Record it in `state.md` under Decisions and assumptions, and on the unit summary's `Advisor:` line.
3. Fix the cause only when it's cheap, then rerun the preflight:
   - `ADVISOR` ranks below the model: set `ADVISOR=opus`. A Fable teammate has no remedy, because no setting gives it an advisor (see above); tell the engineer and carry on.
   - The probe's hint names a variable such as `DISABLE_TELEMETRY`: unset it for the run.

Otherwise those roles still launch as background sessions, without the advisor. An in-process subagent wouldn't bring it back.

## Who is live

Re-read who is live with `claude agents --json` (inside an Admiral ship, `admiral crew list --json`) when you resume and before any push, stack submit or close.
