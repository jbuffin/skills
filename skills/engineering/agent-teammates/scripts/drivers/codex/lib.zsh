# Sourced by the Codex driver's operations, with D set to the team directory and DRVDIR to this directory.
# A session's state is <team-dir>/codex-<thread-id>.state: zsh assignments for NAME THREAD PID PGID MODEL EFFORT RO
# WORKDIR EVENTS ERRLOG PERM CXHOME STOPPED. PID is the process-group leader of the session's latest turn (codex itself
# for a writer, the `turn` wrapper for a read-only role); PGID equals it. EVENTS is the --json log of every turn.
STATE_VARS=(NAME THREAD PID PGID MODEL EFFORT RO WORKDIR EVENTS ERRLOG PERM CXHOME STOPPED)
state_file() { print -r -- $D/codex-$1.state; }
state_save() {
  local f=$(state_file $THREAD) v
  { for v in $STATE_VARS; do print -r -- "$v=${(q)${(P)v}}"; done } > $f.tmp.$$ && mv $f.tmp.$$ $f
}
# state_load <thread-id>: loads the session's state into the shell's variables; 1 when there is none.
state_load() { local f=$(state_file $1); [[ -f $f ]] || return 1; local v; for v in $STATE_VARS; do typeset -g $v=; done; source $f; }
# turn_alive: is the recorded process still this session's turn? The pid must lead the recorded process group and its
# args (`ps -o args=`, never `comm`: the real binary hides behind shims) must name codex and this session, so a reused
# pid is never reported working or signalled.
turn_alive() {
  [[ $PID == <-> && $PGID == $PID ]] || return 1
  local args pg
  args=$(ps -ww -o args= -p $PID 2>/dev/null); [[ $args == *codex* ]] || return 1
  pg=$(ps -o pgid= -p $PID 2>/dev/null); [[ ${pg//[[:space:]]/} == $PGID ]] || return 1
  [[ ( -n $THREAD && $args == *$THREAD* ) || ( -n $EVENTS && $args == *$EVENTS* ) || $args == *"teammate $NAME. Read"* ]]
}
# The rollout codex writes for the thread; its mtime moves with every event of a turn.
rollout_of() { print -r -- $CXHOME/sessions/*/*/*/rollout-*-$THREAD.jsonl(NOm[1]); }
# toml_str <value>: a TOML basic string, for -c values.
toml_str() { print -rn -- "\"${${1//\\/\\\\}//\"/\\\"}\""; }
# sandbox_args launch|resume: sets SANDBOX to codex's sandbox flags for the role (RO, D, PERM are set). `exec resume` takes
# no -s, so a resumed turn passes the same choice as -c config.
sandbox_args() {
  SANDBOX=()
  if [[ $1 == launch ]]; then
    if [[ -n $RO ]]; then SANDBOX=(-s read-only -o $D/reports/$NAME.md)
    else SANDBOX=(-s workspace-write -c sandbox_workspace_write.network_access=true --add-dir $D/reports); fi
  elif [[ -n $RO ]]; then SANDBOX=(-c "sandbox_mode=$(toml_str read-only)" -o $D/reports/$NAME.md)
  else SANDBOX=(-c "sandbox_mode=$(toml_str workspace-write)" -c sandbox_workspace_write.network_access=true -c "sandbox_workspace_write.writable_roots=[$(toml_str $D/reports)]"); fi
}
# bg_start <workdir> <stdin-file> <events> <errlog> <command...>: starts the command in the background in a new session
# (so its own process group, whose leader execs the command), stdin from <stdin-file>, stdout appended to <events> and
# stderr to <errlog>, never inheriting the caller's. Sets BGPID. Not setsid(1): it doesn't exist on macOS.
bg_start() {
  local w=$1 in=$2 ev=$3 er=$4; shift 4
  { cd $w && exec python3 -c 'import os,sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])' "$@" } < $in >> $ev 2>> $er &!
  BGPID=$!
}
# the read-only wrapper and the markers
turn_cmd() { # turn_cmd <codex args...>: sets TURN to the command for the role: codex itself, or for a read-only role the wrapper around it
  if [[ -n $RO ]]; then TURN=($DRVDIR/turn $EVENTS $D/reports/$NAME.done $D/reports/$NAME.md codex "$@"); else TURN=(codex "$@"); fi
}
# kill_group: TERM, then KILL, the recorded process group, only when the leader still is this session's turn.
kill_group() {
  turn_alive || return 1
  kill -TERM -- -$PGID 2>/dev/null
  local i=0; while kill -0 -- -$PGID 2>/dev/null && (( i++ < 50 )); do /bin/sleep 0.1; done
  kill -0 -- -$PGID 2>/dev/null && kill -KILL -- -$PGID 2>/dev/null
  return 0
}
# live_named <name>: 0 when a session of this driver with that name has a turn running.
live_named() {
  local f id
  for f in $D/codex-*.state(N); do
    id=${${f:t}#codex-}
    ( state_load ${id%.state} && [[ $NAME == $1 && -z $STOPPED ]] && turn_alive ) && return 0
  done
  return 1
}
