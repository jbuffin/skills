---
"jasonbuffin-skills": minor
---

Give every teammate Claude Code's built-in advisor. In `agent-teammates`, `launch-teammate.sh` passes `--advisor $ADVISOR` (default `opus`, `none` turns it off) on every launch. The teammate contract asks for an `## Advisor consults` section in every report, and the common brief says when to consult. `team-preflight.sh` probes the advisor once per distinct teammate model with the new `advisor-probe.sh` and warns `ADVISOR OFF` where it didn't come on; `agent-team-build` tells the engineer before launching and reads the consults.
