#!/bin/zsh
# usage: retasked.sh <team-dir> <name>
# Call right after sending a live teammate new work (SendMessage to its session name). Resets its watchdog clock so
# the previous .done marker no longer counts as reported.
D=${1:A}; NAME=$2
[[ -z $1 || -z $NAME ]] && { sed -n 2,4p $0; exit 5; }
source ${0:A:h}/team-env.zsh
ID=$(reg_field $NAME 2); V=$(reg_field $NAME 4); W=$(reg_field $NAME 5)
[[ -z $ID ]] && { echo "$NAME is not registered in $REG"; exit 5; }
[[ $(reg_field $NAME 3) == closed ]] && { echo "$NAME is closed; launch a new teammate instead"; exit 5; }
printf '%s %s %s %s %s\n' "$NAME" "$ID" "$(date -u +%s)" "${V:--}" "$W" >> $REG
echo "$NAME re-tasked (session $ID)"
