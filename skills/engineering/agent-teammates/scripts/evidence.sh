#!/bin/zsh
# usage: evidence.sh <team-dir> <name> <label>                  run the proof command the coordinator declared
#        evidence.sh <team-dir> <name> <label> -- <command...>  run an extra command of your own
# Proof commands are declared one per line as "<label> <command>" in <team-dir>/prompts/<name>.proof, written by
# the coordinator; the declared form runs that command with zsh -c in the current directory. Saves the output as
# <team-dir>/reports/<name>-evidence/<label>.log: a header ("$ <command>", dir, head SHA, uncommitted file count,
# start time), the output, and a last line "exit: <code>". The log is written to a temp file and moved into place
# only once the command has finished, so a killed run leaves no log. Prints the last 40 lines and exits with the
# command's code. verify-report.sh checks these logs, not the report's prose.
[[ -z $1 || -z $2 || -z $3 || ( -n $4 && ( $4 != -- || -z $5 ) ) ]] && { sed -n 2,9p $0; exit 5; }
D=${1:A}; NAME=$2; LABEL=$3
source ${0:A:h}/team-env.zsh
valid_name $NAME; valid_name $LABEL
if [[ -n $4 ]]; then
  shift 4; CMD=(${@}); SHOWN=${(j: :)${(q-)@}}
  [[ -f $D/prompts/$NAME.proof ]] && awk -v l=$LABEL '$1==l {f=1} END {exit !f}' $D/prompts/$NAME.proof \
    && { echo "label $LABEL is a declared proof; run it without -- so the declared command runs"; exit 5; }
else
  SHOWN=$(awk -v l=$LABEL '$1==l {sub(/^[^ ]+ +/, ""); print; exit}' $D/prompts/$NAME.proof 2>/dev/null)
  [[ -z $SHOWN ]] && { echo "no proof '$LABEL' declared in $D/prompts/$NAME.proof"; exit 5; }
  CMD=(zsh -c $SHOWN)
fi
E=$D/reports/$NAME-evidence; mkdir -p $E; L=$E/$LABEL.log; T=$L.partial
{
  print -r -- "\$ $SHOWN"
  print -r -- "dir: $PWD"
  print -r -- "head: $(git rev-parse HEAD 2>/dev/null)"
  print -r -- "dirty: $(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
  print -r -- "start: $(date -u +%FT%TZ)"
  print -r -- "---"
} > $T
"${CMD[@]}" >> $T 2>&1
RC=$?
print -r -- "exit: $RC" >> $T
mv -f $T $L
tail -40 $L
exit $RC
