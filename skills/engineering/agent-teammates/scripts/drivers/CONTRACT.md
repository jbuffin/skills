# Driver contract

Every harness has a folder here (`claude/`, `codex/`, `copilot/`) holding a `driver.env` and one executable per operation. The shared scripts run an operation through `drv <op> <args>` (`team-env.zsh`). A missing operation makes `drv` return 9 with a message on stderr, which the callers map to exit 5. Operations must never exit 9 themselves. The coordinator reads the declarations through the harness reference; the shared scripts don't source `driver.env`, except that `retask.sh` reads its `SEND=` line.

## Declarations

Each `driver.env` sets three values and holds nothing else the contract cares about:

- `LIVE_MESSAGING`: `1` when a live teammate can be sent new work, so the coordinator keeps its session open between rounds. `0` when a teammate works one turn at a time.
- `SEND`: `tool` when sending is a harness tool call (the driver has no `send` executable), `script` when `retask.sh` calls the driver's `send`.
- `SKILL_PREFIX`: what goes before a skill's name to invoke it: `/` (Claude Code, Copilot CLI) or `$` (Codex). commodore's `role-skills.sh` reads this line.

## Operations

`<team-dir>` is the run directory; the driver reads its `team.env` (through `team-env.zsh`) for its own settings. Every operation exits 0 on success; a non-zero exit is the shared script's exit code.

### launch

`launch <team-dir> <name> <workdir> <model> <prompt-file> <read-only: 0|1>`

Starts a background session named `<name>` in `<workdir>` (an existing directory) on `<model>`, told to read `<prompt-file>`, and opens a viewer pane if `team.env` asks for one. On success prints line 1 `<session-id> <viewer-ref|->`, then the lines to show the engineer after the "launched" line. Failure prints a message and exits:

- 1: sessions couldn't be listed, the session started with no id, or the harness CLI isn't on `PATH`.
- 2: no background session can run. The last line starts `NO_BG:` and names what to do instead.
- 5: a live session already has `<name>`, or the harness refuses an input, such as a malformed `TEAMMATE_EFFORT` (Copilot does).

Optional input: the environment variable `TEAMMATE_EFFORT`, set on every launch call (empty when the launch has no `--role` or the role has no `EFFORT_<ROLE>` in `team.env`), is the reasoning effort for harnesses that take one. Drivers may ignore it.

### status

`status <team-dir>`

Prints one line per known session: `<session-id> <status> <state> <last-activity-epoch|->`, `-` for an empty value; exits 3, printing nothing, when the sessions can't be listed. Only `<session-id>`, `<state>` and `<last-activity-epoch>` are read (`watch-teammates.sh`); `<status>` is unused and may be `-`. `<last-activity-epoch>` is when the session last did anything, however the driver finds out; `-` when unknown, and `STALL` then never fires for that session. The watchdog acts on `<state>`, and a session with no row counts as `missing`:

- `working`: the session is mid-turn; `STALL` fires when its last activity is older than `STALL_MIN`.
- `blocked`: its turn ended, or it waits on a prompt; two polls in a row fire `BLOCKED`.
- `done`: its turn ended normally; counts like `blocked` (no `.done` marker yet).
- anything else: resets the `BLOCKED` count and fires nothing but `STALE`.
- `stopped`, `failed`, `missing`: the session is gone; `GONE` fires. A harness whose process exits when a turn ends must report that as `blocked` or `done`, never `stopped` or `failed`.

### tail

`tail <team-dir> <label> <session-id> <n>`

Prints a `transcript: ...` line, then the session's last `<n>` tool calls as `TOOL` lines and its latest message as one `SAID` line, as plain text. `<label>` is the name or id the engineer typed, for the message when nothing is found (exit 3).

### stop

`stop <team-dir> <session-id>`

Stops the session without removing anything it created. Exits 0 if it was running, non-zero if not.

### send

`send <team-dir> <session-id> <message-file>`

Reserved for drivers that declare `SEND=script` (read by `retask.sh`). Gives the session `<message-file>` as its next job, resuming it if its process has exited. Returns once the job has started, without waiting for the turn to end, and exits non-zero if it couldn't start the job. Drivers with `SEND=tool` have no `send` executable; the coordinator sends through the harness's own tool.

### advisor-probe

`advisor-probe <team-dir> <model>`

Prints `ADVISOR ON <model>` or `ADVISOR OFF <model>: <reason>` as its last line; exits 0 either way. A driver with no `advisor-probe` makes `team-preflight` print `ADVISOR n/a (<harness>)`.

### has-skill

`has-skill <team-dir> <name>` (optional)

Exits 0 when the harness can load the skill `<name>` (a bare name, no prefix) for the run's repo (`REPO` in `team.env`), and 1 when it can't. It looks wherever the harness finds skills: the repo, the user's own skills, installed plugins and the skills built into the CLI. It reads `team.env` and writes nothing. commodore's `role-skills.sh` drops a skill this rejects. A driver without `has-skill` makes every named skill count as available, with a warning.

### list-skills

`list-skills <team-dir>` (optional)

Prints one `<name><TAB><file>` line for each skill the harness can load for the run's repo, sorted by name, each name once. The names are the ones `has-skill` accepts, by bare name, so build both from one search (each driver's `skills.zsh`). `<file>` is the skill's `SKILL.md`, or another file with a `description:` line such as a Copilot agent's `.agent.yaml`, and `-` when no file describes it, as for a skill built into the Claude Code CLI. It reads `team.env` and writes nothing. `setup-commodore` lists candidate role skills with it.

### preflight

`preflight <run-dir>` (optional)

The harness's own runtime checks: prints `OK` / `WARN` / `FAIL` lines, exits 1 if any is `FAIL`.

## Per-session state

A driver may keep its own files per session under `<team-dir>` (name them after the driver, e.g. `<team-dir>/<harness>-<session-id>`). `launch` must record there whatever the driver's re-tasking (`send`) needs that `teammates.tsv` doesn't hold: the read-only flag, the model and the workdir.
