---
"jasonbuffin-skills": minor
---

Commodore's `state-set.sh` sets several `state.md` fields in one call. `mode --set <key>=<value> …` takes several mode keys, and `units`, `trace` and `findings` take `--set <row> <column>=<value> … [--set <row> …]` for several columns across several rows of one table. A call edits one section and gives the same `state.md` as the same fields set one call at a time, in order; it is refused whole, with one stderr line that names the bad field, when any field is bad. The coordinator now updates `state.md` in one batched call per section at each milestone (unit start, review round done, unit ships, unit closes) instead of one call per field, and `mission-build.md` shows the calls. `--add` and `--drop` stay one row per call, and the existing forms behave as before. The usage text for exit 5 now prints; it never did, because `$0` inside the usage function was not the script's path.
