#!/bin/zsh
# usage: close-teammate.sh <team-dir> <name>...
# Stops each teammate's background session (`claude stop`), closes its viewer pane if it has one,
# and marks it closed in the registry. Uses `stop`, never `claude rm`, so worktrees the run created are left alone.
[[ $# -lt 2 ]] && { sed -n 2,4p $0; exit 5; }
D=${1:A}; shift
source ${0:A:h}/team-env.zsh
for n in "$@"; do
  ID=$(reg_field $n 2); V=$(reg_field $n 4); W=$(reg_field $n 5)
  [[ -z $ID ]] && { echo "$n not registered; skipping"; continue; }
  claude stop $ID >/dev/null 2>&1 && echo "stopped $n ($ID)" || echo "$n ($ID) was not running"
  case $V in
    surface:*) $CMUX close-surface --workspace $CMUX_WORKSPACE --surface $V >/dev/null 2>&1 ;;
    %*)        tmux kill-pane -t $V >/dev/null 2>&1 ;;
  esac
  printf '%s %s %s %s %s\n' "$n" "$ID" "closed" "-" "$W" >> $REG
done
