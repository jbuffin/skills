---
name: agent-teammates
description: Run teammates as background agent sessions on a harness (Claude Code is the supported harness today). Launch, re-task, watch with a watchdog, verify their proof, and close them. Use when work is handed to parallel agent sessions that run unattended, including from an orchestrating skill.
---

# Agent teammates

A teammate is a full agent session started in the background on the run's **harness**, the agent CLI the run starts in. It has its own name, model, permission mode and working directory, and it gets one prompt file. It keeps going when a terminal closes or the laptop sleeps, and the engineer can watch it from any terminal.

The scripts in this skill are harness-neutral. Each calls the harness's **driver** (`scripts/drivers/<HARNESS>/`) for launch, status, tail and stop. Everything that depends on the harness is in a reference file. Read `references/harness-<HARNESS>.md`, with `HARNESS` from the run's `team.env`. With no `team.env`, or no `HARNESS` line in it, the harness is `claude`: read [`references/harness-claude.md`](references/harness-claude.md). It covers how a teammate starts, how you send it new work, how you watch it, the model and advisor settings, and the fallback when sessions can't start.

Teammates run unattended, so almost everything here guards against one failure. A teammate stops and nobody notices. It ends its turn "to wait" and nothing wakes it up. Or it sits on a prompt. Or it stalls mid-turn, still "working" but doing nothing. Or it drifts off and never reports. The contract and the watchdog below cover all four.

## The team directory

This can be any directory you choose, or one an orchestrating skill gives you. It holds `prompts/<name>.md` (one per teammate), `prompts/<name>.proof` (its proof commands, when it has any), `reports/` (their output), and `teammates.tsv`, a registry the scripts keep with each teammate's name, session id, tasked-at time, viewer and working directory. It can also hold two optional files.

- `team.env` holds the settings below. `HARNESS` and the script directories are written by commodore's `team-init.sh`.

  | Setting | Default | Meaning |
  | --- | --- | --- |
  | `HARNESS` | claude | the harness; selects `scripts/drivers/<HARNESS>` and `references/harness-<HARNESS>.md` |
  | `MODEL` | the harness reference | the model for a launch with neither `--model` nor `--role` |
  | `MODEL_<ROLE>` | none | the model for `--role <role>`; see "Set the model explicitly" |
  | `REQUIRE_ROLE` | unset | `1` makes every launch pass `--role` or `--model` |
  | `ADVISOR` | the harness reference | the advisor model every teammate launches with, where the harness has an advisor; `none` turns it off. The reference gives the pairing rules |
  | `PERMISSION_MODE` | the harness reference | the teammates' permission mode |
  | `STALL_MIN` | 10 | the quiet minutes before STALL |
  | `VIEWER` | none | opens a viewer pane per teammate, on a harness that supports it; the reference lists the values |
  | `REPO` | unset | the engineer's checkout, inside which no teammate starts |

- `worktrees.tsv` lists `unit branch path`, so a unit name can stand in for a directory.

`<teammates>` below is this skill's `scripts/` directory, as a resolved absolute path.

Make every call **bare**: one command, run directly by its literal absolute path, with no `;`, `&&`, pipes, `source`, `zsh <script>` or shell variables. Allow rules match the literal command, and a worktree guard refuses compound lines, so `$TEAM/helper.sh` misses a rule written for `/abs/path/helper.sh`. The contract's wait loop is the one exception, and the probe checks that it runs unprompted. Write every prompt file with literal absolute paths for the same reason, because teammates copy paths from it.

## The teammate contract

Put this in every prompt file, or in a shared brief that every prompt points to. The harness's `driver.env` sets `LIVE_MESSAGING`. When you paste the contract, keep only the variant lines for the run's value.

- Wait inside a Bash command whenever you're waiting on a build, a deploy, a token expiry or a device: `until <condition>; do sleep 30; done` with a long timeout, then carry on. Ending your turn to wait means nothing wakes you.
- Write the report, then the marker. When you're finished, write `<team-dir>/reports/<name>.md`, then create `<team-dir>/reports/<name>.done`, in that order. Every role writes both, read-only ones included. Then:
  - `LIVE_MESSAGING=1`: wait for messages.
  - `LIVE_MESSAGING=0`: exit. The coordinator resumes your session for the next job.
- Questions go in the report under `## Questions for the engineer`, each with options and a recommendation. Keep going on whatever doesn't depend on the answer.
- If your harness gives you an advisor, ask it technical questions: how to do something, which approach, why something fails. It's a stronger model paired with your session, and you decide when to call it.
- Scope, product behaviour, departures from the source of truth and ground-rule questions go under `## Questions for the engineer`, and so does a problem two advisor consults haven't moved forward: stop consulting and ask.
- Every report has an `## Advisor consults` section with one line per advisor call: the question in brief, the advice in brief, and whether you followed it and why. Write `none` if you made no calls or have no advisor.
- New instructions:
  - `LIVE_MESSAGING=1`: they arrive as messages from the coordinator. Do them, overwrite the report, and touch the marker again.
  - `LIVE_MESSAGING=0`: they arrive when the coordinator resumes your session with the next job. Do it, overwrite the report, touch the marker again, and exit.
- Clean up only what you started, whether that's processes or files outside your directory.
- Make every call bare: one command, by its literal absolute path, with no `;`, `&&`, pipes, `source` or shell variables, so the allow rules match it. The wait loop above is the one exception.
- No proof, no done. If `<team-dir>/prompts/<name>.proof` exists, run each proof in it as `<teammates>/evidence.sh <team-dir> <name> <label>`, after your last commit and again in every round. It runs the declared command and logs its output, head SHA and exit code, and the coordinator checks those logs against your HEAD. Your own summary of a run isn't evidence.
- Keep the report short. Say what you did, the files you touched, one `commit: <sha>` line if you committed, each proof label with its result, what you didn't check and why, where you departed from the brief and why, and your start and end times (`date -u`).

## Launch, re-task, close

```bash
<teammates>/launch-teammate.sh [--read-only] [--model <model>] [--role <role>] <team-dir> <name> <workdir|unit> [prompt-file]
<teammates>/retasked.sh        <team-dir> <name>                                              # after sending new work
<teammates>/close-teammate.sh  <team-dir> <name>...
```

Names use letters, digits, `.`, `_` and `-`; the scripts refuse anything else.

Give each teammate only what its job needs. Launch a teammate that only reads the source (a reviewer, a brief checker, a probe that only reads) with `--read-only`. That denies the file-editing tools inside its working directory and still lets it write its report in the team directory. Bash isn't covered, so the brief still says read-only. The flag catches slips. It isn't a sandbox.

Write a teammate's `prompts/<name>.proof` before launching or re-tasking it, one `<label> <command>` per line. A proof file that changes after the tasking fails verification, so a teammate can't rewrite its own proof. An exact allow rule per proof (`Bash(<teammates>/evidence.sh <team-dir> <name> <label>)`) approves it without approving anything else. A prefix rule on `evidence.sh` would approve any command, because the `--` form runs whatever follows.

To give a live teammate new work (`LIVE_MESSAGING=1`), send it a message the way the harness reference says, addressed by the teammate's name. Then run `retasked.sh` so the watchdog stops counting the old marker. With `LIVE_MESSAGING=0`, resume the teammate's session with the next job instead, then run `retasked.sh`. The reference also covers the permission class a teammate needs so your message isn't held for approval.

Set the model explicitly. The launcher picks it in this order: `--model <model>`; else, with `--role <role>`, `MODEL_<ROLE>` from `team.env` (the role uppercased, `-` and `.` as `_`, so `brief-checker` reads `MODEL_BRIEF_CHECKER`); else `MODEL`, whose default the harness reference gives. If `MODEL_<ROLE>` is unset or empty, the launch exits 5 and names the variable, and it never falls back to `MODEL`. With `REQUIRE_ROLE=1`, a launch with neither `--role` nor `--model` exits 5, so a forgotten flag fails loudly. Flags go in any order before the positional arguments. The launcher passes the model name through unchecked.

Give each teammate its own working directory, which is usually a git worktree. The reference says which folders are trusted.

Re-task instead of relaunching when the teammate's context is worth keeping, like an implementer fixing review findings on its own work. Relaunch fresh when independence matters (a reviewer) or the context has gone bad.

Close teammates with `close-teammate.sh`. Close only with `close-teammate.sh`; some harness commands also delete worktrees. The reference lists what never to run in its place. A closed teammate stays closed. `retasked.sh` refuses it, so launch a new one.

## What the engineer sees

The harness reference names the dashboard and the command that opens one teammate.

To read what a teammate is doing, run `<teammates>/teammate-tail.sh <team-dir> <name> [n]`. It prints its last tool calls and latest message as plain text from the session transcript, plus how long ago the transcript was last written. Use it before the harness's raw log, which costs thousands of tokens to read.

With `VIEWER` set, launching also opens a pane attached to the session. That pane is a window onto the session and nothing more. Closing it never stops the teammate, and the run doesn't depend on it.

## Watch

Run `<teammates>/watch-teammates.sh <team-dir>` for as long as any teammate is live, the way the harness reference says, so its events reach you. Re-arm it whenever it ends or expires and someone is still live. Every minute it reads the harness's session status, the markers and each teammate's session activity time, and it emits these events.

| Event | Meaning | Do |
| --- | --- | --- |
| `DONE <name>` | the marker appeared or was touched | run `<teammates>/verify-report.sh <team-dir> <name>`, then read the report. `verdict: unverified` means not done: send it the FAIL lines as its next instruction |
| `BLOCKED <name> <id>` | its turn ended (or it's waiting on a prompt) twice in a row with no new marker | run `teammate-tail.sh`, then read the harness's raw log (see the reference) only if you need to see an open prompt. A permission prompt you can't approve under the run's ground rules, or a question for the engineer, goes up. Pick only options that keep data in and permissions as they are. Otherwise, message it one concrete next instruction |
| `STALL <name> <id> <min>` | still "working", but its transcript hasn't changed for `<min>` minutes, usually a long deliberation mid-turn | run `teammate-tail.sh` and message it one concrete next command (the exact command to run, not "what's your status?"). If it stalls again on the same step, close it and relaunch with that step spelled out |
| `STALE <name> <id> <min>` | 45, 90, … minutes since it was tasked, still working, no marker | run `teammate-tail.sh`. If it's looping or off task, or you've already nudged it twice, close it and relaunch fresh with a sharper prompt |
| `GONE <name> <id> <state>` | its session stopped, failed or vanished without being closed | check the report and relaunch if needed |

When a report looks untrustworthy, the brief or its proof was weak. Sharpen it and relaunch once, or take the question up. Extra reviewers and repeated relaunches only hide the doubt.

## Fallback

If `launch-teammate.sh` exits 2 (`NO_BG`: the harness can't run a background session here), follow the harness reference's fallback. Tell the engineer what they lose.

## Parallelism

Keep at most two teammates that write (edit files or commit) working at once, plus one long-lived owner of a shared target such as a device or a stage environment. Read-only teammates do not count toward the limit. The limit protects your context from too many reports and keeps writers from contending, and read-only reviewers produce the same reports whether they run in parallel or one after another. Give each exclusive resource (a device, a worktree, a test account) one long-lived owner that takes requests by message, rather than sharing it between teammates.
