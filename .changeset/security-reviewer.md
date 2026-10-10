---
"jasonbuffin-skills": minor
---

`agent-team-build` adds a security reviewer that runs in every review round alongside the reviewer, with merged, source-labelled findings, blocking and non-blocking severities, new profile security fields, and a `MODEL_SECURITY_REVIEWER` default in `team.env`. Both `agent-team-build` and `agent-teammates` now limit concurrency to two teammates that write, plus the steward; read-only teammates don't count.
