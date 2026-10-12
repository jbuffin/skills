---
"jasonbuffin-skills": patch
---

`agent-teammates`' watchdog table now sends `DONE` (unverified) and `BLOCKED` to the re-tasking paragraph instead of saying "message it", and on `STALL` with `LIVE_MESSAGING=0` tells the coordinator to close the teammate with `close-teammate.sh` and relaunch it fresh instead of nudging. `commodore` states the re-task job-file rule once (`<run>/prompts/<name>.job-<n>.md`, written with the file-writing tool) for every mission, and the implementer role says "end your turn" instead of "wait for". Claude behaviour is unchanged.
