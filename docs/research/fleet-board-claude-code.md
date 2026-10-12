# Research: what Claude Code exposes for watching a task force

Ticket: [#54](https://github.com/jbuffin/skills/issues/54), part of the fleet board map [#53](https://github.com/jbuffin/skills/issues/53).

Question: what can an outside process read from Claude Code to show each live teammate's state and latest
activity, without the skills writing anything new?

- CLI version for every probe: `claude --version` → `2.1.296 (Claude Code)`, macOS (Darwin 25.6.0), 2026-10-11.
- Probes were read-only against the engineer's sessions. Two throwaway background sessions (`fleetprobe-1`,
  `fleetprobe-2`, model `haiku`, `--permission-mode manual`, a `--settings` file with logging hooks) were started
  in a scratch directory and stopped with `claude stop` afterwards.
- **Verified** = a probe was run here; the command and the relevant output are quoted. **Doc** = stated in the
  official docs, with a link. **Inferred** = a conclusion drawn from the above, not tested directly.

## Short answer

`claude agents --json` is the supported source and covers most of a teammate line: name, id, cwd, a five-value
`state`, and a live `status` with `waitingFor` that says *why* a session needs input. What it does not give is
**time in state** and **latest activity**. Both exist on disk, in files the docs tell you not to parse
(`$CLAUDE_CONFIG_DIR/jobs/<id>/state.json` + `timeline.jsonl`, `$CLAUDE_CONFIG_DIR/sessions/<pid>.json`), or can
be derived from the transcript (`projects/<dir>/<session>.jsonl`, also declared internal). The supported way to
get them is a user-level settings hook (or `statusLine` with `refreshInterval`), which does fire inside
background sessions and receives `session_id` and `transcript_path`. Everything is per `CLAUDE_CONFIG_DIR`: each
config dir has its own daemon and its own listing. "FleetView" is Claude Code's internal name for agent view, not
a separate API.

## 1. `claude agents --json`

**Doc** ([agent view](https://code.claude.com/docs/en/agent-view)): `--json` prints
every live session (interactive and background), plus background sessions still working or blocked after their
process exited; `--all` adds completed background sessions; `--cwd <path>` filters to sessions started under a
path (including ones that moved into `<path>/.claude/worktrees/`). Fields:

| Field | Present | Values |
| --- | --- | --- |
| `cwd`, `kind`, `startedAt` | always | `kind`: `interactive` / `background`; `startedAt` in Unix ms |
| `id` | background | short id for `attach`, `logs`, `stop` |
| `state` | background | `working`, `blocked`, `done`, `failed`, `stopped` |
| `pid`, `status` | while the process is alive | `busy`, `waiting`, `idle` |
| `waitingFor` | when `status` is `waiting` | `permission prompt`, `input needed`, `sandbox request`, `worker request`, `dialog open` |
| `sessionId`, `name` | when set | full UUID; display name (`-n`) |

The docs say to poll `claude agents --json --all` from scripts and **not** to read `jobs/<id>/state.json`.

**Verified** (`claude agents --json`, one live background row):

```json
{"pid":50868,"id":"6da1e41d","cwd":".../skills-52-commodore-retask-u1","kind":"background",
 "startedAt":1791772356527,"sessionId":"6da1e41d-5d3f-421d-9ae9-38c6577a9c65",
 "name":"u1-implementer","status":"idle","state":"done"}
```

Interactive rows (for example the commodore coordinator's own session) have no `id` and no `state`, only
`status`:

```json
{"pid":23395,"cwd":"/Users/jasonbuffin/github_repos_Personal/skills","kind":"interactive",
 "startedAt":1791771276642,"sessionId":"2b96b2a0-...","name":"skills-3c","status":"busy"}
```

**Verified** (`claude agents --json --all`, 229 rows): field counts `cwd 229, id 227, kind 229, name 229,
sessionId 229, startedAt 229, state 227, pid 5, status 5`; states `done 173, stopped 53, failed 1`; rows whose
process has exited carry no `pid`/`status`. No row has a summary, a "last activity" time or a "state since" time.

**Verified** (throwaway session `fleetprobe-2`, asked to write a file in manual permission mode):

```json
{"id":"140c42c1","name":"fleetprobe-2","status":"busy","state":"working"}          // t+3s
{"id":"140c42c1","name":"fleetprobe-2","status":"waiting","waitingFor":"permission prompt","state":"blocked"}  // t+6s
```

So `state: blocked` plus `waitingFor` is the native needs-input signal, and it distinguishes a permission prompt
from a question. After `claude stop`, the row became `"state":"stopped","status":null`. `fleetprobe-1`, which had
already finished its turn, stayed `"state":"done"` after `claude stop` (the stop of an idle session doesn't flip
it to `stopped`).

**Doc** (agent view): the supervisor stops a finished or waiting, unattached session's process after about an
hour; the row stays and `pid`/`status` disappear. A row's age in agent view counts from session start, not from
the wait.

## 2. Files under the config dir (undocumented internals)

The `--json` output is assembled from these. They carry what the board most wants and the CLI doesn't print,
but the docs call the format internal ("Don't read `~/.claude/jobs/<id>/state.json` directly, since its values
are overwritten on update").

**Doc** ([agent view, storage](https://code.claude.com/docs/en/agent-view)): `daemon.log`, `daemon/roster.json`
(running sessions), `jobs/<id>/state.json` (per-session state), `jobs/<id>/tmp/`, `daemon.lock`. Each background
session has `CLAUDE_JOB_DIR=<config>/jobs/<id>`.

**Verified** `jobs/<id>/state.json` (keys across 227 jobs include `state`, `detail`, `tempo`, `inFlight`,
`output.result`, `intent`, `name`, `respawnFlags`, `cwd`, `createdAt`, `updatedAt`, `lastTerminalAt`,
`worktreePath`, `worktreeBranch`, `suggestedReply`):

```json
{"state":"done","detail":"retask rule added to commodore docs; suite green, not pushed","tempo":"active",
 "output":{"result":"AC7 re-task rule added to commodore docs on retask/u1-commodore-fix-rounds; ..."},
 "intent":"You are teammate u1-implementer. Read .../prompts/u1-implementer.md and do exactly what it says.",
 "updatedAt":"2026-10-12T02:39:51.137Z", ...}
```

`detail` is the agent-view row summary (Doc: "a one-line summary generated by a Haiku-class model … a working row
shows what the session says it's doing; a blocked row shows the question it's asking"). That is the board's
"latest activity" field, ready-made.

**Verified** `jobs/<id>/timeline.jsonl`: one line per summary/state change with a timestamp, so time in state is
`now - at` of the last line whose state differs from the one before:

```json
{"at":"2026-10-12T02:32:38.951Z","state":"working","detail":"Reading .../prompts/u1-implementer.md","text":""}
{"at":"2026-10-12T02:33:49.174Z","state":"working","detail":"writing AC7 check; will commit it alone, then show it failing","text":""}
{"at":"2026-10-12T02:35:26.364Z","state":"done","detail":"retask rule added to commodore docs; suite green, not pushed","text":"I've finished reading the brief ..."}
```

Blocked entries carry the question: `{"state":"blocked","detail":"Keep it patched, or retire format 1?", ...}`.
States seen across all timelines: `working 3032, done 396, blocked 84, failed 1, running 1`.

**Verified, with a caveat:** the job files lag the live listing. While `fleetprobe-2` was on a permission prompt,
`claude agents --json` said `blocked` but `jobs/140c42c1/state.json` still said `{"state":"working","detail":"Writing probe.txt"}`.
The live waiting state comes from the next file.

**Verified** `sessions/<pid>.json` (one per live process, interactive and background):

```json
{"pid":11241,"sessionId":"140c42c1-...","kind":"bg","jobId":"140c42c1","name":"fleetprobe-2",
 "status":"waiting","waitingFor":"permission prompt","statusUpdatedAt":1791772925739,"updatedAt":1791772925739,
 "messagingSocketPath":"/tmp/cc-socks/11241.sock","version":"2.1.296", ...}
```

`statusUpdatedAt` gives time in the current live status (busy / waiting / idle). Next to each JSON sits a
`<pid>.<hash>.key` file; it wasn't read and a board shouldn't read it.

**Verified** `claude daemon status` prints the supervisor's pid, version, config, socket dir and worker count
(`bg workers: 3 running (control.sock), 3 in roster.json`). Not needed for the board beyond a health line.

## 3. Session transcripts

**Doc** ([sessions](https://code.claude.com/docs/en/sessions#where-transcripts-are-stored)): JSONL at
`<config>/projects/<project>/<session-id>.jsonl`, `<project>` being the cwd with non-alphanumerics replaced by
`-` (truncated plus a hash past 200 chars). "The entry format is internal to Claude Code and changes between
versions." The supported ways to reach a transcript are `transcript_path` in hook and status-line input.

**Verified** (`fleetprobe-2` transcript while it waited on the permission prompt): the last records were
`assistant` with a `tool_use` (`Write`) and no `tool_result`. Nothing in the transcript says "waiting on a
permission prompt", so the transcript alone can't tell *blocked on a prompt* from *running a long tool*. Other
record types seen: `attachment`, `last-prompt`, `custom-title`, `agent-name`, `mode`, `permission-mode`.

What the transcript is good for (already used by `teammate-tail.sh` and the watchdog's `STALL`): mtime as a
progress heartbeat, and the last `tool_use` / `text` as a fallback "latest activity" line.

## 4. Hooks

**Doc** ([hooks](https://code.claude.com/docs/en/hooks)): every hook gets `session_id`, `transcript_path`, `cwd`,
`permission_mode`, `hook_event_name` (and `agent_id`/`agent_type` inside subagents). Relevant events: `SessionStart`
(has `session_title`), `UserPromptSubmit`, `PreToolUse`/`PostToolUse`, `Notification`, `Stop` (has
`last_assistant_message`, `background_tasks`), `StopFailure`, `SessionEnd`. `Notification` types include
`permission_prompt` (~6 s after a permission prompt opens), `idle_prompt`, `elicitation_dialog`, and
`agent_needs_input` / `agent_completed`, which fire **only while agent view is open in a terminal**. Plugins ship
hooks in `hooks/hooks.json`; user-, project-, local- and plugin-level hooks merge.

**Verified** (throwaway sessions with `--settings` hooks that append to a log file): hooks fire inside `claude --bg`
sessions, and the hook process sees `CLAUDE_JOB_DIR` and `CLAUDE_CONFIG_DIR`:

```text
02:42:02 SessionStart  job=/Users/jasonbuffin/.claude-personal/jobs/140c42c1 cfg=/Users/jasonbuffin/.claude-personal
02:42:02 UserPromptSubmit  job=.../jobs/140c42c1
02:42:05 PreToolUse  job=.../jobs/140c42c1 keys=[...,"tool_input","tool_name",...]
02:42:11 Notification permission_prompt job=.../jobs/140c42c1 keys=["cwd","hook_event_name","message","notification_type",...]
02:42:01 Stop  job=.../jobs/d0c52188 keys=["background_tasks",...,"last_assistant_message",...]
02:42:21 SessionEnd  job=.../jobs/140c42c1
```

`Notification permission_prompt` fired in the background session itself with no agent view open, 6 s after the
tool call. So a user-level (`<config>/settings.json`) or plugin-level hook can write per-session status to a file
the board reads, keyed by `session_id` (or the short id from `CLAUDE_JOB_DIR`), without touching the skills.

**Verified** precedent: cmux, the terminal the engineer runs, already does exactly this. The teammates' recorded
`respawnFlags` include `--settings /var/folders/.../cmux-claude-settings.*`, whose hooks are
`Notification, PermissionRequest, PostToolUse, PreToolUse, SessionEnd, SessionStart, Stop, StopFailure,
SubagentStop, UserPromptSubmit`. A flag passed at launch is carried into respawns.

**Inferred:** a hook only sees sessions started after it's installed (or respawned), and it adds a process spawn
per tool call. A hook-written status file also duplicates what `jobs/` already holds, so it's the fallback if the
`jobs/` files change shape, not the first choice.

## 5. Status line and mods

**Verified:** the `statusLine` command from `--settings` ran in the background sessions too (log lines with keys
`session_id`, `session_name`, `transcript_path`, `cost`, `context_window`, `model`, `rate_limits`, `workspace`,
`cwd`). **Doc** ([status line](https://code.claude.com/docs/en/statusline#when-the-status-line-updates)): it runs
on session events and, with `refreshInterval`, every N seconds. That is a second supported push channel, and the
only one that carries cost and context-window use.

**Doc** ([mods](https://code.claude.com/docs/en/plugins/mods/overview)): a mod is in-process JS in a plugin that
can draw panes and bands, observe tool calls and turns, and "send a message to another of your sessions". Its
hooks run in every session that loads the plugin, but it draws only in that session's own terminal or the
Desktop app. **Inferred:** a mod could publish richer per-session status than a settings hook, but it can't be the
fleet board itself (it lives inside one session) and it's heavier to ship than a settings hook.

## 6. FleetView

**Verified:** there's no public page or CLI command by that name (docs index has none; `fleetview` isn't on
PATH). The string appears inside the Claude Code 2.1.296 binary as agent view's internal name
(`mountFleetView`, `FleetViewScreen`, `touchFleetViewHeartbeat`, `[FleetView] action ...`,
`Set model for this FleetView session`), and the built-in `claude` agent is described as "FleetView's default
when no agent name is typed". An unrelated third-party npm package `fleetview` (a TUI that dispatches to
opencode, Claude Code and Copilot CLI) also exists ([socket.dev](https://socket.dev/npm/package/fleetview)).
Conclusion: FleetView = `claude agents`; nothing extra to read.

## 7. Opening `attach` / `logs` from another app

**Verified** (`claude --help`, `claude attach --help`, `claude logs --help`):

- `claude attach <id|name>` opens the session in the terminal it runs in; `←` returns to agent view, Ctrl+Z to
  the shell, and the session keeps running either way. A partial name works (running sessions only, Doc v2.1.290+).
- `claude logs <id|name>` prints recent raw terminal output (ANSI frames; 13 KB for a 20-second session).
- `claude --resume <session-id>` on a running background session attaches to it (Doc,
  [sessions](https://code.claude.com/docs/en/sessions#resume-a-running-background-session)); `--desktop` with
  `--resume <id>` opens it in the Claude Desktop app instead of the terminal.

So a board opens a teammate by launching a terminal running `CLAUDE_CONFIG_DIR=<dir> claude attach <id>`, the
same way `launch` already does for `VIEWER=cmux|tmux` (`cmux new-split ... --command "claude attach $ID"`,
`tmux split-window ... "claude attach $ID"`). A web page can't do that by itself; it needs a local helper or a
URL scheme of the terminal app. **Inferred:** `logs` is not worth showing in a board; the `jobs` timeline or
`teammate-tail.sh` give readable text.

## 8. More than one `CLAUDE_CONFIG_DIR`

**Doc** (agent view): "if you set `CLAUDE_CONFIG_DIR`, the supervisor uses that directory instead of `~/.claude`
and runs as a separate instance with its own sessions."

**Verified:** this machine has three config dirs, each with its own `daemon.lock` and `daemon/roster.json`
(`~/.claude`, `~/.claude-personal`, `~/.claude-work`). Listings don't overlap:

```text
CLAUDE_CONFIG_DIR=~/.claude-work claude agents --json      → 2 rows (bugsnag..., android...)
CLAUDE_CONFIG_DIR=~/.claude-personal claude agents --json  → 6 rows (u1-implementer, u1-reviewer-2, ...)
```

The job's `providerEnv` records its config dir (`{"CLAUDE_CONFIG_DIR":"/Users/jasonbuffin/.claude-personal"}`),
and every `attach`/`logs`/`stop` has to run with the same `CLAUDE_CONFIG_DIR`. There's no command that lists
config dirs; the board needs a configured list (or a scan of `~/.claude*` for `daemon.lock`).

**Verified, a naming clash:** `<config>/teams/` is also where Claude Code's own (experimental) agent teams write
`teams/session-<8>/config.json` (Doc, [agent teams](https://code.claude.com/docs/en/agent-teams#architecture)).
`~/.claude-work/teams/` holds both `session-692b9fb1/config.json` (native) and `issue-1744-chat-insets` (a run).
A board scanning `${AGENT_TEAMS_DIR:-$CLAUDE_CONFIG_DIR/teams}` must recognise a run by its `teammates.tsv` /
`team.env`, not by being a directory there.

## What this means for the fleet board

Run header:

| Field | From Claude Code natively? | Source |
| --- | --- | --- |
| repo | Partly | `cwd` of the coordinator / teammates (`claude agents --json`), mapped to a repo with `git -C`; the run's `state.md` is clearer |
| mission | No | run files (`state.md`, brief); `jobs/<id>/state.json` `intent` only holds the teammate's launch prompt |
| mode | No | run files |
| current unit | No | run files (`state.md`) |
| needs-input | Yes, supported | any teammate with `state: blocked` (`waitingFor` says why), or the coordinator's interactive row with `status: waiting` |

Teammate line:

| Field | From Claude Code natively? | Source |
| --- | --- | --- |
| name | Yes, supported | `name` in `--json` (= the `-n` the launcher passes; joins to `teammates.tsv` by `id`) |
| role | No | run files (the launcher's `--role`; not recorded by Claude Code beyond `--model` in `respawnFlags`) |
| unit | No | run files |
| state | Yes, supported | `state` (`working`/`blocked`/`done`/`failed`/`stopped`) + `status`/`waitingFor` for live detail; a registry row with no `--json` row = gone |
| time in state | Internal only | `jobs/<id>/timeline.jsonl` `at`, or `sessions/<pid>.json` `statusUpdatedAt` for the live status; `--json` has only `startedAt`. Supported fallback: a hook that stamps its own file, or the transcript mtime for "last activity" |
| latest activity | Internal only | `jobs/<id>/state.json` `detail` (agent view's own summary; the question when blocked; the result in `output.result` when done). Supported fallback: last `tool_use`/text in the transcript (`teammate-tail.sh`), or a `PreToolUse`/`Stop` hook writing its own file |

Bottom line for the map: Claude Code supplies identity, state and needs-input through a supported interface, and
supplies latest activity and time in state only through files it calls internal. Run-level fields (mission,
mode, unit, role) aren't Claude Code's to know and must come from the run directory the skills already write.
Nothing here requires a change to agent-teammates or commodore: the board can read `--json` per config dir, read
`jobs/<id>/` defensively for summary and timing, and fall back to transcript mtime and `teammate-tail.sh` when those
files are missing or change shape. A user-level hook is the supported escape hatch if that fallback isn't good
enough.
