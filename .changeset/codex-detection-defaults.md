---
"jasonbuffin-skills": minor
---

`commodore` detects a run started in Codex (`CODEX_THREAD_ID` set) and `team-init.sh` writes a Codex `team.env`: `HARNESS=codex`, `MODEL=gpt-6.1-sol`, a `MODEL_<ROLE>` and an `EFFORT_<ROLE>` per role, and no `ADVISOR`, `PERMISSION_MODE` or `CLAUDE_CONFIG_DIR` line. A run with both `CLAUDECODE=1` and `CODEX_THREAD_ID` still exits 7. Launching Codex teammates and the Codex guidance come in later changes; until then a Codex run's driver operations exit 5. Claude runs are unchanged.
