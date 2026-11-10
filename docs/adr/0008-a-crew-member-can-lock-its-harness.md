# A crew member can lock its harness

A crew member's `harness` field is a lock: that member always runs on that harness, whatever harness the lead runs. A member without it runs on the lead's harness. There is no softer "prefer" setting. An engineer who wants prose always written by Codex locks their writer member to Codex, and a Claude-led run still launches it on Codex.

The lock applies everywhere. Inside an Admiral ship the member runs as a crew boat (ADR 0006). Outside Admiral it runs through `drivers/<harness>`, turn-based on Codex and Copilot (ADR 0003). Under `ADMIRAL_AUTOPILOT=1`, where Admiral refuses Codex and Copilot boats, it runs headless. If the locked harness isn't installed, has no dock in the fleet or fails preflight, the run never swaps harnesses quietly. The member goes into phase 1's decision batch, where the engineer can run it on the lead's harness this time, pick another member, or stop. Inside Admiral that is a question item.

This loosens ADR 0002: one harness per run, except a crew member that locks another. Decided in [#193](https://github.com/jbuffin/skills/issues/193).

## Considered options

- **Keep one harness per run**: rejected. The engineer wants some work always done by a particular harness.
- **A preference that only holds inside Admiral**: rejected. The lock should mean the same in and out of a ship, and the per-harness drivers can already run a teammate on another harness.
- **Fall back to the lead's harness silently**: rejected. The engineer locked the harness on purpose.

## Consequences

ADR 0002's "Mixed runs" option is now taken, but only per member. The coordinator's guidance still comes from the lead's harness. Each locked member's launch, messages, status and stop go through its own harness's driver, so a run can use several drivers, as ADR 0006 already allows inside a ship.
