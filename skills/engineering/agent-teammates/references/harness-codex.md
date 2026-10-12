# Teammates on Codex

Read this when the run's `HARNESS` is `codex`. This harness declares `LIVE_MESSAGING=0` and `SEND=script` in `scripts/drivers/codex/driver.env`: a teammate works one turn at a time, and you give it new work by running `retask.sh`, not by sending a message to a live session.

## What a teammate is

A teammate is a background `codex exec` turn in its own process group. `launch-teammate.sh` starts the turn and returns once codex has printed `thread.started`, not when the turn ends. When the turn ends, the teammate's process exits and `status` reports it `done`. The session (a Codex thread) stays on disk, and a later `codex exec resume <thread>` continues it with its context.

Everything else follows from that:

- There is no live messaging, and no `codex queue` or app-server. Never use either to reach a teammate.
- A turn takes no input mid-turn.
- The coordinator is the only thing that wakes a finished teammate, with `retask.sh`.

## Known limits

Tell the engineer these before a Codex run, and record their answer in the run's state. Each is explained in the section it links to.

- **Writers run with the engineer's permissions.** The two `git` rules writers need run outside the sandbox, and a writer can use them to run any command ([The `~/.codex/rules` lines](#the-codexrules-lines); follow-up [#66](https://github.com/jbuffin/skills/issues/66)).
- **Read-only doesn't cover MCP servers.** A read-only teammate's files and shell are sandboxed, but the MCP servers in the engineer's Codex config still start, and their tools are offered to it ([Sandbox per role](#sandbox-per-role)).
- **A writer can replace a read-only teammate's report.** Check every read-only report against its events log before you act on it ([How a read-only teammate reports](#how-a-read-only-teammate-reports)).
- **The sandbox follows `--read-only`, not `--role`.** A reviewer launched without the flag gets a writer's sandbox, network and the `git` rules.
- **A slow start fails the launch.** The launch waits 20 seconds for `thread.started`. An MCP server that is slow to start can push past that, and the launch exits 1.
- **A re-task isn't confirmed.** `retask.sh` reports success once the resumed turn is started in the background. A resume that dies at once shows up later as `BLOCKED`; read its `.err` file.
- **The preflight splits paths on whitespace.** A `REPO` or `worktrees.tsv` path with a space in it gets past the `core.hooksPath` check (it prints a `WARN`). Keep those paths free of spaces.
- **Sessions stay on disk.** Closing never deletes a rollout under `~/.codex/sessions`.

## Settings in `team.env`

`team-init.sh` writes a Codex `team.env` with these lines.

| Setting | Value | Meaning |
| --- | --- | --- |
| `HARNESS` | `codex` | selects `scripts/drivers/codex` and this reference |
| `MODEL` | `gpt-6.1-sol` | the model for a launch with neither `--model` nor `--role` |
| `MODEL_<ROLE>` | per role | the model for `--role <role>` |
| `EFFORT_<ROLE>` | per role | the reasoning effort for `--role <role>`, passed as `-c model_reasoning_effort=<effort>`. Empty passes nothing |
| `VIEWER` | `none` | Codex teammates have no viewer panes |

`ADVISOR` and `PERMISSION_MODE` aren't in a Codex `team.env`. `team-env.zsh` still defaults `MODEL=sonnet`, `ADVISOR=opus` and `PERMISSION_MODE=auto` on every harness, so they exist in the scripts' environment, but Codex ignores all three. Never write `ADVISOR`, `PERMISSION_MODE`, `CMUX*` or `CLAUDE_CONFIG_DIR` for a Codex run. Write `MODEL` as `gpt-6.1-sol`, because a missing `MODEL` falls back to the Claude name `sonnet`, which would then reach codex.

## Sandbox per role

The sandbox is chosen from `--read-only`, not from `--role`. Commodore always passes both for a read-only role. Nothing checks that pairing: a reviewer, security reviewer, brief checker or triager launched without `--read-only` runs as a writer, with network and the `git` rules.

| Teammate | How it runs | What it can do |
| --- | --- | --- |
| launched with `--read-only` (reviewer, security reviewer, brief checker, triager) | read-only sandbox and `--ignore-rules`: `-s read-only` on launch, `-c sandbox_mode="read-only"` on every resume | reads files. Its shell writes no file and has no network, so no `gh`. Only `--ignore-rules` makes that true: without it, a user-level `allow` rule would run a matching command outside the sandbox. MCP servers aren't covered (below) |
| any other (implementer, test writer, target steward, scribe) | `workspace-write`, network on | writes its working directory and `<team-dir>/reports`, and reaches the network |

Because a read-only teammate's shell has no network, put any GitHub data it needs (a PR diff, issue text, comments) in files under the run directory before you launch it, and name those files in its brief. Never expect it to run `gh`.

The sandbox doesn't cover MCP servers. On codex-cli 0.162.0 the servers in `~/.codex/config.toml` (`[mcp_servers.*]`) start for every teammate, read-only ones included, and their tools are offered to it, along with a web tool (`web__run`). An MCP server runs outside the sandbox, so a tool call could reach whatever that server can: post to Slack, write to GitHub, send mail. Whether such a call goes through from a read-only turn hasn't been tested. Before a run that feeds a read-only teammate untrusted text (someone else's PR in the review mission), list the engineer's MCP servers by name and have them disable, for the run, any that can write or post, or accept the risk.

`codex exec resume` takes no `-s` and no `-C`. On launch the driver passes `-s`. On every resume it passes the same choice as `-c sandbox_mode=…`, plus `-c sandbox_workspace_write.writable_roots=[<team-dir>/reports]` for a writer, and sets the working directory itself. A re-tasked read-only teammate keeps the read-only sandbox (checked on codex-cli 0.162.0: a write in a resumed turn was refused). A re-tasked writer's `writable_roots` replaces any `writable_roots` in `config.toml`, where the launch's `--add-dir` adds to them. So a writer that needed an extra root from the config on its first turn may lose it on a re-task. That's read from codex's `-c` override rules, not tested.

`--read-only` also matters for how a teammate reports (next section), so launch every read-only role with it.

Before you launch or re-task a read-only teammate, record the worktree's `git -C <worktree> rev-parse HEAD` and `git -C <worktree> status --short`. Run read-only turns only while no writer in that worktree is `working`. After the turn, both must match what you recorded. A change means the isolation failed: stop and ask the engineer.

## How a read-only teammate reports

A read-only teammate can't write files, so the contract's "write the report, then the marker" doesn't apply to it. Its launch prompt tells it so. Its final message is its report:

1. The driver runs the turn under a wrapper and has codex save the final message to a private file in the team directory.
2. After a completed turn that left a non-empty message, the wrapper renames that file to `<team-dir>/reports/<name>.md` and then creates `<team-dir>/reports/<name>.done`.
3. A turn that fails or ends with no message leaves no marker, so the watchdog reports it `BLOCKED` rather than `DONE`.

Never write a `.proof` for a read-only Codex role. It can't run `evidence.sh`, so it could never verify. Still run `verify-report.sh` on its `DONE`: with no proof it checks that the report and marker are from this tasking.

Writers write their own report, marker and evidence under `<team-dir>/reports`. That directory is writable for them, so a writer, or code a writer runs, can overwrite a read-only teammate's report and marker, and the watchdog then reports `DONE` again. A forged report reads as clean, not as surprising. So whenever a writer is live or has run since the read-only turn, check every read-only report against that teammate's own events log before you act on it: the report must match the `text` of the last `item.completed` event whose `item.type` is `agent_message` in `<team-dir>/codex-<name>.<n>.events`. That log holds every turn's `--json` events, in a place no writer's sandbox covers. In the review mission this matters most: the target steward is a writer and runs the PR's own code.

## The team directory must be private

Choose a team directory outside every path a writer can write: not `/tmp`, not `$TMPDIR` (`workspace-write` makes both writable by default), and not inside any worktree. Otherwise a writer can tamper with the driver's private files (the session state and the saved final message), and the protection above stops working. Commodore's `team-init.sh` puts the run directory under `${AGENT_TEAMS_DIR:-${CLAUDE_CONFIG_DIR:-~/.claude}/teams}`, outside the source tree. Never set `AGENT_TEAMS_DIR` or `CLAUDE_CONFIG_DIR` to a path under `/tmp`, `$TMPDIR` or a worktree on Codex.

## Launch, re-task, close

Launch and close as in `SKILL.md`. On success a launch prints `launched <name> as background session <thread-id> in <workdir>`, with `(read-only)` after it for a read-only role. It exits:

- `1` when codex printed no `thread.started` within 20 seconds. The driver stopped the process and printed the start of codex's stderr. An MCP server that is slow to start can cause this.
- `5` when the launch was refused. The message says why. Only when it reads "a live Codex session is already named …" do you close that session or pick another name. For anything else (a missing prompt file, an empty `MODEL_<ROLE>`, an invalid name), fix what the message names and launch again.

`status` and the watchdog name sessions by thread id. To find a teammate's thread id, read column 2 of its row in `<team-dir>/teammates.tsv` (the last row for that name).

To give a teammate its next job:

1. Write the job to a file, with the file-writing tool.
2. Run `<teammates>/drivers/codex/status <team-dir>` and check that the teammate's session reads `done`. A writer touches its marker before codex exits, so `DONE` can arrive while `status` still says `working`. `send` refuses a running turn, and `retask.sh` then fails with "send to … failed with exit 1; nothing recorded". When you see that, wait and run it again.
3. Run `<teammates>/retask.sh <team-dir> <name> <message-file>`.

`retask.sh` resumes the session with the file as its prompt, in the same sandbox, and resets the watchdog clock. It returns once the resumed turn is started in the background, without checking that the turn got going. A resume that dies at once (a removed worktree, a flag a newer codex rejects) shows up as `BLOCKED` a couple of polls later; read the teammate's `.err` file then. Don't run `retasked.sh` after it. It refuses a closed teammate. A read-only teammate re-tasked this way gets a fresh report and marker from its new turn.

A teammate that is stuck mid-turn can't be nudged; see the `STALL` row in [`SKILL.md`](../SKILL.md). When you paste the teammate contract into a brief, follow [the contract's note](../SKILL.md#the-teammate-contract) for `LIVE_MESSAGING=0`.

## The `~/.codex/rules` lines

Codex runs a command that a user-level `allow` rule matches outside the sandbox, without asking. Writers need exactly two such rules, because a writer can't commit in a linked worktree without them: the index lock is in the main repo's `.git/worktrees/`, outside the sandbox. Put these two lines in a `.rules` file under `~/.codex/rules/` (for example `default.rules`), or under `$CODEX_HOME/rules` when `CODEX_HOME` is set. Rules are user-level; put them there, not in a project.

```text
prefix_rule(pattern=["git", "add"], decision="allow")
prefix_rule(pattern=["git", "commit"], decision="allow")
```

Say these plainly to the engineer:

- With these two rules, a Codex writer can run arbitrary commands outside the sandbox, so writers effectively run with the engineer's permissions. `git add` and `git commit` run unsandboxed, and git runs the hooks, filters and fsmonitor of whichever repository it finds from the command's working directory. A writer can create such a repository inside its own writable root (a nested repo with its own hooks, or a rewritten gitfile) and commit in it. The preflight's `core.hooksPath` check is defence in depth for tracked hooks only; it doesn't close that route. The follow-up is [#66](https://github.com/jbuffin/skills/issues/66).
- The rules apply to every Codex session on the machine, not just this run's teammates.
- Any broader `allow` rule the engineer already has (for example `["gh"]` or `["git"]`) applies to writers too, outside the sandbox. The preflight looks only at rules that cover `git add` and `git commit`, so it stays silent about a `["gh"]` rule. Before an unattended run, list every `allow` rule in `~/.codex/rules/*.rules` (and `$CODEX_HOME/rules`), have the engineer keep or remove each, and remove the `gh` rules an earlier version of this reference asked for.
- Read-only roles run with `--ignore-rules`, which also drops the engineer's `forbidden` rules for them. That's accepted.

There are no `gh` rules and none for `git push`. Pushes go through `push-branch.sh`.

**Never turn the coordinator's own calls into user-level rules.** `gh`, `push-branch.sh`, `retask.sh`, `launch-teammate.sh`, `close-teammate.sh` and file writes must not become `prefix_rule` lines: every writer teammate inherits user-level rules, and would run those commands outside its sandbox. The coordinator gets them approved for its own session by the engineer, through Codex's own approval. That's unverified from inside a real Codex session. No `<teammates>` script is safe as a user-level prefix rule: each takes a `<team-dir>` argument and sources `<team-dir>/team.env`, and `watch-teammates.sh` also writes into it, so a writer could run its own code through such a rule.

`<teammates>/drivers/codex/preflight <team-dir>` (run for you by commodore's `team-preflight.sh`) reads the `*.rules` files as text. It checks only the two git rules and `core.hooksPath`, and prints:

- A `FAIL` for a missing rule that names the command and ends with the exact `prefix_rule(…)` line to add. Add that line.
- A `FAIL` for a `decision="prompt"` rule that covers a needed command (it stops an unattended run): narrow or remove that rule, then add the two lines above. Don't change a broad `prompt` rule to `allow`: every command it covers would then run outside the sandbox. Make a rule `allow` only when it's no broader than the needed one.
- A `FAIL` for a `decision="forbidden"` rule that covers a needed command: narrow or remove that rule, then add the two lines above.
- A `WARN` when a broader `allow` rule covers `git add` or `git commit`. The needed rule counts as present. Mention it to the engineer.
- A `FAIL` when the resolved `core.hooksPath` is relative, or inside a writer-writable root: `WORKTREES_DIR`, a path in the run's `worktrees.tsv` (not `git worktree list`), or `<run>/reports` (`~/…` counts as absolute). It doesn't cover the repo's own main checkout, and it doesn't check `/tmp` or `$TMPDIR`. It gives a `WARN` when it can't check. Set `core.hooksPath` to an absolute path outside every writer-writable root, or unset it, before launching a writer. A path inside any other writer's working directory is unsafe too, including one the preflight can't see (a writer in another repo, `/tmp`, `$TMPDIR`).
- An `OK` line about writers when all is well.

The preflight reads only keyword-form `prefix_rule(pattern=…, decision=…)` lines. A rule written another way (positional arguments, or built by other code in the file) isn't seen, and the preflight fails the command it covers even though codex would allow it. Write the lines in the form above.

Don't write prefix rules for `evidence.sh` or `gh api graphql`. A prefix rule matches every command that starts with it, and `evidence.sh … <label> -- <command>` runs whatever follows. Writers run `evidence.sh` inside their sandbox, and the coordinator does GitHub mutations itself.

## Run the watchdog

A Codex coordinator can't keep a watcher running in the background. Run the bounded mode as one bare call between jobs, and again whenever it returns while anyone is live:

```bash
<teammates>/watch-teammates.sh --until-event <max-min> <team-dir>
```

It polls once a minute and exits 0 right after the poll that printed an event, or prints `WATCH timeout <max-min>` after `<max-min>` polls with none. Pass an explicit long timeout on the call itself, and pick `<max-min>` (in minutes) comfortably under it, so the call isn't cut off. The Codex shell's own default limit is short and unverified; the end-to-end run used `<max-min>` 5, and each call returned within a minute or two. Rerun it after each exit. Seen markers persist in `<team-dir>/.watch-seen`, so a rerun doesn't repeat a `DONE`, and the `BLOCKED` counts and alert times persist in `<team-dir>/.watch-state`, so a rerun doesn't reset the two-in-a-row rule. The events are the ones in `SKILL.md`.

Each poll reads `<teammates>/drivers/codex/status <team-dir>`, which prints one line per session: `<thread-id> - <state> <mtime>`.

| State | Meaning |
| --- | --- |
| `working` | its turn is running |
| `done` | its turn ended, however it ended: codex exits when the turn does |
| `stopped` | `close-teammate.sh` stopped it mid-turn |

A teammate closed after its turn ended still reads `done`: there was nothing to stop. The registry's `closed` row is what marks it closed.

The mtime is the session's rollout file (or the events log before the rollout exists). `STALL` fires when a `working` session's mtime is `STALL_MIN` minutes old. A `done` turn with no new marker twice in a row is `BLOCKED`. With no marker the usual cause is a turn that failed or ended without a report.

For `BLOCKED`, read the raw log only after `teammate-tail.sh`: `<team-dir>/codex-<name>.<n>.events` (the `--json` event log of every turn) and `<team-dir>/codex-<name>.<n>.err` (codex's stderr). Lines `ERROR rmcp` in stderr are about unauthenticated MCP servers. They don't affect the turn, but they show that the engineer's MCP servers start for every teammate (see "Sandbox per role").

## What the engineer sees

There's no dashboard and no attaching. To see who is live, run `<teammates>/drivers/codex/status <team-dir>`. To see what a teammate is doing, run `<teammates>/teammate-tail.sh <team-dir> <name> [n]`, which prints its last tool calls and latest message from the events log. The watchdog's events tell the engineer the rest.

## Where sessions live

Each session's rollout is `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<timestamp>-<thread-id>.jsonl`, with `CODEX_HOME` defaulting to `~/.codex`. The driver's own files are in the team directory: `codex-<thread-id>.state` (name, process group, model, effort, working directory), `codex-<name>.<n>.events`, `.err` and, for a read-only role, a private `.out` that the wrapper renames into `reports/`. `close-teammate.sh` stops the turn and keeps all of them, so a closed session's rollout stays readable.

## Closing

Close teammates with `close-teammate.sh`. It stops the turn's process group and every process below it. Limits:

- A tool process that was re-parented to pid 1 after codex exited isn't found. After closing, look for strays: run `ps -A -o pid=,ppid=,lstart=,command=` and pick processes with parent `1` that started during the teammate's turns, then run `lsof -a -p <pid> -d cwd` on each to see whether its working directory is the teammate's. Stop only the ones that no live teammate could own (check `status` first), or report them to the engineer instead.
- Never run these in place of `close-teammate.sh`:
  - `codex delete`, or anything else that removes a session or its rollout;
  - killing the codex process or its group by hand: it writes no `closed` row, so `retask.sh` still resumes the thread. The tool processes it started can survive, and the watchdog reports a `BLOCKED` teammate, not a closed one;
  - `codex` with `danger-full-access`, `--dangerously-bypass-approvals-and-sandbox`, `--full-auto` or an approval-policy override (`-a`, `approval_policy`), to get past a denial or a launch failure: stop and ask instead;
  - an interactive `codex resume <thread>`: it appends to the thread the driver resumes, and the teammate's next turn would pick up your input.

## Fallback when a launch fails

There is no `NO_BG` on Codex: a launch exits 1 or 5, never 2, so the in-process subagent fallback in `SKILL.md` doesn't apply.

- Exit `5` means the launch was refused. Handle it as "Launch, re-task, close" says.
- Exit `1` means codex printed no `thread.started`. Retry the launch once. If it fails again, stop that unit and ask the engineer, attaching `<team-dir>/codex-<name>.<n>.err` (the launch output names it). Don't do the teammate's role yourself: that breaks the independence the roles exist for.
