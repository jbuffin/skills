---
"jasonbuffin-skills": minor
---

`agent-teammates` and `commodore` are now harness-aware, with Claude Code the supported harness today (Codex and Copilot CLI are planned, #9). `team-init.sh` detects the harness from where the run starts and writes `HARNESS` to `team.env`, and the Claude calls live in a driver under `agent-teammates/scripts/drivers/claude/`. The skill text is harness-neutral and reads `references/harness-<HARNESS>.md` for anything Claude-specific: sending work with SendMessage, running the watchdog under Monitor, the default model per role, and the advisor. The teammate contract has `LIVE_MESSAGING=1` and `LIVE_MESSAGING=0` variants. Claude runs behave as before.
