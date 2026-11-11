#!/bin/zsh
# usage: detect-harness.sh
# CODEX_THREAD_ID is exact: match no *CODEX* pattern, since cmux sets CMUX_CODEX_* in ordinary shells.
[[ $CLAUDECODE == 1 ]] && echo claude
[[ -n $CODEX_THREAD_ID ]] && echo codex
# COPILOT_CLI=1 is exact. Copilot passes its parent's environment through, so one started from a Claude Code shell
# prints both lines; no signal wins.
[[ $COPILOT_CLI == 1 ]] && echo copilot
exit 0
