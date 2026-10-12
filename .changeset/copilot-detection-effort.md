---
"jasonbuffin-skills": minor
---

`commodore` detects a run started in Copilot CLI (`COPILOT_CLI=1`), as does agent-teammates' `detect-harness.sh`, and `team-init.sh` writes a Copilot `team.env`: `HARNESS=copilot`, `MODEL=claude-sonnet-5.5`, a `MODEL_<ROLE>` and an empty `EFFORT_<ROLE>` per role, and no `ADVISOR`, `PERMISSION_MODE` or `CLAUDE_CONFIG_DIR` line. A run with both `CLAUDECODE=1` and `COPILOT_CLI=1` now exits 7 instead of starting as Claude. The Copilot driver records the role's effort at launch and passes `--reasoning-effort <effort>` on launch and every resume only when it is set. Claude and Codex runs are unchanged.
