#!/bin/zsh
# usage: detect-harness.sh
# Prints the name of each harness this environment looks like, one per line: none when the run wasn't started from a
# supported harness, two or more when the signals disagree. Each driver adds its signal here.
[[ $CLAUDECODE == 1 ]] && echo claude
exit 0
