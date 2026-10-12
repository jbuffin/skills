# Codex teammates are turn-based; the app-server daemon isn't used

The Codex driver launches each teammate with `codex exec`, sets `LIVE_MESSAGING=0`, and re-tasks a teammate with `codex exec resume` after it exits on its `.done` marker. That's the same shape as the Copilot CLI driver. `codex queue` can't reach a running `codex exec`: the message is lost and the turn is aborted. Live messages only work for threads on the app-server daemon, which the CLI can't start a thread on, so the driver would need its own JSON-RPC client for the daemon's socket.

## Considered options

- **Daemon-based driver with `LIVE_MESSAGING=1`**: rejected. It keeps live re-tasking, but it adds a JSON-RPC client to maintain, and in testing the daemon updated itself mid-run and left managed binaries in `~/.codex/packages/` that the run couldn't clean up.

## Consequences

Codex runs lose live messages and idle notices, as ADR 0002 sets out for any harness without live messaging. `codex exec resume` doesn't keep the sandbox setting, so the driver passes `-s` on every resume.
