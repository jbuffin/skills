#!/bin/zsh
# usage: advisor-probe.sh <team-dir> <model>
# Prints `ADVISOR ON <model>` or `ADVISOR OFF <model>: <reason>` and exits 0 either way (5 on bad arguments).
# Runs the advisor-probe operation of the run's harness driver (HARNESS in team.env, default claude); see the
# driver's header in agent-teammates/scripts/drivers/<harness>/ for how it probes and what it costs. A driver
# without the operation prints `ADVISOR n/a (<harness>)`.
[[ -z $1 || -z $2 || -n $3 || ! -d $1 ]] && { sed -n 2,3p $0; exit 5; }
# HARNESS comes from team.env alone, never from the caller's environment.
HARNESS=$(unset HARNESS; source ${1:A}/team.env 2>/dev/null; print -r -- ${HARNESS:-claude})
[[ $HARNESS =~ '^[a-z0-9-]+$' ]] || { echo "invalid HARNESS '$HARNESS' in ${1:A}/team.env: use lowercase letters, digits and '-'"; exit 5; }
DRIVER=${0:A:h:h:h}/agent-teammates/scripts/drivers/$HARNESS
[[ -x $DRIVER/advisor-probe ]] || { echo "ADVISOR n/a ($HARNESS)"; exit 0; }
exec $DRIVER/advisor-probe "$@"
