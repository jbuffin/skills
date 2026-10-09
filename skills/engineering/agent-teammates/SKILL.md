---
name: agent-teammates
description: Run Claude teammates as Claude Code background sessions (claude --bg). Launch, re-task, watch with a watchdog, verify their proof, and close them. Use when work is handed to parallel Claude sessions that run unattended, including from an orchestrating skill.
---

# Agent teammates

A teammate is a full Claude Code session started in the background with `claude --bg`. It has its own name, model, permission mode and working directory, and it gets one prompt file. It runs under Claude Code's background daemon, so it keeps going when a terminal closes or the laptop sleeps, and the engineer can watch it from any terminal.

Teammates run unattended, so almost everything here guards against one failure. A teammate stops and nobody notices. It ends its turn "to wait" and nothing wakes it up. Or it sits on a prompt. Or it stalls mid-turn, still "working" but doing nothing. Or it drifts off and never reports. The contract and the watchdog below cover all four.

## The team directory

This can be any directory you choose, or one an orchestrating skill gives you. It holds `prompts/<name>.md` (one per teammate), `prompts/<name>.proof` (its proof commands, when it has any), `reports/` (their output), and `teammates.tsv`, a registry the scripts keep with each teammate's name, session id, tasked-at time, viewer and working directory. It can also hold two optional files.

- `team.env` sets `MODEL` (default sonnet), `PERMISSION_MODE` (default auto), `STALL_MIN` (default 10, the quiet minutes before STALL), `VIEWER` (`none` by default, or `cmux` or `tmux`), and `REPO`, the engineer's checkout, inside which no teammate starts. For cmux viewers it also sets `CMUX_WORKSPACE` and `CMUX_SURFACE`, which you get from `cmux identify`.
- `worktrees.tsv` lists `unit branch path`, so a unit name can stand in for a directory.

`<teammates>` below is this skill's `scripts/` directory, as a resolved absolute path.

Make every call **bare**: one command, run directly by its literal absolute path, with no `;`, `&&`, pipes, `source`, `zsh <script>` or shell variables. Allow rules match the literal command, and a worktree guard refuses compound lines, so `$TEAM/helper.sh` misses a rule written for `/abs/path/helper.sh`. The contract's wait loop is the one exception, and the probe checks that it runs unprompted. Write every prompt file with literal absolute paths for the same reason, because teammates copy paths from it.

## The teammate contract

Put this in every prompt file, or in a shared brief that every prompt points to.

- Wait inside a Bash command whenever you're waiting on a build, a deploy, a token expiry or a device: `until <condition>; do sleep 30; done` with a long timeout, then carry on. Ending your turn to wait means nothing wakes you.
- Write the report, then the marker. When you're finished, write `<team-dir>/reports/<name>.md`, then create `<team-dir>/reports/<name>.done`, in that order, and wait. Every role writes both, read-only ones included.
- Questions go in the report under `## Questions for the engineer`, each with options and a recommendation. Keep going on whatever doesn't depend on the answer.
- New instructions arrive as messages from the coordinator. Do them, overwrite the report, and touch the marker again.
- Clean up only what you started, whether that's processes or files outside your directory.
- Make every call bare: one command, by its literal absolute path, with no `;`, `&&`, pipes, `source` or shell variables, so the allow rules match it. The wait loop above is the one exception.
- No proof, no done. If `<team-dir>/prompts/<name>.proof` exists, run each proof in it as `<teammates>/evidence.sh <team-dir> <name> <label>`, after your last commit and again in every round. It runs the declared command and logs its output, head SHA and exit code, and the coordinator checks those logs against your HEAD. Your own summary of a run isn't evidence.
- Keep the report short. Say what you did, the files you touched, one `commit: <sha>` line if you committed, each proof label with its result, what you didn't check and why, where you departed from the brief and why, and your start and end times (`date -u`).

## Launch, re-task, close

```bash
<teammates>/launch-teammate.sh [--read-only] <team-dir> <name> <workdir|unit> [prompt-file]   # claude --bg
<teammates>/retasked.sh        <team-dir> <name>                                              # after sending new work
<teammates>/close-teammate.sh  <team-dir> <name>...                                           # claude stop
```

Names use letters, digits, `.`, `_` and `-`; the scripts refuse anything else.

Give each teammate only what its job needs. Launch a teammate that only reads the source (a reviewer, a brief checker, a probe that only reads) with `--read-only`. That denies the file-editing tools inside its working directory and still lets it write its report in the team directory. Bash isn't covered, so the brief still says read-only. The flag catches slips. It isn't a sandbox.

Write a teammate's `prompts/<name>.proof` before launching or re-tasking it, one `<label> <command>` per line. A proof file that changes after the tasking fails verification, so a teammate can't rewrite its own proof. An exact allow rule per proof (`Bash(<teammates>/evidence.sh <team-dir> <name> <label>)`) approves it without approving anything else. A prefix rule on `evidence.sh` would approve any command, because the `--` form runs whatever follows.

To give a live teammate new work, send it with the SendMessage tool, `to: <name>`, because the session name is the address. Then run `retasked.sh` so the watchdog stops counting the old marker. Teammates have to run in the same permission class as the coordinator (`PERMISSION_MODE` in `team.env`). Otherwise the message sits waiting for the engineer's approval in that session.

Set the model explicitly. `--model` comes from `MODEL` and defaults to Sonnet. An in-process agent launched without a model runs on whatever model the coordinator uses.

Give each teammate its own working directory, which is usually a git worktree. The folder has to be trusted. Worktrees inside a repository the engineer has opened in Claude Code inherit its trust, and anything else fails to launch with "Workspace not trusted".

Re-task instead of relaunching when the teammate's context is worth keeping, like an implementer fixing review findings on its own work. Relaunch fresh when independence matters (a reviewer) or the context has gone bad.

Close teammates with `stop`, never `claude rm`, which also deletes any worktree it decides is safe to delete. A closed teammate stays closed. `retasked.sh` refuses it, so launch a new one.

## What the engineer sees

`claude agents` is the dashboard, and it works in any terminal (Space to peek, Enter to attach). `claude attach <id>` opens one teammate.

To read what a teammate is doing, run `<teammates>/teammate-tail.sh <team-dir> <name> [n]`. It prints its last tool calls and latest message as plain text from the session transcript, plus how long ago the transcript was last written. Use it in place of `claude logs`, whose output is raw terminal frames that cost thousands of tokens to read.

With `VIEWER=cmux` or `VIEWER=tmux`, launching also opens a pane running `claude attach <id>`. That pane is a window onto the session and nothing more. Closing it never stops the teammate, and the run doesn't depend on it.

## Watch

Run `<teammates>/watch-teammates.sh <team-dir>` under the Monitor tool for as long as any teammate is live. Monitors expire after 30 minutes, so re-arm it whenever it reports expiry and someone is still live. Every minute it reads `claude agents --json`, the markers and each teammate's transcript mtime, and it emits these events.

| Event | Meaning | Do |
| --- | --- | --- |
| `DONE <name>` | the marker appeared or was touched | run `<teammates>/verify-report.sh <team-dir> <name>`, then read the report. `verdict: unverified` means not done: send it the FAIL lines as its next instruction |
| `BLOCKED <name> <id>` | its turn ended (or it's waiting on a prompt) twice in a row with no new marker | run `teammate-tail.sh`, then `claude logs <id>` only if you need to see an open prompt. A permission prompt you can't approve under the run's ground rules, or a question for the engineer, goes up. Pick only options that keep data in and permissions as they are. Otherwise, message it one concrete next instruction |
| `STALL <name> <id> <min>` | still "working", but its transcript hasn't changed for `<min>` minutes, usually a long deliberation mid-turn | run `teammate-tail.sh` and message it one concrete next command (the exact command to run, not "what's your status?"). If it stalls again on the same step, close it and relaunch with that step spelled out |
| `STALE <name> <id> <min>` | 45, 90, … minutes since it was tasked, still working, no marker | run `teammate-tail.sh`. If it's looping or off task, or you've already nudged it twice, close it and relaunch fresh with a sharper prompt |
| `GONE <name> <id> <state>` | its session stopped, failed or vanished without being closed | check the report and relaunch if needed |

When a report looks untrustworthy, the brief or its proof was weak. Sharpen it and relaunch once, or take the question up. Extra reviewers and repeated relaunches only hide the doubt.

For a single teammate, a SendMessage with `notify_when_idle: true` gives you a one-time notice the next time it goes idle, with no polling.

## Fallback

If `launch-teammate.sh` exits 2 (`NO_BG`, meaning background sessions aren't available or the folder isn't trusted), run the teammate as an in-process subagent. Give it an explicit `model: sonnet`, the same prompt file, the same contract and its own working directory, and verify it with `verify-report.sh … --workdir <dir>`, since it isn't in the registry. The watchdog still reports its `DONE` marker, but none of the session events. Tell the engineer what they lose. There's no dashboard and no attaching, and the teammate ends when the coordinator's session does.

## Parallelism

Two teammates working at once is about the useful limit for one coordinator. Past that, your context goes on reading reports. Give each exclusive resource (a device, a worktree, a test account) one long-lived owner that takes requests by message, rather than sharing it between teammates.
