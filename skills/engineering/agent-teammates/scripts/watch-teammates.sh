#!/bin/zsh
# usage: watch-teammates.sh <team-dir>     (run under the Monitor tool; re-arm when it expires)
# Polls every 60 s, from `claude agents --json` and the team's .done markers. Emits one line per event:
#   DONE <name>              reports/<name>.done appeared or was touched
#   BLOCKED <name> <id>      its turn ended (or it's waiting on a prompt) with no new .done; twice running
#   STALL <name> <id> <min>  working, but its transcript hasn't changed for <min> (>= STALL_MIN) minutes
#   STALE <name> <id> <min>  still working 45, 90, … minutes after being (re-)tasked, with no new .done
#   GONE <name> <id> <state> its session stopped, failed or vanished without being closed
# BLOCKED, STALL and GONE each repeat at most every 10 minutes per teammate. STALL_MIN comes from team.env (default 10).
D=${1:A}
[[ -z $1 ]] && { sed -n 2,9p $0; exit 5; }
source ${0:A:h}/team-env.zsh
R=$D/reports
typeset -A seen blocked lastalert
# Reported marker mtimes persist across re-arms, so a marker touched between two watcher runs still emits DONE.
SEEN=$D/.watch-seen; touch $SEEN
while read -r f m; do [[ -n $f ]] && seen[$f]=$m; done < $SEEN
# keep one line per marker so the file doesn't grow with every touch
for f in ${(k)seen}; do print -r -- "$f ${seen[$f]}"; done > $SEEN
while true; do
  for f in $R/*.done(N); do
    m=$(stat -f %m "$f"); [[ "${seen[$f]}" != "$m" ]] && { seen[$f]=$m; print -r -- "$f $m" >> $SEEN; echo "DONE ${${f:t}%.done}"; }
  done
  now=$(date -u +%s)
  states=$(claude agents --json --all 2>/dev/null | python3 -c 'import json,sys
try: rows=json.load(sys.stdin)
except Exception: sys.exit(3)
for r in rows: print(r.get("id",""), r.get("status") or "-", r.get("state") or "-")')
  # a failed or unreadable listing says nothing about the teammates; skip the session checks this poll
  (( $? == 0 )) || { sleep 60; continue; }
  # latest registry row per teammate; a "closed" row ends the watch for that name
  awk '{last[$1]=$0} END {for (n in last) print last[n]}' $REG | while read -r name id started viewer workdir; do
    [[ -z $name || $started == closed ]] && continue
    marker=$R/$name.done
    if [[ -f $marker && $(stat -f %m $marker) -ge $started ]]; then blocked[$name]=0; continue; fi
    line=$(print -r -- "$states" | awk -v i=$id '$1==i {print $3}')
    st=${line:-missing}
    case $st in
      blocked|done) blocked[$name]=$(( ${blocked[$name]:-0} + 1 )) ;;
      *) blocked[$name]=0 ;;
    esac
    tr=$(transcript_of $id); quiet=0
    [[ -n $tr ]] && quiet=$(( (now - $(stat -f %m $tr)) / 60 ))
    ev=
    if [[ $st == stopped || $st == failed || $st == missing ]]; then ev="GONE $name $id $st"
    elif (( ${blocked[$name]:-0} >= 2 )); then ev="BLOCKED $name $id"
    elif [[ $st == working ]] && (( quiet >= STALL_MIN )); then ev="STALL $name $id $quiet"
    fi
    if [[ -n $ev ]] && (( now - ${lastalert[${name}:${ev%% *}]:-0} >= 600 )); then echo $ev; lastalert[${name}:${ev%% *}]=$now; fi
    # STALE fires once per 45 minutes since tasking, whatever else fired
    last=${lastalert[${name}:STALE]:-$started}
    if (( now - started >= 2700 && (now - started) / 2700 > (last - started) / 2700 )); then
      echo "STALE $name $id $(( (now - started) / 60 ))"; lastalert[${name}:STALE]=$now
    fi
  done
  sleep 60
done
