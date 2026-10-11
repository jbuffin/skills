---
"jasonbuffin-skills": major
---

Rename the `agent-team-build` skill to `commodore`. `/agent-team-build` (`/jasonbuffin:agent-team-build`) no longer exists, so call `/jasonbuffin:commodore`. The skill's behaviour, scripts and references are unchanged. A run started before the rename keeps the old resolved paths in its `team.env` (`SKILL=…/agent-team-build`, `TEAM_SCRIPTS=…`), because plugin installs are versioned.
