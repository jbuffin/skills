---
"jasonbuffin-skills": patch
---

Copilot writer teammates can run the skill scripts again. Copilot's path guard refused `evidence.sh` (and `secret-run.sh` and `push-branch.sh`) because they live outside the writer's added directories, so `verify-report.sh` always said `unverified` for a Copilot writer. Writer launches and resumes now also get `--add-dir` for the agent-teammates scripts directory and for `PREFLIGHT_SCRIPTS` and `TEAM_SCRIPTS` from `team.env`. Read-only runs keep their flags. `drivers/copilot/preflight` runs a second, writer turn that calls `evidence.sh` and fails, naming the path guard, when it can't. The Copilot reference lists the directories (checked on Copilot CLI 1.0.96) and adds a security caveat: a writer can now edit those scripts.
