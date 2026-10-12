#!/bin/zsh
# usage: retasked.sh <team-dir> <name>
# Call right after sending a live teammate new work (SendMessage to its session name). Resets its watchdog clock so
# the previous .done marker no longer counts as reported.
D=${1:A}; NAME=$2
[[ -z $1 || -z $NAME ]] && { sed -n 2,4p $0; exit 5; }
source ${0:A:h}/team-env.zsh
reg_open $NAME
reg_retask $NAME
