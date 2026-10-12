---
"jasonbuffin-skills": minor
---

Codex teammates can be launched, re-tasked, watched, tailed and closed. `agent-teammates` has a Codex driver (`scripts/drivers/codex`) with `launch`, `send`, `status`, `tail`, `stop` and `preflight`. Each turn runs as `codex exec` or `codex exec resume` in its own background process group; read-only roles get a read-only sandbox and the driver writes their report marker after a completed turn, writers get workspace-write with network access and the run's `reports/` directory. `launch-teammate.sh --role <role>` now hands `EFFORT_<ROLE>` to the driver's `launch` as `TEAMMATE_EFFORT` (empty without `--role`); the Claude driver ignores it and its launch is unchanged. The Codex preflight checks the `~/.codex/rules` prefix rules the roles need and fails with the exact line to add.
