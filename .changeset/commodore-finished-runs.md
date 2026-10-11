---
"jasonbuffin-skills": patch
---

`commodore` now writes a `result:` line into `state.md` when a run ends, and treats a run with that line as finished: it doesn't resume it, and a new run never reuses its directory. A new request checks only a run directory you name.
