#!/bin/zsh
# usage: watch-teammates.sh [--until-event <max-min>] <team-dir>
# Run it under the Monitor tool on Claude (re-arm when it expires), or with --until-event on Codex, which has no Monitor.
# Polls every 60 s, from the driver's session status and the team's .done markers. Emits one line per event:
#   DONE <name>              reports/<name>.done appeared or was touched
#   BLOCKED <name> <id>      its turn ended (or it's waiting on a prompt) with no new .done; twice running
#   STALL <name> <id> <min>  working, but its transcript hasn't changed for <min> (>= STALL_MIN) minutes
#   STALE <name> <id> <min>  still working 45, 90, … minutes after being (re-)tasked, with no new .done
#   GONE <name> <id> <state> its session stopped, failed or vanished without being closed
# BLOCKED, STALL and GONE each repeat at most every 10 minutes per teammate. STALL_MIN comes from team.env (default 10).
# --until-event <max-min> is one bounded call: it polls the same way, once a minute, and exits 0 right after the poll that
# printed an event, or after <max-min> polls with none, printing `WATCH timeout <max-min>`. Run it again to keep waiting.
# The BLOCKED counts and alert times persist in <team-dir>/.watch-state, so a rerun neither repeats a DONE nor resets the
# two-polls-in-a-row and 10-minute rules. Without the flag nothing changes and no state file is written.
BOUND=
if [[ $1 == --until-event ]]; then
  [[ $2 == <1-> ]] || { sed -n 2,14p $0; exit 5; }
  BOUND=$2; shift 2
fi
D=${1:A}
[[ -z $1 ]] && { sed -n 2,14p $0; exit 5; }
source ${0:A:h}/team-env.zsh
R=$D/reports
typeset -A seen blocked lastalert
# Reported marker mtimes persist across re-arms, so a marker touched between two watcher runs still emits DONE.
EVENTS=0
emit() { echo "$@"; EVENTS=$((EVENTS + 1)); }
SEEN=$D/.watch-seen; touch $SEEN
while read -r f m; do [[ -n $f ]] && seen[$f]=$m; done < $SEEN
# keep one line per marker so the file doesn't grow with every touch
for f in ${(k)seen}; do print -r -- "$f ${seen[$f]}"; done > $SEEN
STATE=$D/.watch-state
if [[ -n $BOUND && -f $STATE ]]; then
  while read -r kind k v; do
    [[ $k =~ '^[A-Za-z0-9._:-]+$' && $v == <-> ]] || continue
    case $kind in blocked) blocked[$k]=$v ;; alert) lastalert[$k]=$v ;; esac
  done < $STATE
fi
save_state() {
  [[ -n $BOUND ]] || return 0
  { for k in ${(k)blocked}; do print -r -- "blocked $k ${blocked[$k]}"; done
    for k in ${(k)lastalert}; do print -r -- "alert $k ${lastalert[$k]}"; done; } > $STATE
}
POLLS=0
while true; do
  for f in $R/*.done(N); do
    m=$(stat -f %m "$f"); [[ "${seen[$f]}" != "$m" ]] && { seen[$f]=$m; print -r -- "$f $m" >> $SEEN; emit "DONE ${${f:t}%.done}"; }
  done
  now=$(date -u +%s)
  states=$(drv status $D)
  rc=$?
  # the driver can't report status at all: say so and stop, rather than skip every poll silently
  (( rc == 9 )) && { echo "WATCH the $HARNESS driver has no status operation; the watchdog can't run"; exit 5; }
  # a failed or unreadable listing says nothing about the teammates; skip the session checks this poll
  if (( rc != 0 )); then
    [[ -n $BOUND ]] && { save_state; (( EVENTS )) && exit 0; (( ++POLLS >= BOUND )) && { echo "WATCH timeout $BOUND"; exit 0; }; }
    sleep 60; continue
  fi
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
    mt=$(print -r -- "$states" | awk -v i=$id '$1==i {print $4}'); quiet=0
    [[ -n $mt && $mt != - ]] && quiet=$(( (now - mt) / 60 ))
    ev=
    if [[ $st == stopped || $st == failed || $st == missing ]]; then ev="GONE $name $id $st"
    elif (( ${blocked[$name]:-0} >= 2 )); then ev="BLOCKED $name $id"
    elif [[ $st == working ]] && (( quiet >= STALL_MIN )); then ev="STALL $name $id $quiet"
    fi
    if [[ -n $ev ]] && (( now - ${lastalert[${name}:${ev%% *}]:-0} >= 600 )); then emit $ev; lastalert[${name}:${ev%% *}]=$now; fi
    # STALE fires once per 45 minutes since tasking, whatever else fired
    last=${lastalert[${name}:STALE]:-$started}
    if (( now - started >= 2700 && (now - started) / 2700 > (last - started) / 2700 )); then
      emit "STALE $name $id $(( (now - started) / 60 ))"; lastalert[${name}:STALE]=$now
    fi
  done
  if [[ -n $BOUND ]]; then
    save_state
    (( EVENTS )) && exit 0
    (( ++POLLS >= BOUND )) && { echo "WATCH timeout $BOUND"; exit 0; }
  fi
  sleep 60
done
