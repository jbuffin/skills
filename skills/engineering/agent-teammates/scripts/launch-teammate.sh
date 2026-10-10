#!/bin/zsh
# usage: launch-teammate.sh [--read-only] [--model <model>] [--role <role>] <team-dir> <name> <workdir|unit> [prompt-file]
# Starts a teammate as a Claude Code background session (`claude --bg`) named <name>, in <workdir>, told to read
# [prompt-file] (default <team-dir>/prompts/<name>.md). Registers "<name> <id> <epoch> <viewer|-> <workdir>"
# in <team-dir>/teammates.tsv. <unit> is looked up in <team-dir>/worktrees.tsv ("unit branch path") when it isn't a
# directory. With VIEWER=cmux|tmux in team.env, also opens a pane attached to it (closing the pane never stops it).
# Model: --model <model>, else with --role <role> the MODEL_<ROLE> from team.env (<ROLE> is the role uppercased, '-' as
# '_'; unset or empty exits 5), else MODEL. With REQUIRE_ROLE=1 in team.env, a launch with neither flag exits 5.
# --read-only denies the file-editing tools inside <workdir> (a reviewer, a brief checker); it can still write its
# report in <team-dir>. Bash isn't covered, so it's a guard against slips, not a sandbox.
# Exit 2 when a background session can't be started: run the teammate as an in-process subagent instead.
SELF=${0:A}
usage() { sed -n 2,11p $SELF; exit 5; }
RO=; MODEL_OPT=; ROLE=
while [[ $1 == --* ]]; do
  case $1 in
    --read-only) RO=1; shift ;;
    --model) [[ -n $2 && $2 != -* ]] || usage; MODEL_OPT=$2; shift 2 ;;
    --role) [[ -n $2 && $2 != -* ]] || usage; ROLE=$2; shift 2 ;;
    *) usage ;;
  esac
done
[[ -z $1 || -z $2 || -z $3 ]] && usage
D=${1:A}; NAME=$2; W=$3; P=${${4:-$1/prompts/$2.md}:A}
source ${0:A:h}/team-env.zsh
valid_name $NAME
# Choose the model before anything else, so a refused launch never calls claude.
if [[ -n $ROLE ]]; then
  valid_name $ROLE
  ROLE_VAR=MODEL_${${(U)ROLE}//[-.]/_}
fi
if [[ -n $MODEL_OPT ]]; then
  CHOSEN=$MODEL_OPT
elif [[ -n $ROLE ]]; then
  CHOSEN=${(P)ROLE_VAR}
  [[ -z $CHOSEN ]] && { echo "$ROLE_VAR is unset or empty in $D/team.env; set it (or pass --model) before launching $NAME with --role $ROLE"; exit 5; }
else
  [[ $REQUIRE_ROLE == 1 ]] && { echo "REQUIRE_ROLE=1 in $D/team.env: launch $NAME with --role <role> or --model <model>"; exit 5; }
  CHOSEN=$MODEL
fi
if [[ ! -d $W ]]; then
  W=$(awk -v u=$W '$1==u {print $3}' $D/worktrees.tsv 2>/dev/null | tail -1)
  [[ -z $W ]] && { echo "no directory or registered worktree for '$3'"; exit 5; }
fi
W=${W:A}
# Anywhere inside the engineer's checkout counts, not only its top directory; a worktree has its own top level.
TOP=$(git -C $W rev-parse --show-toplevel 2>/dev/null)
[[ -n $REPO && ${${TOP:-$W}:A} == ${REPO:A} ]] && { echo "refusing to start $NAME in the repository's own checkout ($REPO); give it a worktree"; exit 5; }
[[ -f $P ]] || { echo "missing prompt file $P"; exit 5; }
LIVE=$(claude agents --json 2>/dev/null) || { echo "couldn't list live sessions (claude agents --json failed); retry before launching $NAME"; exit 1; }
print -r -- "$LIVE" | grep -q "\"name\": *\"${NAME//./\\.}\"" && {
  echo "a live session is already named $NAME; close it first or pick another name"; exit 5; }

# --disallowedTools takes several values, so it goes before another flag, never right before the prompt.
DENY=(); [[ -n $RO ]] && DENY=(--disallowedTools "Edit(/$W/**)" "NotebookEdit(/$W/**)")
OUT=$(cd $W && claude --bg -n $NAME $DENY --model $CHOSEN --permission-mode $PERMISSION_MODE \
  "You are teammate $NAME. Read $P and do exactly what it says." 2>&1)
RC=$?
CLEAN=$(print -r -- "$OUT" | sed $'s/\x1b\\[[0-9;]*m//g')
ID=$(print -r -- "$CLEAN" | awk '/^backgrounded/ {print $3; exit}')
# Started, but the id didn't parse: a session may be running, so don't fall back to a second, in-process copy.
[[ $RC == 0 && -z $ID ]] && { print -r -- "$CLEAN" | head -5; echo "claude --bg succeeded but printed no session id; find $NAME in claude agents before relaunching"; exit 1; }
if [[ $RC != 0 ]]; then
  print -r -- "$CLEAN" | grep -v '^warning: --bg manages the session id' | head -5
  [[ $CLEAN == *"not trusted"* ]] && echo "the folder isn't trusted: run \`claude\` once in the repository and accept the prompt (worktrees inside it inherit trust)"
  echo "NO_BG: run $NAME as an in-process subagent with model=$CHOSEN, working in $W${RO:+, read-only (no edits in $W)}, task: read $P"; exit 2
fi

VREF=
case $VIEWER in
  cmux) if [[ -x $CMUX && -n $CMUX_WORKSPACE ]]; then
          T=(--workspace $CMUX_WORKSPACE); [[ -n $CMUX_SURFACE ]] && T+=(--surface $CMUX_SURFACE)
          VREF=$($CMUX new-split right $T --focus false --command "claude attach $ID" 2>/dev/null | grep -o 'surface:[0-9A-Za-z-]*' | head -1)
        fi ;;
  tmux) [[ -n $TMUX ]] && VREF=$(tmux split-window -d -h -P -F '#{pane_id}' "claude attach $ID" 2>/dev/null) ;;
esac
printf '%s %s %s %s %s\n' "$NAME" "$ID" "$(date -u +%s)" "${VREF:--}" "$W" >> $REG
echo "launched $NAME as background session $ID in $W${RO:+ (read-only)}${VREF:+ (viewer $VREF)}"
echo "  watch: claude agents   ·   attach: claude attach $ID   ·   output: claude logs $ID"
