#!/bin/zsh
# usage: pr-ready.sh <run-dir> <unit>
# Decides whether <unit>'s PR is clean enough to mark ready, in an Admiral autopilot run. Reads the PR once with
# `gh pr view` and makes no gh write. Clean means open, based on BASE_BRANCH, CI complete and green, at the unit
# branch's local head, and no `human` row for the unit in state.md's findings table.
# Exit 0, clean: prints the commands to run next, one per line as `run: gh pr ready <url>` (only while the PR is
# draft) and `run: gh pr merge --auto --<method> <url>` (only when ADMIRAL_AUTO_MERGE is set); `ready: <url>` when
# there are none. Run each as its own tool call, so Admiral's guard sees it.
# Exit 1, not clean: prints `not clean: <url>: <reason>`. Exit 5: bad usage or a precondition fails, with one line on stderr.
usage() { sed -n 2,2p $0 >&2; exit 5; }
refuse() { print -ru2 -r -- "pr-ready.sh: $1"; exit 5; }
[[ -z $1 || -z $2 || $# -gt 2 || ! -f $1/team.env || ! -f $1/state.md ]] && usage
command -v jq >/dev/null || refuse "needs jq on PATH"
RUN=${1:A}; U=$2; source $RUN/team.env; REPO=${REPO:-$WORKTREE}
[[ $ADMIRAL_AUTOPILOT == 1 ]] || refuse "ADMIRAL_AUTOPILOT=1 isn't set; only Admiral's guard makes autopilot's gh writes safe"
awk '/^## /{s=($0 ~ /^## Mode, phase, current unit/)} s && /^autopilot: on[ \t]*$/{f=1} END{exit !f}' $RUN/state.md \
  || refuse "state.md has no 'autopilot: on' line"
# The unit's row in the units table: branch and PR cells, by header name.
ROW=$(awk -F'|' -v u=$U '
  function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
  /^## /{s=($0 ~ /^## Units/); h=0; next}
  s && /^\|/ { if (!h) { for (i=2; i<NF; i++) { c=trim($i); if (c=="branch") b=i; if (c=="PR") p=i } h=1; next }
               if (trim($2)==u) { print trim($b) "\t" trim($p); exit } }' $RUN/state.md)
[[ -n $ROW ]] || refuse "no row for unit '$U' in state.md"
BR=${ROW%%$'\t'*}; PR=${ROW#*$'\t'}
[[ $PR =~ '^https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/pull/[0-9]+$' ]] \
  || refuse "unit '$U' has no full PR URL in its PR cell ('$PR'); Admiral's guard refuses a bare number or branch"
case ${ADMIRAL_AUTO_MERGE-} in ''|squash|merge|rebase) ;; *) refuse "ADMIRAL_AUTO_MERGE must be squash, merge or rebase" ;; esac

notclean() { print -r -- "not clean: $PR: $1"; exit 1; }
# A human row stays whatever its severity: mission-build puts findings left at the round cap there.
HUMAN=$(awk -F'|' -v u=$U '
  function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
  /^## /{s=($0 ~ /^## Non-blocking findings/); h=0; next}
  s && /^\|/ { if (!h) { for (i=2; i<NF; i++) { c=trim($i); if (c=="unit") a=i; if (c=="status") b=i } h=1; next }
               if (trim($a)==u && trim($b)=="human") n++ } END{print n+0}' $RUN/state.md)
JSON=$(gh pr view $PR --json isDraft,state,baseRefName,headRefOid,statusCheckRollup) || notclean "gh pr view failed"
J() { print -r -- $JSON | jq -r "$1"; }
[[ $(J .state) == OPEN ]] || notclean "PR is $(J .state), not OPEN"
[[ $(J .baseRefName) == $BASE_BRANCH ]] || notclean "stacked on $(J .baseRefName)"
(( HUMAN )) && notclean "$HUMAN finding(s) left for a human"
BAD=$(J '[.statusCheckRollup[]? | select(
    (if .__typename == "StatusContext" then .state == "SUCCESS"
     else .status == "COMPLETED" and (.conclusion | IN("SUCCESS", "NEUTRAL", "SKIPPED")) end) | not)] | length')
[[ $(J '.statusCheckRollup | length') == 0 ]] && notclean "no CI checks"
[[ $BAD == 0 ]] || notclean "$BAD check(s) not green"
HEAD=$(git -C $REPO rev-parse --verify -q $BR) || notclean "branch $BR not found in $REPO"
[[ $(J .headRefOid) == $HEAD ]] || notclean "PR head isn't $BR's local head"

[[ $(J .isDraft) == true ]] && print "run: gh pr ready $PR" && OUT=1
[[ -n $ADMIRAL_AUTO_MERGE ]] && print "run: gh pr merge --auto --$ADMIRAL_AUTO_MERGE $PR" && OUT=1
[[ -n $OUT ]] || print "ready: $PR"
exit 0
