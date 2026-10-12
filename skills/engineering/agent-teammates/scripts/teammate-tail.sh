#!/bin/zsh
# usage: teammate-tail.sh <team-dir> <name|id> [n]
# Plain-text view of a teammate's last n (default 8) tool calls and its latest message, read from the session
# transcript. Use it instead of the harness's own log view, whose output is raw terminal frames.
D=${1:A}; W=$2; N=${3:-8}
[[ -z $1 || -z $W ]] && { sed -n 2,4p $0; exit 5; }
source ${0:A:h}/team-env.zsh
id=$(reg_field $W 2); [[ -z $id ]] && id=$W
drv tail $D $W $id $N; rc=$?
(( rc == 9 )) && exit 5
exit $rc
