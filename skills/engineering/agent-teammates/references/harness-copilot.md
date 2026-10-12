# Teammates on Copilot CLI

Read this when the run's `HARNESS` is `copilot`. This harness declares `LIVE_MESSAGING=0` and `SEND=script` in `scripts/drivers/copilot/driver.env`: a teammate works one turn at a time, and you give it new work by running `retask.sh`, not by sending a message to a live session.

Copilot support is partial. Set `HARNESS=copilot` yourself: detection, Copilot model defaults in `team-init.sh`, reasoning effort and commodore's Copilot reference are [#63](https://github.com/jbuffin/skills/issues/63). Read [Security caveats](#security-caveats) before you launch anyone.

## What a teammate is

A teammate is a background `copilot -p` run in its own process group, with a fixed `--session-id`. `launch-teammate.sh` starts the run and returns right away. When the turn ends, copilot exits and `status` reports the session `done`. The session stays in `~/.copilot/session-state/<session-id>/`, and `retask.sh` continues it by running `copilot -p` again with the same `--session-id`.

- There is no live messaging. A turn takes no input mid-turn.
- The coordinator is the only thing that wakes a finished teammate, with `retask.sh`.
- There is no advisor. `team-preflight.sh` prints `ADVISOR n/a (copilot)`, and teammates write `none` under `## Advisor consults`.
- There are no viewer panes. `VIEWER` is ignored.

## Setting up a run

1. Create the run with the harness preset: `HARNESS=copilot <team>/team-init.sh <run-name> <repo>`. It writes `HARNESS=copilot` to `team.env`.
2. `team-init.sh` still writes Claude model names. Replace every `MODEL_<ROLE>` the run uses, and `MODEL`, with names `copilot --model` accepts, for example `claude-sonnet-5.5` and `claude-opus-5.5`. `ADVISOR`, `PERMISSION_MODE`, `CMUX*` and `CLAUDE_CONFIG_DIR` are ignored.
3. Run `<teammates>/drivers/copilot/preflight <team-dir>`. It fails when `copilot` isn't on `PATH`, or when one headless read-only turn on `MODEL_REVIEWER` (else `MODEL_IMPLEMENTER`, else `MODEL`) exits non-zero or prints nothing. A bad model name fails here with copilot's own message. It doesn't check `jq`, which `teammate-tail.sh` needs.
4. Copilot uses the engineer's existing sign-in. Have them sign in before the run.

## Permissions per role

The flag set is chosen from `--read-only`, not from `--role`. Every run, launch and resume alike, gets `--no-ask-user`, `-s`, `--session-id <id>` and `--add-dir <team-dir>`.

| Teammate | Flags | What it can do |
| --- | --- | --- |
| launched with `--read-only` (reviewer, security reviewer, brief checker, triager) | `--available-tools bash view glob grep`, `--deny-tool=write`, and `--allow-tool` for `shell(git log)`, `shell(git show)`, `shell(git diff)`, `shell(git status)`, `shell(gh pr view)`, `shell(gh pr diff)`, `shell(gh issue view)` | reads files and runs the allowed commands. Copilot's write tool is gone and other shell commands are refused, but see [Security caveats](#security-caveats) |
| any other (implementer, test writer, target steward, scribe) | `--available-tools bash view edit create glob grep`, `--allow-all-tools`, and `--deny-tool` for `shell(git push:*)`, `shell(gh pr merge:*)`, `shell(gh pr create:*)`, `shell(gh api:*)`, `shell(gh issue:*)` | runs any command as the engineer, except the five denied prefixes |

What these flags need in order to work, on Copilot 1.0.95:

- `--add-dir <team-dir>` on every run. Under `--no-ask-user`, Copilot refuses reads and writes outside the working directory unless the directory is added, even with `--allow-all-tools`. Without it, no teammate can read its brief or write its report.
- The `:*` suffix on the writer denies. Without it, three-token denies such as `shell(gh pr merge)` never match, and `gh pr merge` and `gh pr create` reach GitHub. The read-only allows match with arguments as written.
- `-s`, so stdout is the final message only.

Put every prompt and message file in the team directory. A file anywhere else is outside the teammate's added directories, so the teammate can't read it. A read-only teammate's final message then says so, the driver saves it as its report, and the watchdog prints `DONE`.

## How a read-only teammate reports

A read-only teammate can't write its report, so the contract's "write the report, then the marker" doesn't apply to it. Its launch and re-task prompts tell it that its final message is its report. When its run exits 0 with a non-empty final message, the driver writes `<team-dir>/reports/<name>.md`, then `<team-dir>/reports/<name>.done`. A run that fails or ends with no message gets neither, so the watchdog reports it `BLOCKED`.

Never write a `.proof` for a read-only Copilot role. It can't run `evidence.sh`, so it could never verify. Writers write their own report, marker and evidence.

## Security caveats

The Copilot permission flags are guardrails against mistakes, not a sandbox. Copilot's OS sandbox is [#49](https://github.com/jbuffin/skills/issues/49). Say these plainly to the engineer before an unattended run:

- **Writers run as the engineer.** `--allow-all-tools` lets a writer run any command. The five denies stop only those exact command prefixes: other spellings (`git -C . push`, `git -c k=v push`, `env git push`, a script that calls git), `curl` with `gh auth token`, and `gh` commands nobody listed (`gh pr review`, `gh pr comment`, `gh release create`) all get through. Keep any credential a writer must not use out of its environment.
- **Read-only teammates can write files.** `git log`, `git show` and `git diff` accept `--output=<file>`, and the read-only allowlist allows them with any arguments. On Copilot 1.0.95, a read-only teammate's `git log -1 --output=<team-dir>/x` and `git diff --output=<team-dir>/x` both wrote into the team dir, and `ls` showed it the file names there. `--deny-tool=write` removes only Copilot's own write tool.
- **Every teammate can write the team directory**, because `--add-dir <team-dir>` covers all of it. That includes:
  - its own state file, `<team-dir>/copilot-<session-id>`. `send` re-reads `ro`, `workdir` and `model` from it on every re-task, so a forged `ro=0` resumes a read-only teammate with the writer flags, in any directory it names. Its `pid` and `pgid` decide which process group `close-teammate.sh` kills;
  - `team.env`, which every coordinator script sources, so code written there runs in the coordinator;
  - other teammates' reports and markers.

  A writer can do all of this through its shell anyway. The new risk is a read-only teammate doing it after reading hostile content, such as a PR under review.

The cheap checks that go with this:

1. Before every `retask.sh` of a read-only teammate, read its state file. Re-task it only when the state file still has `ro=1` and `workdir=` matches column 5 of its row in `teammates.tsv`.
2. Record `shasum <team-dir>/team.env` at launch, and compare it after every read-only turn.
3. After every read-only turn, run `git -C <workdir> status --porcelain` and check it's empty.
4. Treat a read-only report that's surprising as unverified until `teammate-tail.sh` shows the turn that produced it.

If any check fails, stop the run and tell the engineer. Don't re-task the teammate.

## Launch, re-task, close

Launch and close as in `SKILL.md`. `launch` and `send` wait up to 1 s and exit 1 if copilot has already exited non-zero. A launch the CLI rejects later still returns 0, and only the watchdog's `BLOCKED` shows it.

To give a teammate its next job:

1. Write the job to a file in the team directory, with the file-writing tool.
2. For a read-only teammate, run the checks in [Security caveats](#security-caveats).
3. Run `<teammates>/retask.sh <team-dir> <name> <message-file>`.

`retask.sh` resumes the session with the same `--session-id` and the flags its state file records, and resets the watchdog clock. Don't run `retasked.sh` after it. `send` waits up to `COPILOT_SEND_WAIT` seconds (default 60) for the previous turn to exit, then refuses with exit 1 and records nothing. Wait and run it again.

A teammate that is stuck mid-turn can't be nudged. Close it with `close-teammate.sh` and relaunch it fresh with the stuck step spelled out.

When you paste the teammate contract into a brief, keep the `LIVE_MESSAGING=0` lines and drop the advisor line.

## Run the watchdog

Run `<teammates>/watch-teammates.sh <team-dir>` as on any other harness. Each poll reads `<teammates>/drivers/copilot/status <team-dir>`, which prints one line per session: `<session-id> - <state> <last-activity>`.

| State | Meaning |
| --- | --- |
| `working` | its run's process is alive |
| `done` | its run exited, however it ended |
| `stopped` | `close-teammate.sh` stopped it |

Liveness comes from the pid and process group in the state file, not from Copilot's `inuse.*.lock` files, which a stop leaves behind. Last activity is the mtime of the session's `events.jsonl`, or the re-task time if that's later. `STALL` fires when a `working` session's last activity is `STALL_MIN` minutes old.

## What the engineer sees

There's no dashboard and no attaching. To see who is live, run `<teammates>/drivers/copilot/status <team-dir>`. To see what a teammate is doing, run `<teammates>/teammate-tail.sh <team-dir> <name> [n]`, which prints its transcript path and its last `TOOL` and `SAID` lines from `events.jsonl`. The text is the teammate's own, unescaped.

## Where sessions live

Each session is `~/.copilot/session-state/<session-id>/`, with its `events.jsonl`. The driver's own files are in the team directory: `copilot-<session-id>` (name, workdir, model, ro, pid, pgid, started, resumed, stopped as `key=value` lines) and `copilot-<session-id>.out`, `.err` and `.rc` from the last run. Closing keeps all of them.

## Closing

Close teammates with `close-teammate.sh`. It sends `TERM`, then `KILL`, to the run's process group, and keeps the session directory. Never do these instead:

- delete a session through `copilot sessions` or by removing its `session-state` directory;
- kill copilot by hand: no `closed` row is written, so `retask.sh` still resumes the session;
- relaunch a teammate with `--allow-all`, `--yolo`, `--allow-all-paths`, `--allow-all-tools` on a read-only role, or a wider allowlist to get past a denial: stop and ask instead;
- open the session interactively with `copilot --resume=<session-id>`: the teammate's next turn would pick up your input.

## Fallback when a launch fails

There is no `NO_BG` on Copilot: a launch exits 1 or 5, never 2, so the in-process subagent fallback in `SKILL.md` doesn't apply.

- Exit `5` means the launch was refused. Close the live session or pick another name only when the message says a session is already running under that name.
- Exit `1` means copilot isn't on `PATH`, or it exited non-zero within 1 s. Retry once. If it fails again, stop and ask the engineer, attaching `<team-dir>/copilot-<session-id>.err`.
