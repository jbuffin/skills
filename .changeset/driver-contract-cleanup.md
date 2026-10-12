---
"jasonbuffin-skills": patch
---

The driver contract moves to `agent-teammates/scripts/drivers/CONTRACT.md`, and each `driver.env` keeps only its own values. `tail` on Claude and Copilot prints the last N tool lines and then the latest message, as the contract says, and Copilot's `tail` skips a malformed line. Codex `launch` and `send` stop with "codex is not on PATH" when the CLI is missing. Copilot `launch` exits 5 for a malformed `TEAMMATE_EFFORT` (anything outside letters, digits, `.`, `_` and `-`, or starting with `-`) and passes any other value to the CLI, which validates it. `team-init.sh` writes `REPO` without the old `WORKTREE` alias (old `team.env` files still work), and Codex `.state` files no longer record `PERM`.
