# Sourced by the Codex driver's operations, with D set to the team directory and DRVDIR to this directory.
# PID in a session's state is the process-group leader of its latest turn: codex, or the `turn` wrapper for a read-only role.
STATE_VARS=(NAME THREAD PID PGID MODEL EFFORT RO WORKDIR EVENTS ERRLOG CXHOME STOPPED)
state_file() { print -r -- $D/codex-$1.state; }
state_save() {
  local f=$(state_file $THREAD) v
  { for v in $STATE_VARS; do print -r -- "$v=${(q)${(P)v}}"; done } > $f.tmp.$$ && mv $f.tmp.$$ $f
}
state_load() { local f=$(state_file $1); [[ -f $f ]] || return 1; local v; for v in $STATE_VARS; do typeset -g $v=; done; source $f; }
# turn_alive: checks args, never `comm` (the real binary hides behind shims), so a reused pid is never signalled
turn_alive() {
  [[ $PID == <-> && $PGID == $PID ]] || return 1
  local args pg
  args=$(ps -ww -o args= -p $PID 2>/dev/null); [[ $args == *codex* ]] || return 1
  pg=$(ps -o pgid= -p $PID 2>/dev/null); [[ ${pg//[[:space:]]/} == $PGID ]] || return 1
  [[ -n $EVENTS && $args == *"/turn $EVENTS "* ]] && return 0
  [[ $args == *" exec "* && ( ( -n $THREAD && $args == *$THREAD* ) || $args == *"teammate $NAME. Read"* ) ]]
}
rollout_of() { print -r -- $CXHOME/sessions/*/*/*/rollout-*-$THREAD.jsonl(NOm[1]); }
toml_str() { print -rn -- "\"${${1//\\/\\\\}//\"/\\\"}\""; }
# sandbox_args launch|resume: `exec resume` takes no -s, so a resumed turn passes it as -c config. --ignore-rules because
# an allow rule runs its command outside the sandbox, which would let a read-only role write.
sandbox_args() {
  SANDBOX=()
  if [[ $1 == launch ]]; then
    if [[ -n $RO ]]; then SANDBOX=(-s read-only --ignore-rules -o ${EVENTS%.events}.out)
    else SANDBOX=(-s workspace-write -c sandbox_workspace_write.network_access=true --add-dir $D/reports); fi
  elif [[ -n $RO ]]; then SANDBOX=(-c "sandbox_mode=$(toml_str read-only)" --ignore-rules -o ${EVENTS%.events}.out)
  else SANDBOX=(-c "sandbox_mode=$(toml_str workspace-write)" -c sandbox_workspace_write.network_access=true -c "sandbox_workspace_write.writable_roots=[$(toml_str $D/reports)]"); fi
}
# bg_start <workdir> <stdin-file> <events> <errlog> <command...>: starts it in a new session and sets BGPID.
# python's os.setsid, because setsid(1) doesn't exist on macOS.
bg_start() {
  local w=$1 in=$2 ev=$3 er=$4; shift 4
  { cd $w && exec python3 -c 'import os,sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])' "$@" } < $in >> $ev 2>> $er &!
  BGPID=$!
}
turn_cmd() {
  if [[ -n $RO ]]; then TURN=($DRVDIR/turn $EVENTS ${EVENTS%.events}.out $D/reports/$NAME.done $D/reports/$NAME.md codex "$@"); else TURN=(codex "$@"); fi
}
# turn_tree: sets TREE to "pid:pgid" pairs below the leader; codex runs each tool command in its own process group
turn_tree() {
  TREE=()
  local rows=(${(f)"$(ps -A -o pid=,ppid=,pgid= 2>/dev/null)"}) todo=($PID) seen=" $PID " p r f
  while (( $#todo )); do
    p=$todo[1]; todo[1]=()
    for r in $rows; do
      f=(${=r})
      [[ $f[2] == $p && $seen != *" $f[1] "* ]] && { seen+="$f[1] "; todo+=$f[1]; TREE+="$f[1]:$f[3]"; }
    done
  done
}
kill_group() {
  turn_alive || return 1
  turn_tree
  local t targets=(-$PGID)
  for t in $TREE; do [[ ${t#*:} == ${t%:*} ]] && targets+=(-${t%:*}) || targets+=(${t%:*}); done
  kill -TERM -- $targets 2>/dev/null
  local i=0 any
  while (( i++ < 50 )); do
    any=
    for t in $targets; do kill -0 -- $t 2>/dev/null && any=1; done
    [[ -z $any ]] && return 0
    /bin/sleep 0.1
  done
  kill -KILL -- $targets 2>/dev/null
  return 0
}
live_named() {
  local f id
  for f in $D/codex-*.state(N); do
    id=${${f:t}#codex-}
    ( state_load ${id%.state} && [[ $NAME == $1 && -z $STOPPED ]] && turn_alive ) && return 0
  done
  return 1
}
