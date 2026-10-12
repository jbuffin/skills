# Sourced by the Claude driver's operations.
# A session's transcript; its mtime moves with every message and tool call, so it doubles as a progress signal.
transcript_of() { [[ -n $1 ]] && print -r -- ${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects/*/$1*.jsonl(Nom[1]); }
# `claude --bg` output: strip colour codes, then read the id from its "backgrounded · <id> · <name>" line.
strip_ansi() { print -r -- "$1" | sed $'s/\x1b\\[[0-9;]*m//g'; }
bg_id() { print -r -- "$1" | awk '/^backgrounded/ {print $3; exit}'; }
# Does `claude agents --json` output $1 list a live session named $2?
live_named() { print -r -- "$1" | grep -q "\"name\": *\"${2//./\\.}\""; }
