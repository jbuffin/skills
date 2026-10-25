#!/bin/zsh
# usage: watch-ci.sh <run-dir> <branch> [workflow]     (run in the background)
# Waits for the CI run of <workflow> (default $CI_WORKFLOW) on <branch>'s current local head SHA,
# then prints "<conclusion> | <job>: <conclusion> ; ...". Exits 0 when the run succeeded, 1 when it failed or no run
# appeared within 10 minutes. On a failed run it also saves `gh run view --log-failed` to
# <run-dir>/ci-<branch>-<sha7>.log and prints that path and up to 20 failing lines from it.
[[ -z $1 || -z $2 || ! -f $1/team.env ]] && { sed -n 2,7p $0; exit 5; }
RUN=${1:A}; source $RUN/team.env
B=$2; WF=${3:-$CI_WORKFLOW}; REPO=${REPO:-$WORKTREE}
SHA=$(git -C $REPO rev-parse --verify -q $B) || { echo "branch $B not found in $REPO"; exit 1; }
# gh picks its repo from the working directory, so run it from the target repo, not wherever the coordinator started
cd $REPO || { echo "can't cd to $REPO"; exit 1; }
ERRF=$(mktemp); trap 'rm -f $ERRF' EXIT; ERR=
for i in {1..30}; do
  ID=$(gh run list --branch $B --workflow $WF --json databaseId,headSha -q "[.[] | select(.headSha==\"$SHA\")][0].databaseId" 2>$ERRF) \
    && ERR= || ERR=$(tail -1 $ERRF)
  [[ -n "$ID" && "$ID" != "null" ]] && break
  sleep 20
done
# a gh failure (auth, unknown workflow) isn't the same as CI never starting; say which
[[ -z "$ID" || "$ID" == "null" ]] && { echo "no $WF run found for $B at $SHA${ERR:+; gh failed: $ERR}"; exit 1; }
gh run watch $ID --exit-status --interval 60 > /dev/null 2>&1; RC=$?
gh run view $ID --json conclusion,jobs -q '.conclusion + " | " + ([.jobs[] | .name + ": " + .conclusion] | join(" ; "))'
(( RC == 0 )) && exit 0
# The failed log goes to a file, so the coordinator gets the failing lines without fetching the log itself.
# Each --log-failed line is "<job>\t<step>\t<timestamp> <text>"; keep the text.
LOG=$RUN/ci-${B//[^A-Za-z0-9._-]/-}-${SHA[1,7]}.log
gh run view $ID --log-failed > $LOG 2>&1 || echo "(gh run view --log-failed failed; the lines above are its error)" >> $LOG
echo "failed log: $LOG"
TEXT=$(cut -f3- $LOG | sed -E 's/^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z ?//')
FAILING=$(print -r -- $TEXT | grep -iE 'fail|error|panic|exception|assert' | head -20)
print -r -- "${FAILING:-$(print -r -- $TEXT | tail -20)}" | cut -c1-200
exit 1
