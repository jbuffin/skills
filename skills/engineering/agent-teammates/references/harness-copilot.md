# Teammates on Copilot CLI

Read this when the run's `HARNESS` is `copilot`. This harness declares `LIVE_MESSAGING=0` and `SEND=script` in `scripts/drivers/copilot/driver.env`: a teammate works one turn at a time, and you give it new work by running `retask.sh`, not by sending a message to a live session.

Read [Security caveats](#security-caveats) before you launch anyone. commodore's `references/harness-copilot.md` covers the default models, the capability rule and fix rounds.

## What a teammate is

A teammate is a background `copilot -p` run in its own process group, with a fixed `--session-id`. `launch-teammate.sh` starts the run and returns right away. When the turn ends, copilot exits and `status` reports the session `done`. The session stays in `~/.copilot/session-state/<session-id>/`, and `retask.sh` continues it by running `copilot -p` again with the same `--session-id`.

- There is no live messaging. A turn takes no input mid-turn.
- The coordinator is the only thing that wakes a finished teammate, with `retask.sh`.
- There is no advisor. `team-preflight.sh` prints `ADVISOR n/a (copilot)`, and Copilot teammates aren't told to use a custom agent through `task` as a stand-in. They write `none` under `## Advisor consults`.
- There are no viewer panes. `VIEWER` is ignored.

## Setting up a run

1. Create the run from inside Copilot CLI: `<team>/team-init.sh <run-name> <repo>`. Detection sees `COPILOT_CLI=1` and writes the settings in [Settings in `team.env`](#settings-in-teamenv). A shell that also sets `CLAUDECODE=1` (Copilot passes its parent's environment through) makes detection print both harnesses, and `team-init.sh` stops with "more than one harness detected". Start Copilot from a shell with `CLAUDECODE` unset.
2. Change a model only when the engineer names one `copilot --model` accepts.
3. Run `<teammates>/drivers/copilot/preflight <team-dir>`. It runs two headless turns and fails when `copilot` isn't on `PATH` or either turn fails:
   - a read-only turn on `MODEL_REVIEWER` (else `MODEL_IMPLEMENTER`, else `MODEL`), which fails when it exits non-zero or prints nothing;
   - a writer turn on `MODEL_IMPLEMENTER` (else the read-only turn's model), with the writer permission flags and the run's script directories, which fails when it can't run `evidence.sh` in a throwaway git dir. The `FAIL` line names Copilot's path guard and `--add-dir`. This turn runs only when the read-only one passed. It uses no `EFFORT_<ROLE>`, so a bad effort still passes here.

   A bad model name fails with copilot's own message. The preflight doesn't check `jq`, which `teammate-tail.sh` needs. Allow up to 240 s for the two turns.
4. Copilot uses the engineer's existing sign-in. Have them sign in before the run.

## Settings in `team.env`

`team-init.sh` writes a Copilot `team.env` with these lines.

| Setting | Value | Meaning |
| --- | --- | --- |
| `HARNESS` | `copilot` | selects `scripts/drivers/copilot` and this reference |
| `MODEL` | `claude-sonnet-5.5` | the model for a launch with neither `--model` nor `--role` |
| `REQUIRE_ROLE` | `1` | every launch passes `--role` or `--model` |
| `MODEL_<ROLE>` | per role | the model for `--role <role>` (commodore's reference has the table) |
| `EFFORT_<ROLE>` | empty | the reasoning effort for `--role <role>`, passed as `--reasoning-effort <effort>` on launch and resume only when set, because some models reject the flag. `send` reuses the effort recorded at launch, so a later `EFFORT_<ROLE>` edit doesn't affect a session that's already launched. The value is any value `copilot --help` lists for `--reasoning-effort`. An unknown value reaches copilot, and launch then exits 1 within a second. The driver refuses only a malformed value, with exit 5 |
| `VIEWER` | `none` | Copilot teammates have no viewer panes |

Keep `MODEL` set: without it `team-env.zsh` falls back to the Claude alias `sonnet`, which Copilot rejects.

## Permissions per role

The flag set is chosen from `--read-only`, not from `--role`. Every run, launch and resume alike, gets `--no-ask-user`, `-s`, `--session-id <id>` and `--add-dir <team-dir>`, plus `--model <model>` and `--reasoning-effort <effort>` when set.

| Teammate | Flags | What it can do |
| --- | --- | --- |
| launched with `--read-only` (reviewer, security reviewer, brief checker, triager) | `--available-tools bash view glob grep`, `--deny-tool=write`, and `--allow-tool` for `shell(git log)`, `shell(git show)`, `shell(git diff)`, `shell(git status)`, `shell(gh pr view)`, `shell(gh pr diff)`, `shell(gh issue view)` | reads files and runs the allowed commands. Copilot's write tool is gone and other shell commands are refused, but see [Security caveats](#security-caveats) |
| any other (implementer, test writer, target steward, scribe) | `--add-dir` for each skill script directory (see the list below), `--available-tools bash view edit create glob grep`, `--allow-all-tools`, and `--deny-tool` for `shell(git push:*)`, `shell(gh pr merge:*)`, `shell(gh pr create:*)`, `shell(gh api:*)`, `shell(gh issue:*)` | runs any command as the engineer, except the five denied prefixes. Also writes the added script directories |

What these flags need in order to work, checked on Copilot CLI 1.0.95 (the script directories on 1.0.96):

- `--add-dir <team-dir>` on every run. Under `--no-ask-user`, Copilot refuses reads and writes outside the working directory unless the directory is added, even with `--allow-all-tools`. Without it, no teammate can read its brief or write its report.
- `--add-dir` for each skill script directory, on every writer run (launch and resume). The scripts a writer calls (`evidence.sh`, `secret-run.sh`, `push-branch.sh`) live outside its working directory and the team directory. The path guard refuses them even with `--allow-all-tools`, and an `--allow-tool 'shell(<script>:*)'` doesn't help either. Without the directories, every `evidence.sh` call is denied and `verify-report.sh` reports `verdict: unverified`. Read-only runs get none of them. The directories are:
  - the agent-teammates `scripts` directory, resolved from the driver's own location;
  - `PREFLIGHT_SCRIPTS` and `TEAM_SCRIPTS` from the run's `team.env`, each only when its value is an absolute path to an existing directory. The driver reads the literal `KEY=value` line as data, so a quoted value, a `~` or a `$VAR` is skipped without a warning, and `secret-run.sh` or `push-branch.sh` is then denied later. `team-init.sh` writes plain absolute paths.

  Copilot takes several `--add-dir` flags in one run. The driver skips a directory whose path string it has already added.
- The `:*` suffix on the writer denies. Without it, three-token denies such as `shell(gh pr merge)` never match, and `gh pr merge` and `gh pr create` reach GitHub. The read-only allows match with arguments as written.
- `-s`, so stdout is the final message only.

Put every prompt and message file in the team directory. A file anywhere else is outside the teammate's added directories, so the teammate can't read it. A read-only teammate then says so in its final message, the driver saves that as its report, and the watchdog prints `DONE` for a job that never ran.

## How a read-only teammate reports

A read-only teammate can't write its report, so the contract's "write the report, then the marker" doesn't apply to it. Its launch and re-task prompts tell it that its final message is its report. When its run exits 0 with a non-empty final message, the driver writes `<team-dir>/reports/<name>.md`, then `<team-dir>/reports/<name>.done`. A run that fails or ends with no message gets neither, so the watchdog reports it `BLOCKED`.

Give a read-only Copilot role no `.proof` file. It can't run `evidence.sh`, so `verify-report.sh` would never pass it. Still run `verify-report.sh` on its `DONE`: with no proof it checks that the report and marker are from this tasking. Writers write their own report, marker and evidence.

## Security caveats

The Copilot permission flags are guardrails against mistakes, not a sandbox. Copilot's OS sandbox is [#49](https://github.com/jbuffin/skills/issues/49). Say these plainly to the engineer before an unattended run:

- **Writers run as the engineer.** `--allow-all-tools` lets a writer run any command. The five denies stop only those exact command prefixes: other spellings (`git -C . push`, `git -c k=v push`, `env git push`, a script that calls git), `curl` with `gh auth token`, and `gh` commands nobody listed (`gh pr review`, `gh pr comment`, `gh release create`) all get through. Keep any credential a writer must not use out of its environment.
- **A writer can write the skill script directories.** It needs them added to run `evidence.sh`, and the same `--add-dir` lets it edit `evidence.sh`, `verify-report.sh`, `secret-run.sh` and `push-branch.sh`. Those are the installed skill's scripts, shared by every run on the machine and by the coordinator's own `verify-report.sh`, so an edited `evidence.sh` forges proof for later runs too. A writer can also point `PREFLIGHT_SCRIPTS` or `TEAM_SCRIPTS` in `team.env` at any directory, `/` included, and its next resume adds it. It can edit the driver itself. All of this was already possible under `--allow-all-tools`. Keeping the scripts read-only to a writer waits on #49; [#81](https://github.com/jbuffin/skills/issues/81) lists the options.
- **A read-only teammate can write any path.** `git log`, `git show` and `git diff` accept `--output=<file>`, and the read-only allowlist allows them with any arguments. Copilot's path guard doesn't constrain an allowed shell command's arguments, so it can write any path the engineer can write. In effect it can run code as the engineer, for example through `team.env`, `<workdir>/.git/config` (which `verify-report.sh` runs git against) or shell startup files. `--deny-tool=write` removes only Copilot's own write tool. Verified on Copilot CLI 1.0.95 (#78).
- **Run read-only Copilot teammates only on trusted input**, not on another person's PR or outside issue text, until Copilot's OS sandbox lands (#49). Hostile text in the teammate's context can make it write anywhere.
- **Every teammate can write the team directory**, a writer through `--add-dir <team-dir>` and a read-only teammate through `--output`. A forged state file (`<team-dir>/copilot-<session-id>`, which `send` re-reads on every re-task) with `ro=0` resumes a read-only teammate with the writer flags, and a forged `pid` or `pgid` redirects `close-teammate.sh`. Code written to `team.env` runs in every coordinator script.

A report that's surprising stays unverified until `teammate-tail.sh` shows the turn that produced it.

## Launch, re-task, close

Launch and close as in `SKILL.md`. `launch` and `send` wait up to 1 s and exit 1 if copilot has already exited non-zero. A launch the CLI rejects later still returns 0, and only the watchdog's `BLOCKED` shows it.

To give a teammate its next job:

1. Write the job to a file in the team directory, with the file-writing tool.
2. Run `<teammates>/retask.sh <team-dir> <name> <message-file>`.

`retask.sh` resumes the session with the same `--session-id` and the flags its state file records, and resets the watchdog clock. Don't run `retasked.sh` after it. `send` waits up to `COPILOT_SEND_WAIT` seconds (default 60) for the previous turn to exit, then refuses with exit 1 and records nothing. Wait and run it again.

A teammate that is stuck mid-turn can't be nudged; see the `STALL` row in [`SKILL.md`](../SKILL.md#watch). When you paste the teammate contract into a brief, follow [the contract's note](../SKILL.md#the-teammate-contract) for `LIVE_MESSAGING=0`.

## Run the watchdog

Run the watchdog in its bounded mode only, as one bare call between jobs, and again whenever it returns while anyone is live:

```bash
<teammates>/watch-teammates.sh --until-event <max-min> <team-dir>
```

It polls once a minute and exits 0 right after the poll that printed an event, or prints `WATCH timeout <max-min>` after `<max-min>` polls with none. Pass an explicit long timeout on the call itself, and pick `<max-min>` (in minutes) comfortably under it, so the call isn't cut off. The Copilot shell tool's default timeout is unverified. Rerun it after each exit. Seen markers persist in `<team-dir>/.watch-seen` and the `BLOCKED` counts in `<team-dir>/.watch-state`, so a rerun repeats no `DONE` and doesn't reset the two-in-a-row rule. The events are the ones in `SKILL.md`. `DONE` can arrive before `status` reads `done`, so check `status` before you re-task.

Each poll reads `<teammates>/drivers/copilot/status <team-dir>`, which prints one line per session: `<session-id> - <state> <last-activity>`.

| State | Meaning |
| --- | --- |
| `working` | its run's process is alive |
| `done` | its run exited, however it ended |
| `stopped` | `close-teammate.sh` stopped it |

Liveness comes from the pid and process group in the state file, not from Copilot's `inuse.*.lock` files, which a stop leaves behind. Last activity is the mtime of the session's `events.jsonl`, or the re-task time if that's later. `STALL` fires when a `working` session's last activity is `STALL_MIN` minutes old.

## What the engineer sees

There's no dashboard and no attaching. To see who is live, run `<teammates>/drivers/copilot/status <team-dir>`. To see what a teammate is doing, run `<teammates>/teammate-tail.sh <team-dir> <name> [n]`, which prints its transcript path and its last `TOOL` and `SAID` lines from `events.jsonl`. The text is the teammate's own, unescaped.

## Where sessions live

Each session is `~/.copilot/session-state/<session-id>/`, with its `events.jsonl`. The driver's own files are in the team directory: `copilot-<session-id>` (name, workdir, model, effort, ro, pid, pgid, started, resumed, stopped as `key=value` lines) and `copilot-<session-id>.out`, `.err` and `.rc` from the last run. Closing keeps all of them, and so does stopping: `stop` ends the run's process group and never touches the session directory. Copilot CLI 1.0.95 has no command that deletes a session: `copilot sessions --help` lists only `import`.

## Closing

Close teammates with `close-teammate.sh`. It sends `TERM`, then `KILL`, to the run's process group, and keeps the session directory. Never do these instead:

- delete a session by hand, by removing `~/.copilot/session-state/<session-id>` or anything in it: the driver reads the session's `events.jsonl` for status and `teammate-tail.sh`, and `retask.sh` resumes it;
- kill copilot by hand: no `closed` row is written, so `retask.sh` still resumes the session;
- relaunch a teammate with `--allow-all`, `--yolo`, `--allow-all-paths`, `--allow-all-tools` on a read-only role, or a wider allowlist to get past a denial: stop and ask instead;
- open the session interactively with `copilot --resume=<session-id>`: the teammate's next turn would pick up your input.

## Fallback when a launch fails

There is no `NO_BG` on Copilot: a launch exits 1 or 5, never 2, so the in-process subagent fallback in `SKILL.md` doesn't apply.

- Exit `5` means the launch was refused. When the message says a session is already running under that name, close it or pick another name. Otherwise fix what the message names and launch again.
- Exit `1` means copilot isn't on `PATH`, or it exited non-zero within 1 s. Retry once. If it fails again, stop and ask the engineer, attaching `<team-dir>/copilot-<session-id>.err`.
