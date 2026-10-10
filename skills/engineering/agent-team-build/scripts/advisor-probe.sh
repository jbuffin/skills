#!/bin/zsh
# usage: advisor-probe.sh <team-dir> <model>
# Does the built-in advisor come on in a background session on <model>, paired with the run's ADVISOR? A session
# whose pairing is refused, or whose feature flag is off, starts without the advisor and prints no error, and there
# is no "advisor is on" flag to read. The one signal is an advisor call in the session's transcript, so this starts
# a real `claude --bg` session named advisor-probe-<model> (--model <model> --advisor $ADVISOR, in the first
# worktree in <team-dir>/worktrees.tsv, else $WORKTREES_DIR; never a checkout whose git top level is $REPO), tells
# it to consult the advisor once on a trivial question and stop, and reads its transcript (transcript_of, which
# honours CLAUDE_CONFIG_DIR) for up to ADVISOR_PROBE_TIMEOUT seconds (default 150). It retries once with a fresh
# session, always stops its sessions with `claude stop` (never `claude rm`), writes nothing to teammates.tsv, and
# prints one line: `ADVISOR ON <model>` or `ADVISOR OFF <model>: <reason>`. Exits 0 either way, 5 on bad arguments.
#
# Transcript signal (confirmed on a real session): the JSONL has a {"type":"server_tool_use",…,"name":"advisor",…}
# entry, then a {"type":"advisor_tool_result",…} entry (its content is redacted). A session whose pairing is refused
# has no advisor tool at all, so it never emits either. Matching is loose (grep, not a JSON parse), spaces allowed:
#   ON    a server_tool_use entry naming advisor, and an advisor_tool_result entry that isn't an error;
#         or the text "Advisor declined to advise"
#   OFF   "Advisor unavailable (<code>)", or an advisor_tool_result_error with an error_code: the reason is the code
# The prompt avoids those strings so it can't match itself. The session name is advisor-probe-<model> with characters
# outside letters, digits, '.', '_' and '-' (as in sonnet[1m]) replaced by '-'. Sourcing team-env.zsh creates an empty
# teammates.tsv and reports/ in a fresh team dir; this script removes them again if it created them and they're empty.
# Cost: about 15-30 s when the advisor is on, up to about 5 min when it's off (two attempts of ADVISOR_PROBE_TIMEOUT
# plus start). Stopped sessions leave nothing in `claude agents --json`, so a rerun is safe.
[[ -z $1 || -z $2 || -n $3 || ! -d $1 ]] && { sed -n 2,3p $0; exit 5; }
D=${1:A}; M=$2
HAD_REG=; HAD_REPORTS=; [[ -e $D/teammates.tsv ]] && HAD_REG=1; [[ -d $D/reports ]] && HAD_REPORTS=1
source ${0:A:h:h:h}/agent-teammates/scripts/team-env.zsh
NAME=advisor-probe-${M//[^A-Za-z0-9._-]/-}
TIMEOUT=${ADVISOR_PROBE_TIMEOUT:-150}
MARK=$D/$NAME.marker
ID=
stop_session() { [[ -n $ID ]] && claude stop $ID >/dev/null 2>&1; ID=; }
cleanup() {
  stop_session; rm -f $MARK
  [[ -z $HAD_REG && ! -s $REG ]] && rm -f $REG
  [[ -z $HAD_REPORTS ]] && rmdir $D/reports 2>/dev/null
}
trap cleanup EXIT
trap 'cleanup; exit 143' INT TERM HUP

# Cheap, checkable causes of a silent OFF.
hints() {
  local h=()
  [[ -n $CLAUDE_CODE_DISABLE_ADVISOR_TOOL ]] && h+="CLAUDE_CODE_DISABLE_ADVISOR_TOOL is set"
  [[ -n $DISABLE_TELEMETRY ]] && h+="DISABLE_TELEMETRY is set (the advisor needs feature-flag fetching)"
  [[ -n $CLAUDE_CODE_USE_BEDROCK ]] && h+="CLAUDE_CODE_USE_BEDROCK is set (the advisor needs the Anthropic API)"
  [[ -n $CLAUDE_CODE_USE_VERTEX ]] && h+="CLAUDE_CODE_USE_VERTEX is set (the advisor needs the Anthropic API)"
  [[ -n $ANTHROPIC_BASE_URL ]] && h+="ANTHROPIC_BASE_URL is set (the gateway must forward the advisor tool)"
  [[ $ADVISOR == fable ]] && h+="ADVISOR=fable may need the one-time usage-credits consent (/model fable)"
  (( $#h )) && print -r -- " (check: ${(j:; :)h})"
}
off() { print -r -- "ADVISOR OFF $M: $1$(hints)"; exit 0; }

# A directory to start in: trusted, and not the engineer's own checkout.
REPO_TOP=${${REPO:-}:A}
usable() { [[ -d $1 ]] || return 1; local top=$(git -C $1 rev-parse --show-toplevel 2>/dev/null); [[ -z $REPO_TOP || ${${top:-$1}:A} != $REPO_TOP ]]; }
W=
for p in ${(f)"$(awk '{print $3}' $D/worktrees.tsv 2>/dev/null)"}; do usable $p && { W=${p:A}; break; }; done
[[ -z $W ]] && usable ${WORKTREES_DIR:-} && W=${WORKTREES_DIR:A}
[[ -z $W ]] && off "probe session couldn't start (no trusted directory outside $REPO: add a worktree to worktrees.tsv or set WORKTREES_DIR)"

LIVE=$(claude agents --json 2>/dev/null) || off "probe session couldn't start (claude agents --json failed)"
print -r -- "$LIVE" | grep -q "\"name\": *\"${NAME//./\\.}\"" && off "a live session is already named $NAME; stop it with claude stop, then rerun"

PROMPT="You are a probe. Consult your advisor exactly once, on this question: is 17 a prime number? Then write the word done to $MARK and stop. Do nothing else."
# attempt -> sets RESULT to ON, OFF <reason>, UNAVAILABLE <code> or NONE, and stops its session. Not run in a command
# substitution, so ID stays visible to the traps.
attempt() {
  local out clean tp t=$SECONDS
  rm -f $MARK
  local ADV=(); [[ $ADVISOR != none ]] && ADV=(--advisor $ADVISOR)
  out=$(cd $W && claude --bg -n $NAME --model $M $ADV --permission-mode $PERMISSION_MODE "$PROMPT" 2>&1)
  clean=$(print -r -- "$out" | sed $'s/\x1b\\[[0-9;]*m//g')
  ID=$(print -r -- "$clean" | awk '/^backgrounded/ {print $3; exit}')
  if [[ -z $ID ]]; then
    RESULT="OFF probe session couldn't start ($(print -r -- "$clean" | grep -v '^warning: --bg manages the session id' | head -1))"; return
  fi
  while (( SECONDS - t < TIMEOUT )); do
    tp=$(transcript_of $ID)
    if [[ -n $tp && -f $tp ]]; then
      if grep -aqE 'Advisor unavailable \(|advisor_tool_result_error' $tp; then
        code=$(grep -aoE 'Advisor unavailable \([A-Za-z0-9_]+\)|"error_code": *"[A-Za-z0-9_]+"' $tp | head -1 | grep -oE '\([A-Za-z0-9_]+\)|"[A-Za-z0-9_]+"$' | tr -d '()"')
        RESULT="UNAVAILABLE ${code:-unknown error}"; stop_session; return
      fi
      if grep -aq 'Advisor declined to advise' $tp || { grep -aE '"type": *"server_tool_use"' $tp | grep -aqE '"name": *"advisor"' && grep -aqE '"type": *"advisor_tool_result"' $tp; }; then
        RESULT=ON; stop_session; return
      fi
    fi
    sleep 2
  done
  RESULT=NONE; stop_session
}
for n in 1 2; do
  attempt
  case $RESULT in
    ON) print -r -- "ADVISOR ON $M"; exit 0 ;;
    OFF\ *) off ${RESULT#OFF } ;;
    UNAVAILABLE\ *) off "advisor unavailable (${RESULT#UNAVAILABLE })" ;;
  esac
done
off "no advisor call seen"
