#!/bin/zsh
# usage: launch-teammate.sh [--read-only] [--model <model>] [--role <role>] <team-dir> <name> <workdir|unit> [prompt-file]
# Starts a teammate as a Claude Code background session (`claude --bg`) named <name>, in <workdir>, told to read
# [prompt-file] (default <team-dir>/prompts/<name>.md). Registers "<name> <id> <epoch> <viewer|-> <workdir>"
# in <team-dir>/teammates.tsv. <unit> is looked up in <team-dir>/worktrees.tsv ("unit branch path") when it isn't a
# directory. With VIEWER=cmux|tmux in team.env, also opens a pane attached to it (closing the pane never stops it).
# Model: --model <model>, else with --role <role> the MODEL_<ROLE> from team.env (<ROLE> is the role uppercased, '-' and
# '.' as '_'; unset or empty exits 5), else MODEL. With REQUIRE_ROLE=1 in team.env, a launch with neither flag exits 5.
# --read-only denies the file-editing tools inside <workdir> (a reviewer, a brief checker); it can still write its
# report in <team-dir>. Bash isn't covered, so it's a guard against slips, not a sandbox.
# Every launch passes --advisor $ADVISOR (default opus) unless team.env sets ADVISOR=none.
# Exit 2 when a background session can't be started: run the teammate as an in-process subagent instead.
SELF=${0:A}
usage() { sed -n 2,12p $SELF; exit 5; }
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
# The driver starts the session (and any viewer pane). Success prints "<id> <viewer|->", then the lines to show after "launched".
OUT=$(drv launch $D $NAME $W $CHOSEN $P ${RO:-0})
RC=$?
(( RC == 9 )) && exit 5   # the driver has no launch operation; drv already said so on stderr
(( RC != 0 )) && { print -r -- "$OUT"; exit $RC; }
read -r ID VREF <<< ${OUT%%$'\n'*}
[[ $VREF == - ]] && VREF=
printf '%s %s %s %s %s\n' "$NAME" "$ID" "$(date -u +%s)" "${VREF:--}" "$W" >> $REG
echo "launched $NAME as background session $ID in $W${RO:+ (read-only)}${VREF:+ (viewer $VREF)}"
if [[ $OUT == *$'\n'* ]]; then print -r -- "${OUT#*$'\n'}"; fi
