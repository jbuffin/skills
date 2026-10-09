#!/bin/zsh
# usage: watch-ci.sh <run-dir> <branch> [workflow]     (run in the background)
# Waits for the CI run of <workflow> (default $CI_WORKFLOW) on <branch>'s current local head SHA,
# then prints "<conclusion> | <job>: <conclusion> ; ...". Exits 0 when the run succeeded, 1 when it failed or no run
# appeared within 10 minutes.
[[ -z $1 || -z $2 || ! -f $1/team.env ]] && { sed -n 2,6p $0; exit 5; }
source $1/team.env
B=$2; WF=${3:-$CI_WORKFLOW}
SHA=$(git -C $WORKTREE rev-parse --verify -q $B) || { echo "branch $B not found in $WORKTREE"; exit 1; }
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
exit $(( RC != 0 ))
