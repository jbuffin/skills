#!/bin/zsh
# usage: retask.sh <team-dir> <name> <message-file>
# Sends a registered teammate its next job through its driver's `send` and resets its watchdog clock (SEND=script harnesses).
# Exit 0: sent; 4: the harness declares SEND=tool (use its own tool, then retasked.sh); 5: refused; else send's own code.
D=${1:A}; NAME=$2; MSG=${3:a}
[[ -z $1 || -z $NAME || -z $3 ]] && { sed -n 2,4p $0; exit 5; }
source ${0:A:h}/team-env.zsh
reg_open $NAME
[[ -s $MSG ]] || { echo "message file $MSG is missing or empty"; exit 5; }
DENV=$DRIVER/driver.env
[[ -f $DENV ]] || { echo "$DENV not found; cannot tell whether harness $TH sends by script or by tool"; exit 5; }
SEND=$(awk -F= '/^SEND=/ {print $2; exit}' $DENV)
case $SEND in
  script) ;;
  tool) echo "harness $TH declares SEND=tool: send $NAME its work through the harness's own tool (see references/harness-$TH.md), then run retasked.sh $D $NAME"; exit 4 ;;
  *) echo "$DENV has no SEND=script or SEND=tool line"; exit 5 ;;
esac
drv send $D $ID $MSG; rc=$?
(( rc == 9 )) && exit 5
(( rc )) && { echo "send to $NAME (session $ID) failed with exit $rc; nothing recorded"; exit $rc; }
reg_retask $NAME
