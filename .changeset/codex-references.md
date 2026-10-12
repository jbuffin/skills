---
"jasonbuffin-skills": minor
---

Codex runs are supported end to end. `agent-teammates` and `commodore` each get a `references/harness-codex.md`. agent-teammates' covers turn-based re-tasking with `retask.sh`, the sandbox per role, how a read-only teammate reports (its final message is its report and the driver writes the marker), the five `~/.codex/rules` lines the preflight checks for, the bounded watchdog (`watch-teammates.sh --until-event`), where sessions live, the two `git` rules writers need (they run outside the sandbox) and why read-only roles launch with `--ignore-rules`, the commands never to run in place of `close-teammate.sh`, and what to do when a launch fails (there is no `NO_BG` on Codex). commodore's gives the default model and effort per role, the capability rule on Codex, the advisor as n/a, and a "where commodore says X, on Codex do Y" list.

The teammate contract gains Codex read-only variant lines: a read-only Codex teammate writes no files, has no `.proof`, and a Codex coordinator escalates a problem it can't move forward without an advisor. The `agent-teammates` and `commodore` descriptions and the README no longer say Claude Code is the only supported harness.
