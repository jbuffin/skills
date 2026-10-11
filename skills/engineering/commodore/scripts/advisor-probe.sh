#!/bin/zsh
# usage: advisor-probe.sh <team-dir> <model>
# Prints `ADVISOR ON <model>` or `ADVISOR OFF <model>: <reason>` and exits 0 either way (5 on bad arguments).
# A refused advisor pairing or a disabled feature flag starts a session without the advisor and prints no error, so
# this starts a real `claude --bg` session on <model> with --advisor $ADVISOR, asks it to consult the advisor once,
# and reads its transcript for up to ADVISOR_PROBE_TIMEOUT seconds (default 150), retrying once with a fresh session.
# Transcript signal (confirmed on a real session): a {"type":"server_tool_use",…,"name":"advisor",…} entry, then a
# {"type":"advisor_tool_result",…} entry. "Advisor unavailable (<code>)" or an advisor_tool_result_error means OFF.
# Cost: about 15-30 s when the advisor is on, up to about 5 min when it's off. Sessions end with `claude stop`.
[[ -z $1 || -z $2 || -n $3 || ! -d $1 ]] && { sed -n 2,3p $0; exit 5; }
# The probe itself is the harness driver's advisor-probe operation; HARNESS comes from team.env (default claude).
HARNESS=$(source ${1:A}/team.env 2>/dev/null; print -r -- ${HARNESS:-claude})
DRIVER=${0:A:h:h:h}/agent-teammates/scripts/drivers/$HARNESS
[[ -x $DRIVER/advisor-probe ]] || { echo "ADVISOR n/a ($HARNESS)"; exit 0; }
exec $DRIVER/advisor-probe "$@"
