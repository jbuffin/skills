# Teammates on Claude Code

Read this when the run's `HARNESS` is `claude`, which is the default when `team.env` has no `HARNESS` line. Outside an Admiral ship this harness declares `LIVE_MESSAGING=1` and `SEND=tool` in `scripts/drivers/claude/driver.env`: a live teammate takes new work by message, and sending is a tool call, not a script. Inside one the admiral driver declares `SEND=script`: re-task with `retask.sh` ("Inside an Admiral ship"). The operations and exit codes every driver follows are in `scripts/drivers/CONTRACT.md`.

## What a teammate is

A teammate is a full Claude Code session started in the background with `claude --bg`. It runs under Claude Code's background daemon, so it keeps going when a terminal closes or the laptop sleeps, and the engineer can watch it from any terminal.

## Claude defaults and Claude-only settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `MODEL` | sonnet | the model for a launch with neither `--model` nor `--role` |
| `ADVISOR` | opus | the built-in advisor model every teammate launches with; `none` turns it off. It has to rank at or above the teammate's model, and a Fable model accepts only `fable`. A refused pairing starts without the advisor and no error |
| `PERMISSION_MODE` | auto | the teammates' permission mode |
| `VIEWER` | none | `cmux` or `tmux` opens a pane per teammate running `claude attach <id>`; cmux also needs `CMUX_WORKSPACE` and `CMUX_SURFACE` from `cmux identify`. Ignored inside an Admiral ship |

An in-process agent launched without a model runs on whatever model the coordinator uses.

## Send new work

To give a live teammate new work, send it with the SendMessage tool, `to: <name>`, because the session name is the address. Then run `<teammates>/retasked.sh <team-dir> <name>` so the watchdog stops counting the old marker.

Teammates have to run in the same permission class as the coordinator (`PERMISSION_MODE` in `team.env`). Otherwise the message sits waiting for the engineer's approval in that session.

For a single teammate, a SendMessage with `notify_when_idle: true` gives you a one-time notice the next time it goes idle, with no polling.

## Run the watchdog

Run `<teammates>/watch-teammates.sh <team-dir>` under the Monitor tool for as long as any teammate is live. Monitors expire after 30 minutes, so re-arm it whenever it reports expiry and someone is still live.

Every minute it reads `claude agents --json` (inside an Admiral ship, `admiral crew list --json`), the markers and each teammate's transcript mtime (inside an Admiral ship, the boat's `last_activity`).

## What the engineer sees

`claude agents` is the dashboard, and it works in any terminal (Space to peek, Enter to attach). `claude attach <id>` opens one teammate.

`claude logs <id>` prints raw terminal frames that cost thousands of tokens to read. Run `teammate-tail.sh` first, and read `claude logs <id>` only when you need to see an open prompt (a BLOCKED teammate).

## Inside an Admiral ship

With `ADMIRAL_SHIP` set (caller's environment or `team.env`), the admiral driver replaces `drivers/claude` for launch, send, status and stop. `SKILL_PREFIX`, `has-skill`, `list-skills` and `advisor-probe` still come from the Claude driver. The crew boats run Claude Code in tmux windows of the ship, not under `claude --bg`, so this reference's `claude agents`, `claude attach`, `claude logs`, `claude stop`, SendMessage and `notify_when_idle` lines don't apply. Admiral must be main at 992f678 or later: `launch` exits 5 and `preflight` prints FAIL on 0.3.0, which has no `--arg`.

- **Launch.** Model, advisor, permission mode and the `--read-only` edit denies reach `admiral crew launch` as `--arg` values; `--role` is passed as Admiral's `--role`. The session id is the crew name. The launch returns after the boat's first hook (`last_activity` set), waiting up to `LAUNCH_WAIT` seconds (default 90, polled every `LAUNCH_POLL`, default 2; both from `team.env` or the environment). A boat that exits first is closed and exits 1. Exit 5 means: the name is in use; an invalid name or role (lowercase letters and digits with `-` inside, not first); Admiral older than main at 992f678, with no `--arg`; Admiral rejected the call; there is no ship; no hook within `LAUNCH_WAIT`; or `HARNESS=admiral` (admiral is a host driver, so set `HARNESS` to the harness and `ADMIRAL_SHIP` to the ship). Exit 1 is any other refusal, with Admiral's message.
- **Send.** `retask.sh` types a pointer to the message file into the boat with `admiral crew send`, which ends with Enter. Board a BLOCKED boat with `admiral attach <ship> <crew>` before re-tasking it: the Enter may answer a prompt it is waiting on. An anchored boat can't take the message (exit 1): launch a new teammate.
- **Watch.** `watch-teammates.sh` reads `admiral crew list --json`: underway is working, needs you is blocked, anchored is stopped and a boat missing from the list is missing. A boat that needs you waits on a prompt, so read it with `admiral attach <ship> <crew>`.
- **Read output.** `teammate-tail.sh` reads the transcript path Admiral records at the boat's first hook. Before that it exits 3 and says no transcript is recorded.
- **Close.** `close-teammate.sh` runs `admiral crew close`. Never close a boat this run didn't launch.
- **Autopilot** (`ADMIRAL_AUTOPILOT=1`). The launch leaves out `--permission-mode` so the boat inherits the dock's, because Admiral refuses any looser mode and the default `auto` would block every launch. Admiral refuses `--disallowedTools` when the dock already sets it, so every `--read-only` launch then exits 1 with Admiral's message. Admiral also refuses `--ship` without an `ADMIRAL_SHIP` in the caller's environment, so the driver leaves it out and the ship in `team.env` alone doesn't work under autopilot.
- **Advisor and trust.** `ADVISOR` pairing applies. Trust the repository once per dock: run the dock's harness in the repository, settle the folder-trust prompt, then launch. A boat at that prompt never fires a hook, so the launch closes it and exits 5 after `LAUNCH_WAIT`.
- **Where the deferred operations run.** `has-skill`, `list-skills`, `advisor-probe` and `tail`'s rendering run in the coordinator's environment. That matches the crew boats' only when both use the same dock.

## Workspace trust

The working directory has to be trusted. Worktrees inside a repository the engineer has opened in Claude Code inherit its trust, and anything else fails to launch with "Workspace not trusted".

## Closing

Close teammates with `close-teammate.sh`, which runs `claude stop`. Never run `claude rm`: it also deletes any worktree it decides is safe to delete.

## Fallback when background sessions can't start

Outside an Admiral ship, if `launch-teammate.sh` exits 2 (`NO_BG`, meaning background sessions aren't available or the folder isn't trusted), run the teammate as an in-process subagent. Give it:

- an explicit `model=`, set to the model the `NO_BG` message names;
- the same prompt file, the same contract and its own working directory.

Verify it with `verify-report.sh … --workdir <dir>`, since it isn't in the registry. The watchdog still reports its `DONE` marker, but none of the session events.

Tell the engineer what they lose. There's no dashboard and no attaching, and the teammate ends when the coordinator's session does.

An in-process subagent inherits the coordinator's configured advisor (and applies the pairing check against its own model); it gets no `--advisor` from `ADVISOR`.
