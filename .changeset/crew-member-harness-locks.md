---
"jasonbuffin-skills": minor
---

A crew member's `harness` now locks that role to its harness. `launch-teammate.sh` takes `--harness` and `HARNESS_<ROLE>` from `team.env`, records the teammate's harness as column 6 of `teammates.tsv`, and `retask.sh`, `close-teammate.sh`, `teammate-tail.sh` and `watch-teammates.sh` route by it (drivers read `TEAMMATE_HARNESS`). Drivers may add an `available` operation, called through `harness-available.sh`. `crew.py cast` checks each locked harness, exits 4 when one is unavailable, takes `--unlock <role>` (kept in `cast.json` as `unlocks`), and `--save` writes `HARNESS_<ROLE>` lines. `team-preflight.sh` runs each locked harness's own preflight and skips locked roles' models in the advisor probe.
