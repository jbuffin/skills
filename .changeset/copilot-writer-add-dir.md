---
"jasonbuffin-skills": patch
---

Copilot writer teammates can now run the skill scripts. Under `--no-ask-user` Copilot's path guard refused `evidence.sh`, so `verify-report.sh` always said `unverified` for a Copilot writer. A writer launch and every resume now also get `--add-dir` for the agent-teammates scripts directory and for `PREFLIGHT_SCRIPTS` and `TEAM_SCRIPTS` from `team.env` (each only when it is an absolute path to an existing directory). Read-only runs keep their flags. `drivers/copilot/preflight` adds a headless writer turn that runs `evidence.sh` against a throwaway team dir and fails, naming the path guard, when it can't. The Copilot reference lists the new directories (checked on Copilot CLI 1.0.96) and the security caveat that a writer can now write those scripts.
