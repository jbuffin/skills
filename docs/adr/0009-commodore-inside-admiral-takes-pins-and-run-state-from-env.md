# Commodore inside Admiral takes pins and run state from env, never from launch text; Admiral report v2

AdmiralBot hands a team to Commodore through the normal launch, in autopilot mode, and gets the Admiral report back. The whole contract is keyed on env vars Admiral sets. Without them Commodore behaves as today.

**What goes in.** The launch text is the only prose: the order reference plus one free-text instruction AdmiralBot writes from the chat. A launch via AdmiralBot is the engineer's act at one remove, so there is no second brief channel. Pinned crew members come from the launch's `crew` field, not the text. Admiral resolves them in Go, writes the run layer (ADR 0007) and points Commodore at it with an env var. Inside Admiral, Commodore ignores pins found in launch text, so an order's body can never forge one. Run state, such as autopilot mode, comes from env the same way.

**Slices.** A launch with two or more issues is a slice, built as a gh stack. Commodore cuts units as it sees fit, but every child issue must be closed by exactly one PR in the stack. A child no PR closes is named in the Admiral report's `why`, and Admiral releases its claim when the ship sails off.

**Autopilot mode.** Admiral launches a ship in autopilot mode by default for every unattended launch: AdmiralBot's commitments, a campaign's Without-you children, scheduled and event routines, and review-wake rounds. Hand launches, and AdmiralBot launches on a current instruction the engineer marks "with me", stay interactive unless autopilot is ticked. Autopilot mode is always `ADMIRAL_LOW_STAKES=advisor`: low-stakes calls take the recommended default, and a high-stakes call becomes a question item and the run stops `partial`. Answering a stopped run's item wakes the same ship: Admiral types `/commodore resume <run>` into its prompt. Nothing merges on its own. Admiral's guard refuses every merge from an autopilot-mode ship, `gh pr merge --auto` included, and runs end with PRs ready for review.

**What comes back.** The Admiral report, never the transcript, feeds AdmiralBot's card and digest line. It moves to `version: 2`. `prs` become objects with `url` and `closes`, and an optional `cast` lists each crew member used, its role and whether it is ad hoc. Admiral accepts v1 and v2 for a while. Commodore publishes a fresh report at the end of every round (the first build and each PR-feedback round), overwriting the last.

Decided in [#195](https://github.com/jbuffin/skills/issues/195). Autopilot on every unattended launch and the guard refusing all merges come from [jbuffin/admiral#240](https://github.com/jbuffin/admiral/issues/240), which extended #195's rule from Commodore launches via AdmiralBot to every unattended launch.

## Considered options

- **Pins in the launch text**: rejected. An order's body is text from people who aren't the engineer, so it could forge a pin.
- **A second brief channel beside the launch text**: rejected. A launch via AdmiralBot is the engineer's act at one remove, and one free-text instruction carries it.
- **Auto-merge from autopilot-mode ships**: rejected. Merging stays the engineer's click in Admiral. If auto-merge is ever wanted, it comes back as a per-fleet limit AdmiralBot can't turn on.

## Consequences

This changes the Commodore skill's "Autopilot mode" section in `skills/engineering/commodore/SKILL.md`, with "Ending a run" step 2 and [`admiral-report.schema.json`](../../skills/engineering/commodore/references/admiral-report.schema.json) for report v2 and one report per round. The skill text follows in a later build PR. Until then the skill still writes v1 once per run.

Inside Admiral, ADR 0007's run layer is set from the env var Admiral sets, not from the launch text. Outside Admiral it is still set from the engineer's prompt.

The `gh pr merge --auto` path in "Marking ready" can no longer succeed inside Admiral, because the guard refuses it. The `never` value of `ADMIRAL_LOW_STAKES` is no longer set by Admiral.
