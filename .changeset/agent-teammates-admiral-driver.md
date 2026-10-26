---
"jasonbuffin-skills": minor
---

agent-teammates has an admiral driver. In an Admiral ship (`ADMIRAL_SHIP` set in the environment or `team.env`) with `HARNESS=claude`, `launch-teammate.sh`, `retask.sh`, `watch-teammates.sh`, `close-teammate.sh` and `teammate-tail.sh` run teammates as Admiral crew boats through `admiral crew launch|send|list|close`, and `VIEWER` is ignored. It needs Admiral main at 992f678 or later; on 0.3.0 a launch exits 5. `launch-teammate.sh --role` now passes the role to the driver as `TEAMMATE_ROLE`. Outside Admiral every script behaves as before.
