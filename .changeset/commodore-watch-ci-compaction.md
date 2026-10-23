---
"jasonbuffin-skills": patch
---

Commodore keeps waiting on CI with `watch-ci.sh` after a compaction. Phase 1 writes the run's exact ship and CI commands on a new `ship:` line in `state.md`, and after a compaction the coordinator re-reads its mission's current phase as well as `state.md`. In a 13-unit run, a compaction summary dropped `watch-ci.sh`, and the coordinator hand-wrote about 33 CI-wait calls for the remaining seven units, one of which marked a red run green. On a red run, `watch-ci.sh` now saves `gh run view --log-failed` to the run directory and prints the path and up to 20 failing lines, so the coordinator doesn't fetch the log itself.
