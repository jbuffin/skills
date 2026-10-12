#!/bin/zsh
# usage: retask.sh <team-dir> <name> <message-file>
# Gives a registered teammate its next job through the driver's `send`, on a harness that declares SEND=script, then
# resets its watchdog clock like retasked.sh. On SEND=tool it sends nothing: use the harness's own tool, then retasked.sh.
# Exit codes: 0 sent and recorded; 4 the harness declares SEND=tool; 5 refused (usage, unregistered or closed teammate,
# missing or empty message file, no usable SEND= line in driver.env, or the driver has no send); send's own non-zero
# code when the driver's send fails (the driver's message is printed, the registry is untouched).
D=${1:A}; NAME=$2; MSG=${3:a}
[[ -z $1 || -z $NAME || -z $3 ]] && { sed -n 2,2p $0; exit 5; }
source ${0:A:h}/team-env.zsh
reg_open $NAME
[[ -s $MSG ]] || { echo "message file $MSG is missing or empty"; exit 5; }
DENV=$DRIVER/driver.env
[[ -f $DENV ]] || { echo "$DENV not found; cannot tell whether harness $HARNESS sends by script or by tool"; exit 5; }
SEND=$(awk -F= '/^SEND=/ {print $2; exit}' $DENV)
case $SEND in
  script) ;;
  tool) echo "harness $HARNESS declares SEND=tool: send $NAME its work through the harness's own tool (see references/harness-$HARNESS.md), then run retasked.sh $D $NAME"; exit 4 ;;
  *) echo "$DENV has no SEND=script or SEND=tool line"; exit 5 ;;
esac
drv send $D $ID $MSG; rc=$?
(( rc == 9 )) && exit 5
(( rc )) && { echo "send to $NAME (session $ID) failed with exit $rc; nothing recorded"; exit $rc; }
reg_retask $NAME
