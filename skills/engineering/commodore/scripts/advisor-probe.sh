#!/bin/zsh
# usage: advisor-probe.sh <team-dir> <model>     runs the advisor-probe of the run's harness driver
# Prints `ADVISOR ON <model>`, `ADVISOR OFF <model>: <reason>`, `ADVISOR SAME-FAMILY <model>` (same family as ADVISOR:
# no probe) or `ADVISOR n/a (<harness>)`, and exits 0 (5 on bad arguments).
[[ -z $1 || -z $2 || -n $3 || ! -d $1 ]] && { sed -n 2,4p $0; exit 5; }
# HARNESS comes from team.env alone, never from the caller's environment.
HARNESS=$(unset HARNESS; source ${1:A}/team.env 2>/dev/null; print -r -- ${HARNESS:-claude})
[[ $HARNESS =~ '^[a-z0-9-]+$' ]] || { echo "invalid HARNESS '$HARNESS' in ${1:A}/team.env: use lowercase letters, digits and '-'"; exit 5; }
DRIVER=${0:A:h:h:h}/agent-teammates/scripts/drivers/$HARNESS
[[ -x $DRIVER/advisor-probe ]] || { echo "ADVISOR n/a ($HARNESS)"; exit 0; }
exec $DRIVER/advisor-probe "$@"
