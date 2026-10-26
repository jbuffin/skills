# One harness per run, behind a per-harness driver

A run uses one harness: the one it was started from. `team-init.sh` detects it and records it as `HARNESS` in `team.env`, and the coordinator and every teammate use that harness. Launch, message, status, tail and stop (plus the advisor probe, where the harness has an advisor) live in `drivers/<harness>/`, with the same arguments on every harness, and the shared scripts call the driver. Per-harness guidance for the coordinator lives in `references/harness-<name>.md`, not in the shared `SKILL.md` text.

The teammate contract depends on the harness. A harness that can message a live teammate keeps it waiting after its `.done` marker, so Claude Code runs keep live re-tasking and idle notices. A harness that can't has the teammate exit after its marker and resumes it with the next job.

## Considered options

- **Mixed runs (a Claude coordinator with Codex teammates, say)**: rejected for now. The coordinator's tools come from its own harness and the driver from the teammates' harness, which doubles the guidance and the combinations to test. It can come later as its own change.
- **One contract on every harness (always exit after the marker)**: rejected. It's simpler, but Claude Code runs would lose live messages and `notify_when_idle`.
- **Abstract model tiers that each driver maps to models**: rejected. `MODEL_<ROLE>` keeps holding real model names, with per-harness defaults, so the profile shows what actually ran.

## Consequences

A run started in Claude Code and resumed from another harness fails preflight. Features one harness lacks, like the advisor off Claude Code, are reported as not available on that harness rather than as warnings.

Amended 2026-10-26 ([#115](https://github.com/jbuffin/skills/issues/115)): inside an Admiral ship, writers are live crew boats; see ADR 0006.
