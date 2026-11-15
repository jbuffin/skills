# Launch rules

Paths are relative to the crew skill's directory.

## Run directory and worktrees

- On the first launch only, run `../commodore/scripts/team-init.sh crew-<short-slug> <top>`. It exits 6 when `agent-teammates`, `run-preflight` or `target-evaluation` isn't next to commodore, and 7 when no harness is detected. Use only its `team.env`; leave `MODE` empty.
- Give each teammate a worktree: `../commodore/scripts/unit-worktree.sh <run> new <unit> <branch> <base>`. Always pass `<base>`; `BASE_BRANCH` is empty. For an existing PR: `unit-worktree.sh <run> pr <unit> <pr-number>`.
- A review member launches with `--read-only`.

## `--member` or `--role`

Use `--member` when `ship: yes` and either the member runs on claude, or it runs on codex or copilot without `--read-only` and with `autopilot: no`:

```text
../agent-teammates/scripts/launch-teammate.sh --member <name> --role <role, or based-on for a custom role> [--harness <lock>] [--read-only] <run> <name> <unit> <prompt>
```

Admiral puts the member's instructions and notes at the front of the prompt but doesn't run its role skills, so the prompt names each one ("Run `/<skill>`."). Admiral reads the repo layer from the teammate's worktree, so a member that exists only uncommitted in the engineer's checkout is "not found"; use `--role` for it.

Otherwise use `--role`: outside a ship, and inside a ship for codex or copilot under autopilot or read-only.

- Built-in role: `--role <role>`.
- Custom role: `--role <based-on> --harness <lock, or the run's harness>`.
- Add `--model <model>` when the member has one.
- The prompt carries the member's instructions, the output of `python3 ../commodore/scripts/crew.py notes --run <run> --member <name>`, and its role skills.
