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
# Assumption, to confirm on a real session: the transcript is JSONL, and the advisor shows up as
#   ON    a line matching "name": "advisor" (the server tool call) followed by a line matching advisor_tool_result
#         that isn't an error, or the text "Advisor declined to advise"
#   OFF   "Advisor unavailable (<code>)", or an advisor_tool_result error with an error_code: the reason is the code
# Matching is loose (grep, not a JSON parse). The prompt avoids those strings so it can't match itself.
[[ -z $1 || -z $2 || -n $3 || ! -d $1 ]] && { sed -n 2,3p $0; exit 5; }
D=${1:A}; M=$2
source ${0:A:h:h:h}/agent-teammates/scripts/team-env.zsh
valid_name $M
NAME=advisor-probe-$M
TIMEOUT=${ADVISOR_PROBE_TIMEOUT:-150}
MARK=$D/$NAME.marker
ID=
stop_session() { [[ -n $ID ]] && claude stop $ID >/dev/null 2>&1; ID=; }
trap 'stop_session; rm -f $MARK' EXIT

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
# attempt -> prints ON, or OFF <reason>
_attempt() {
  local out clean tp n=0 t=$SECONDS
  rm -f $MARK
  local ADV=(); [[ $ADVISOR != none ]] && ADV=(--advisor $ADVISOR)
  out=$(cd $W && claude --bg -n $NAME --model $M $ADV --permission-mode $PERMISSION_MODE "$PROMPT" 2>&1)
  clean=$(print -r -- "$out" | sed $'s/\x1b\\[[0-9;]*m//g')
  ID=$(print -r -- "$clean" | awk '/^backgrounded/ {print $3; exit}')
  if [[ -z $ID ]]; then
    print -r -- "OFF probe session couldn't start ($(print -r -- "$clean" | grep -v '^warning: --bg manages the session id' | head -1))"; return
  fi
  while (( SECONDS - t < TIMEOUT )); do
    tp=$(transcript_of $ID)
    if [[ -n $tp && -f $tp ]]; then
      if grep -aqE 'Advisor unavailable \(|advisor_tool_result_error' $tp; then
        code=$(grep -aoE 'Advisor unavailable \([A-Za-z0-9_]+\)|"error_code": *"[A-Za-z0-9_]+"' $tp | head -1 | grep -oE '\([A-Za-z0-9_]+\)|"[A-Za-z0-9_]+"$' | tr -d '()"')
        print -r -- "UNAVAILABLE ${code:-unknown error}"; return
      fi
      if grep -aq 'Advisor declined to advise' $tp || { grep -aqE '"name": *"advisor"' $tp && grep -aq 'advisor_tool_result' $tp; }; then
        print -r -- "ON"; return
      fi
    fi
    sleep 2
  done
  print -r -- "NONE"
}
# The session id lives in the command substitution, so the session is stopped there.
attempt() { _attempt; stop_session; }
for n in 1 2; do
  R=$(attempt)
  case $R in
    ON) print -r -- "ADVISOR ON $M"; exit 0 ;;
    OFF\ *) off ${R#OFF } ;;
    UNAVAILABLE\ *) off "advisor unavailable (${R#UNAVAILABLE })" ;;
  esac
done
off "no advisor call seen"
