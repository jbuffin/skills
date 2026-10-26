---
"jasonbuffin-skills": minor
---

Inside an Admiral ship, agent-teammates now runs Codex and Copilot writers as crew boats too. With `HARNESS=codex` or `copilot` and `ADMIRAL_SHIP` set, `launch-teammate.sh` starts a teammate without `--read-only` through `admiral crew launch --harness <harness>`, and `retask.sh` re-tasks it with `admiral crew send`. A `--read-only` teammate stays headless, and under `ADMIRAL_AUTOPILOT=1` every Codex and Copilot teammate does. `teammate-tail.sh` prints a Codex or Copilot boat's transcript path and last lines raw. A new boat stops at an unsettled folder-trust or hook-review prompt: settle them once per dock, and run `drivers/admiral/preflight` to check. A malformed `LAUNCH_WAIT` or `LAUNCH_POLL` now exits 5 naming the variable. ADR 0006 records the change.
