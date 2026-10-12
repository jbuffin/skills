# Sourced by the Copilot driver's operations. A session's state file is <team-dir>/copilot-<session-id> (key=value lines).
cp_state() { print -r -- $1/copilot-$2; }
cp_get() { [[ -f $1 ]] && awk -v k=$2 '{i=index($0,"="); if (substr($0,1,i-1)==k) v=substr($0,i+1)} END {print v}' $1; }
cp_put() { { grep -v "^$2=" $1 2>/dev/null; print -r -- "$2=$3"; } > $1.tmp && mv $1.tmp $1; }
# The session's events.jsonl; its mtime moves with every event, so it doubles as a progress signal.
cp_events() { print -r -- $HOME/.copilot/session-state/$1/events.jsonl; }
# Is the process this state file recorded still running (and still the process group it started)?
cp_alive() {
  local pid=$(cp_get $1 pid) pg=$(cp_get $1 pgid)
  [[ -n $pid ]] && kill -0 $pid 2>/dev/null && [[ $(ps -o pgid= -p $pid 2>/dev/null | tr -d ' ') == $pg ]]
}
# cp_flags <read-only: 0|1> <model|-> <add-dir|-> <session-id>: sets CP_FLAGS, the flags shared by every run.
# The variadic flags (--available-tools, --allow-tool, --deny-tool) come last; -p follows them, so it ends the list.
cp_flags() {
  CP_FLAGS=(--no-ask-user -s --session-id $4)
  [[ -n $2 && $2 != - ]] && CP_FLAGS+=(--model $2)
  [[ -n $3 && $3 != - ]] && CP_FLAGS+=(--add-dir $3)
  if [[ $1 == 1 ]]; then
    CP_FLAGS+=(--available-tools bash view glob grep --deny-tool=write --allow-tool
      'shell(git log)' 'shell(git show)' 'shell(git diff)' 'shell(git status)' 'shell(gh pr view)' 'shell(gh pr diff)' 'shell(gh issue view)')
  else
    CP_FLAGS+=(--available-tools bash view edit create glob grep --allow-all-tools --deny-tool
      'shell(git push:*)' 'shell(gh pr merge:*)' 'shell(gh pr create:*)' 'shell(gh api:*)' 'shell(gh issue:*)')
  fi
}
cp_uuid() { { uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid; } | tr 'A-Z' 'a-z'; }
# cp_report <events.jsonl> <stdout-file>: the final message of the latest run, on stdout; nothing if it has none.
# Only events after the last session.resume count, so a resumed turn that said nothing doesn't reuse the old report.
cp_report() {
  local m
  [[ -f $1 ]] && m=$(jq -rs '(([to_entries[] | select(.value.type == "session.resume") | .key] | last) // 0) as $i
    | [.[$i:][] | select(.type == "assistant.message" and ((.data.content // "") != ""))] | last | .data.content // empty' $1 2>/dev/null)
  [[ -z $m && -s $2 ]] && m=$(<$2)
  [[ -n $m ]] && print -r -- $m
}
# cp_supervise <team-dir> <session-id> <prompt>: runs in its own process group, started by cp_start. Runs one turn,
# then, for a read-only session, writes reports/<name>.md and then reports/<name>.done from the final message.
cp_supervise() {
  local D=$1 id=$2 prompt=$3 f=$(cp_state $1 $2) rc msg
  local name=$(cp_get $f name) w=$(cp_get $f workdir) ro=$(cp_get $f ro)
  cp_flags $ro "$(cp_get $f model)" $D $id
  cd $w || exit 1
  copilot $CP_FLAGS -p $prompt < /dev/null > $f.out 2> $f.err
  rc=$?
  if [[ $ro == 1 ]]; then
    msg=$(cp_report $(cp_events $id) $f.out)
    if [[ -n $msg ]]; then
      print -r -- $msg > $D/reports/$name.md.tmp && mv $D/reports/$name.md.tmp $D/reports/$name.md && : > $D/reports/$name.done
    fi
  fi
  print -r -- $rc > $f.rc
  exit $rc
}
# cp_start <team-dir> <session-id> <prompt> [resume]: starts the turn in the background, in its own process group, with
# no stdin and no inherited stdout, so a caller that captures our output never waits on it. Records pid and pgid.
# Waits up to a second; returns 1, printing why, if the process died or exited non-zero in that time.
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
