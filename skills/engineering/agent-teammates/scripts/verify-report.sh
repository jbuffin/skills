#!/bin/zsh
# usage: verify-report.sh <team-dir> <name> [--workdir <dir>] [label...]
# Checks a teammate's proof before you act on its DONE, so a fluent report never stands in for evidence.
#   - reports/<name>.md and reports/<name>.done exist and are newer than the teammate's latest tasking
#   - the proofs are every label in prompts/<name>.proof plus any [label] given; each needs a log from this tasking
#     (reports/<name>-evidence/<label>.log, written by evidence.sh) that ran the declared command,
#     in the teammate's worktree, on its current HEAD with nothing uncommitted, and ended "exit: 0"
#   - the .proof file is older than the tasking (a teammate can't rewrite its own proof)
#   - the worktree is clean, and when there are proofs the report has one "commit: <sha>" line naming HEAD
# The worktree is the teammate's workdir from teammates.tsv, or --workdir for an in-process teammate. A teammate
# with proofs and no git worktree fails. Prints OK / FAIL / NOTE lines and a last line "verdict: verified" (exit 0)
# or "verdict: unverified" (exit 1).
[[ -z $1 || -z $2 || ! -d $1 ]] && { sed -n 2,12p $0; exit 5; }
RUN=${1:A}; NAME=$2; shift 2
WD=; [[ $1 == --workdir ]] && { WD=${2:A}; shift 2; }
R=$RUN/reports; REP=$R/$NAME.md; E=$R/$NAME-evidence; PROOF=$RUN/prompts/$NAME.proof; BAD=0
ok()   { echo "OK   $*"; }
fail() { echo "FAIL $*"; BAD=1; }
mtime() { stat -f %m $1 2>/dev/null || echo 0; }

# The latest tasking: launch or retasked.sh. Anything older belongs to an earlier round.
TASKED=$(awk -v n=$NAME '$1==n && $3 ~ /^[0-9]+$/ {v=$3} END {print v+0}' $RUN/teammates.tsv 2>/dev/null)
[[ -z $WD ]] && WD=$(awk -v n=$NAME '$1==n && $5 != "" {v=$5} END {print v}' $RUN/teammates.tsv 2>/dev/null)
(( TASKED )) || echo "NOTE $NAME isn't in teammates.tsv (an in-process teammate?); freshness can't be checked"

for f in $REP $R/$NAME.done; do
  if [[ ! -f $f ]]; then fail "missing $f"
  elif (( $(mtime $f) < TASKED )); then fail "${f:t} is from an earlier tasking"
  else ok "${f:t} from this tasking"; fi
done

typeset -A want
if [[ -f $PROOF ]]; then
  while read -r lab cmd; do [[ -n $lab && $lab != \#* ]] && want[$lab]=$cmd; done < $PROOF
  (( $(mtime $PROOF) > TASKED && TASKED > 0 )) && fail "${PROOF:t} changed after the tasking; rewrite it and re-task"
fi
for lab in $@; do (( ${+want[$lab]} )) || want[$lab]=; done

WT=; HEAD=
[[ -n $WD && -d $WD ]] && WT=$(git -C $WD rev-parse --show-toplevel 2>/dev/null)
[[ -n $WT ]] && HEAD=$(git -C $WT rev-parse HEAD)
if [[ -z $WT ]]; then
  (( ${#want} )) && fail "no git worktree for $NAME (workdir '${WD:-unknown}'); pass --workdir" \
    || echo "NOTE no git worktree for $NAME; git checks skipped"
fi

for lab in ${(ko)want}; do
  L=$E/$lab.log
  if [[ ! -f $L ]] || (( $(mtime $L) < TASKED )); then fail "$lab: no log from this tasking"; continue; fi
  # evidence.sh appends the exit line last, after the command has finished
  last=$(tail -1 $L)
  [[ $last == "exit: 0" ]] && ok "$lab: exit 0" || fail "$lab: ${last:-empty log} ($L)"
  shown=$(sed -n '1s/^\$ //p' $L)
  [[ -z ${want[$lab]} || $shown == ${want[$lab]} ]] || fail "$lab: ran '$shown', but the proof is '${want[$lab]}'"
  if [[ -n $WT ]]; then
    ld=$(sed -n 's/^dir: //p;3q' $L); lh=$(sed -n 's/^head: //p;4q' $L); lc=$(sed -n 's/^dirty: //p;5q' $L)
    [[ $(git -C "$ld" rev-parse --show-toplevel 2>/dev/null) == $WT ]] || fail "$lab: ran in $ld, not in $WT"
    [[ $lh == $HEAD ]] || fail "$lab: ran on ${lh:-unknown}, but HEAD is $HEAD; re-run it after the last commit"
    [[ ${lc:-1} == 0 ]] || fail "$lab: ran with ${lc:-unknown} uncommitted files"
  fi
done
(( ${#want} )) || echo "NOTE no proofs declared for $NAME"

if [[ -n $WT ]]; then
  n=$(git -C $WT status --porcelain | wc -l | tr -d ' ')
  [[ $n == 0 ]] && ok "worktree $WT clean at $HEAD" || fail "worktree $WT has $n uncommitted files"
  # one "commit: <sha>" line, markdown bullets and bold allowed
  shas=(${(f)"$(grep -E '^[-*[:space:]]*commit:' $REP 2>/dev/null | grep -oE '[0-9a-f]{7,40}' )"})
  if (( ${#shas} > 1 )); then fail "report has ${#shas} commit lines; give one"
  elif (( ${#shas} == 1 )); then
    [[ $HEAD == ${shas[1]}* ]] && ok "report's commit ${shas[1]} is HEAD" || fail "report claims commit ${shas[1]}, but HEAD is $HEAD"
  elif (( ${#want} )); then fail "report has no 'commit: <sha>' line (7+ hex characters)"; fi
fi

(( BAD )) && { echo "verdict: unverified"; exit 1; }
echo "verdict: verified"
