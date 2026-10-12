# Teammates on Claude Code

Read this when the run's `HARNESS` is `claude`, which is the default when `team.env` has no `HARNESS` line. This harness declares `LIVE_MESSAGING=1` and `SEND=tool` in `scripts/drivers/claude/driver.env`: a live teammate takes new work by message, and sending is a tool call, not a script. The operations and exit codes every driver follows are in `scripts/drivers/CONTRACT.md`.

## What a teammate is

A teammate is a full Claude Code session started in the background with `claude --bg`. It runs under Claude Code's background daemon, so it keeps going when a terminal closes or the laptop sleeps, and the engineer can watch it from any terminal.

## Claude defaults and Claude-only settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `MODEL` | sonnet | the model for a launch with neither `--model` nor `--role` |
| `ADVISOR` | opus | the built-in advisor model every teammate launches with; `none` turns it off. It has to rank at or above the teammate's model, and a Fable model accepts only `fable`. A refused pairing starts without the advisor and no error |
| `PERMISSION_MODE` | auto | the teammates' permission mode |
| `VIEWER` | none | `cmux` or `tmux` opens a pane per teammate running `claude attach <id>`; cmux also needs `CMUX_WORKSPACE` and `CMUX_SURFACE` from `cmux identify` |

An in-process agent launched without a model runs on whatever model the coordinator uses.

## Send new work

To give a live teammate new work, send it with the SendMessage tool, `to: <name>`, because the session name is the address. Then run `<teammates>/retasked.sh <team-dir> <name>` so the watchdog stops counting the old marker.

Teammates have to run in the same permission class as the coordinator (`PERMISSION_MODE` in `team.env`). Otherwise the message sits waiting for the engineer's approval in that session.

For a single teammate, a SendMessage with `notify_when_idle: true` gives you a one-time notice the next time it goes idle, with no polling.

## Run the watchdog

Run `<teammates>/watch-teammates.sh <team-dir>` under the Monitor tool for as long as any teammate is live. Monitors expire after 30 minutes, so re-arm it whenever it reports expiry and someone is still live.

Every minute it reads `claude agents --json`, the markers and each teammate's transcript mtime.

## What the engineer sees

`claude agents` is the dashboard, and it works in any terminal (Space to peek, Enter to attach). `claude attach <id>` opens one teammate.

`claude logs <id>` prints raw terminal frames that cost thousands of tokens to read. Run `teammate-tail.sh` first, and read `claude logs <id>` only when you need to see an open prompt (a BLOCKED teammate).

## Workspace trust

The working directory has to be trusted. Worktrees inside a repository the engineer has opened in Claude Code inherit its trust, and anything else fails to launch with "Workspace not trusted".

## Closing

Close teammates with `close-teammate.sh`, which runs `claude stop`. Never run `claude rm`: it also deletes any worktree it decides is safe to delete.

## Fallback when background sessions can't start

If `launch-teammate.sh` exits 2 (`NO_BG`, meaning background sessions aren't available or the folder isn't trusted), run the teammate as an in-process subagent. Give it:

- an explicit `model=`, set to the model the `NO_BG` message names;
- the same prompt file, the same contract and its own working directory.

Verify it with `verify-report.sh … --workdir <dir>`, since it isn't in the registry. The watchdog still reports its `DONE` marker, but none of the session events.

Tell the engineer what they lose. There's no dashboard and no attaching, and the teammate ends when the coordinator's session does.

An in-process subagent inherits the coordinator's configured advisor (and applies the pairing check against its own model); it gets no `--advisor` from `ADVISOR`.
