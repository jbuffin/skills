# Sourced by the Copilot driver's operations. A session's state file is <team-dir>/copilot-<session-id> (key=value lines).
cp_state() { print -r -- $1/copilot-$2; }
cp_get() { [[ -f $1 ]] && awk -v k=$2 '{i=index($0,"="); if (substr($0,1,i-1)==k) v=substr($0,i+1)} END {print v}' $1; }
# cp_num: a writer teammate can write the state file, so no value from it reaches arithmetic without this
cp_num() { local v=$(cp_get $1 $2); [[ $v == <-> ]] && print -r -- $v; }
cp_put() { { grep -v "^$2=" $1 2>/dev/null; print -r -- "$2=$3"; } > $1.tmp && mv $1.tmp $1; }
cp_events() { print -r -- $HOME/.copilot/session-state/$1/events.jsonl; }
cp_alive() {
  local pid=$(cp_num $1 pid) pg=$(cp_num $1 pgid)
  [[ -n $pid ]] && kill -0 $pid 2>/dev/null && [[ $(ps -o pgid= -p $pid 2>/dev/null | tr -d ' ') == $pg ]]
}
CP_SCRIPTS=${${(%):-%x}:A:h:h:h}
# cp_extra_dirs <team.env>: reads team.env as data, never sourcing it, and keeps only existing absolute directories
cp_extra_dirs() {
  local k v
  CP_EXTRA=($CP_SCRIPTS)
  for k in PREFLIGHT_SCRIPTS TEAM_SCRIPTS; do
    v=$(cp_get $1 $k)
    [[ $v == /* && -d $v && ${CP_EXTRA[(Ie)$v]} == 0 ]] && CP_EXTRA+=($v)
  done
  return 0
}
# cp_flags <read-only: 0|1> <model|-> <add-dir|-> <session-id> [effort [extra-dir...]]: anything but 0 fails closed to read-only.
# The variadic flags come last, so the -p that follows them ends the list.
cp_flags() {
  local d
  CP_FLAGS=(--no-ask-user -s --session-id $4)
  [[ -n $2 && $2 != - ]] && CP_FLAGS+=(--model $2)
  [[ -n $5 ]] && CP_FLAGS+=(--reasoning-effort $5)
  [[ -n $3 && $3 != - ]] && CP_FLAGS+=(--add-dir $3)
  if [[ $1 != 0 ]]; then
    CP_FLAGS+=(--available-tools bash view glob grep --deny-tool=write --allow-tool
      'shell(git log)' 'shell(git show)' 'shell(git diff)' 'shell(git status)' 'shell(gh pr view)' 'shell(gh pr diff)' 'shell(gh issue view)')
  else
    for d in "${@:6}"; do [[ $d != "$3" ]] && CP_FLAGS+=(--add-dir $d); done
    CP_FLAGS+=(--available-tools bash view edit create glob grep --allow-all-tools --deny-tool
      'shell(git push:*)' 'shell(gh pr merge:*)' 'shell(gh pr create:*)' 'shell(gh api:*)' 'shell(gh issue:*)')
  fi
}
cp_uuid() { { uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid; } | tr 'A-Z' 'a-z'; }
# cp_report: only events after the last session.resume count, so a silent resumed turn doesn't reuse the old report
cp_report() {
  local m
  [[ -f $1 ]] && m=$(jq -rs '(([to_entries[] | select(.value.type == "session.resume") | .key] | last) // 0) as $i
    | [.[$i:][] | select(.type == "assistant.message" and ((.data.content // "") != ""))] | last | .data.content // empty' $1 2>/dev/null)
  [[ -z $m && -s $2 ]] && m=$(<$2)
  [[ -n $m ]] && print -r -- $m
}
# cp_supervise <team-dir> <session-id> <prompt>: runs one turn; a read-only session's final message becomes its report
cp_supervise() {
  local D=$1 id=$2 prompt=$3 f=$(cp_state $1 $2) rc msg
  local name=$(cp_get $f name) w=$(cp_get $f workdir) ro=$(cp_get $f ro)
  cp_extra_dirs $D/team.env
  cp_flags "$ro" "$(cp_get $f model)" $D $id "$(cp_get $f effort)" $CP_EXTRA
  cd $w || exit 1
  copilot $CP_FLAGS -p $prompt < /dev/null > $f.out 2> $f.err
  rc=$?
  if [[ $ro != 0 && $rc == 0 && $name =~ '^[A-Za-z0-9._-]+$' && $name != .* ]]; then
    msg=$(cp_report $(cp_events $id) $f.out)
    if [[ -n $msg ]]; then
      print -r -- $msg > $D/reports/$name.md.tmp && mv $D/reports/$name.md.tmp $D/reports/$name.md && : > $D/reports/$name.done
    fi
  fi
  print -r -- $rc > $f.rc.tmp && mv $f.rc.tmp $f.rc
  exit $rc
}
# cp_start <team-dir> <session-id> <prompt> [resume]: no inherited stdout, so a caller capturing ours never waits on the turn
cp_start() {
  local f=$(cp_state $1 $2) i
  cp_put $f stopped ''
  rm -f $f.rc
  perl -e 'setpgrp(0, 0); exec @ARGV' /bin/zsh -f -c 'source "$1" && shift && cp_supervise "$@"' zsh ${${(%):-%x}:A} $1 $2 $3 < /dev/null > /dev/null 2>&1 &!
  local pid=$!
  cp_put $f pid $pid
  cp_put $f pgid $pid
  cp_put $f started $(date -u +%s)
  [[ -n $4 ]] && cp_put $f resumed $(date -u +%s)
  for i in 1 2 3 4 5 6 7 8 9 10; do
    [[ -f $f.rc ]] && break
    /bin/sleep 0.1
  done
  if [[ -f $f.rc ]]; then [[ $(<$f.rc) == 0 ]] && return 0
  else cp_alive $f && return 0
  fi
  echo "copilot exited at once${$(<$f.rc 2>/dev/null):+ with $(<$f.rc)}: $(head -1 $f.err 2>/dev/null)"
  return 1
}
