#!/bin/zsh
# usage: harness-available.sh <team-dir> <harness>
# Whether <harness> can start a teammate here, from its driver's `available` operation (the admiral driver's inside a ship).
# Exit 0: available, maybe with a WARN line; 1: not available, with one line of reason; 5: a bad call or harness name.
[[ $# -eq 2 && -d $1 && -n $2 ]] || { sed -n 2,4p $0; exit 5; }
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
