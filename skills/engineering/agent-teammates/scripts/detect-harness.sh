#!/bin/zsh
# usage: detect-harness.sh
# Prints the name of each harness this environment looks like, one per line: none when the run wasn't started from a
# supported harness, two or more when the signals disagree. Each driver adds its signal here.
# CODEX_THREAD_ID is exact: match no *CODEX* pattern, since cmux sets CMUX_CODEX_* in ordinary shells.
[[ $CLAUDECODE == 1 ]] && echo claude
[[ -n $CODEX_THREAD_ID ]] && echo codex
exit 0
