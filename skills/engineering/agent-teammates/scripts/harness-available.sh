#!/bin/zsh
# usage: harness-available.sh <team-dir> <harness>
# Whether <harness> can start a teammate here, from the harness driver's `available` operation (the admiral driver's inside a ship).
# Exit 0: available, with an optional WARN line on stdout; 1: not available, one line of reason on stdout; 5: a bad call or a bad
# harness name. A driver with no `available` counts as available (WARN  harness <h> has no available operation). A harness
# whose driver can't message a teammate of its own harness from this lead (SEND=tool outside Admiral) is not available either.
# Starts no session. Writes only what team-env.zsh creates in the team dir.
[[ $# -eq 2 && -d $1 && -n $2 ]] || { sed -n 2,3p $0; exit 5; }
D=${1:A}; export TEAMMATE_HARNESS=$2
source ${0:A:h}/team-env.zsh
# A lead can only re-task a SEND=tool teammate (Claude's SendMessage) from the same harness, or from inside Admiral.
if [[ $TH != $HARNESS && $DRIVER != */drivers/admiral ]] && [[ $(awk -F= '/^SEND=/ {print $2; exit}' $DRIVER/driver.env 2>/dev/null) == tool ]]; then
  echo "a $HARNESS lead can't message a $TH teammate outside Admiral"
  exit 1
fi
drv available $D; rc=$?
(( rc == 9 )) && { echo "WARN  harness $TH has no available operation"; exit 0; }
exit $rc
