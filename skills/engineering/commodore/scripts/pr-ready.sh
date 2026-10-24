#!/bin/zsh
# usage: pr-ready.sh <run-dir> <unit>
# Decides what to run to leave <unit>'s PR ready for review. Reads the PR once with `gh pr view` and makes no gh
# write. Works with autopilot on or off. The auto-merge check applies only when auto-merge is requested: ADMIRAL_AUTOPILOT=1
# in the real environment, `autopilot: on` in state.md and ADMIRAL_AUTO_MERGE set. It is clean when the PR is open,
# based on BASE_BRANCH, CI complete and green, at the unit branch's local head, with no `human` row for the unit.
# Exit 0, the PR is open: prints `run: gh pr ready <url>` while it is draft, whether or not it is clean. When auto-merge
# is requested and the PR is clean, it then prints `run: gh pr merge --auto --<method> <url>`; when it isn't clean,
# `no auto-merge: <url>: <reason>`. With no `run:` line it prints `ready: <url>` first. Run each `run:` line as its own tool
# call, so Admiral's guard sees it.
# Exit 1, can't be marked ready: prints `not ready: <url>: <reason>` (gh pr view failed, or the PR isn't OPEN).
# Exit 5: bad usage or a precondition fails, with one line on stderr.
usage() { sed -n 2,12p ${ZSH_ARGZERO:-$0} >&2; exit 5; }
refuse() { print -ru2 -r -- "pr-ready.sh: $1"; exit 5; }
[[ -z $1 || -z $2 || $# -gt 2 || ! -f $1/team.env || ! -f $1/state.md ]] && usage
command -v jq >/dev/null || refuse "needs jq on PATH"
# Admiral's variables count only from the real environment: team.env can't stand in for them. Read the two keys
# needed from team.env in a subshell, so nothing in it can change a variable this script decides with.
AUTOPILOT=${ADMIRAL_AUTOPILOT-}; AUTO_MERGE=${ADMIRAL_AUTO_MERGE-}; OUT=
RUN=${1:A}; U=$2
TE=$(source $RUN/team.env >/dev/null && print -r -- ${REPO:-$WORKTREE} && print -r -- $BASE_BRANCH) \
  || refuse "can't read REPO and BASE_BRANCH from team.env"
REPO=${${(@f)TE}[1]}; BASE_BRANCH=${${(@f)TE}[2]}
[[ -n $REPO ]] || refuse "team.env sets neither REPO nor WORKTREE"
[[ $U =~ '^[A-Za-z0-9._-]+$' ]] || refuse "invalid unit name '$U'"
# rows <section> <column,...>: prints the cells of each row whose `unit` cell is $U, tab-separated, in that column order.
# Cells and headers are read the way state-set.sh reads them. A missing section or column exits 7 (fail closed).
rows() {
  awk -v sec=$1 -v want=$2 -v u=$U '
    function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
    function norm(h) { sub(/[ \t]*\(.*\)$/, "", h); return tolower(trim(h)) }
    function cells(line, a,   n, i) {
      gsub(/\\\|/, "\001", line); sub(/^[ \t]*\|/, "", line); sub(/\|[ \t]*$/, "", line)
      n = split(line, a, "|"); for (i = 1; i <= n; i++) { a[i] = trim(a[i]); gsub(/\001/, "\\|", a[i]) }
      return n
    }
    /^## /{ if (index($0, sec) == 1) { s = 1; h = 0; next } if (s) exit; next }
    s && /^[ \t]*\|/ {
      if (!h) {
        nc = cells($0, H); nw = split(want, W, ",")
        for (j = 1; j <= nw; j++) { X[j] = 0; for (i = 1; i <= nc; i++) if (norm(H[i]) == tolower(W[j])) X[j] = i; if (!X[j]) bad = 1 }
        h = 1; next
      }
      if ($0 ~ /^[ \t]*\|[ \t:|-]*-[ \t:|-]*$/ || bad) next
      cells($0, C)
      if (C[X[1]] == u) { o = C[X[1]]; for (j = 2; j <= nw; j++) o = o "\t" C[X[j]]; print o }
    }
    END { if (!s || !h || bad) exit 7 }' $RUN/state.md
}
ROW=$(rows "## Units" unit,branch,PR); RC=$?
(( RC )) && refuse "state.md's units table is missing, lacks a needed column (unit, branch, PR) or can't be read"
[[ -n $ROW ]] || refuse "no row for unit '$U' in state.md"
ROW=${ROW#*$'\t'}; BR=${ROW%%$'\t'*}; PR=${ROW#*$'\t'}
[[ $PR =~ '^https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/pull/[0-9]+$' ]] \
  || refuse "unit '$U' has no full PR URL in its PR cell ('$PR'); Admiral's guard refuses a bare number or branch"
case $AUTO_MERGE in ''|squash|merge|rebase) ;; *) refuse "ADMIRAL_AUTO_MERGE must be squash, merge or rebase" ;; esac

FIND=$(rows "## Non-blocking findings" unit,status); RC=$?
(( RC )) && refuse "state.md's findings table is missing, lacks a needed column (unit, status) or can't be read"
# Auto-merge is requested only when Admiral's variable and state.md's mode section agree and a method is set.
REQ=
if [[ $AUTOPILOT == 1 && -n $AUTO_MERGE ]] \
  && awk '/^## /{s=($0 ~ /^## Mode, phase, current unit/)} s && /^autopilot: on[ \t]*$/{f=1} END{exit !f}' $RUN/state.md; then
  REQ=1
fi
notready() { print -r -- "not ready: $PR: $1"; exit 1; }
JSON=$(gh pr view $PR --json isDraft,state,baseRefName,headRefOid,statusCheckRollup) || notready "gh pr view failed"
J() { print -r -- "$JSON" | jq -r "$1"; }
[[ $(J .state) == OPEN ]] || notready "PR is $(J .state), not OPEN"

# The first reason the PR isn't clean for auto-merge, or nothing. A human row stays whatever its severity:
# mission-build puts findings left at the round cap there.
unclean() {
  local human bad head
  human=$(print -r -- $FIND | grep -c $'\thuman$')
  [[ $(J .baseRefName) == "$BASE_BRANCH" ]] || { print -r -- "stacked on $(J .baseRefName)"; return; }
  (( human )) && { print -r -- "$human finding(s) left for a human"; return; }
  [[ $(J '.statusCheckRollup | length') == 0 ]] && { print -r -- "no CI checks"; return; }
  bad=$(J '[.statusCheckRollup[]? | select(
      (if .__typename == "StatusContext" then .state == "SUCCESS"
       else .status == "COMPLETED" and (.conclusion | IN("SUCCESS", "NEUTRAL", "SKIPPED")) end) | not)] | length')
  [[ $bad == 0 ]] || { print -r -- "$bad check(s) not green"; return; }
  head=$(git -C $REPO rev-parse --verify -q $BR) || { print -r -- "branch $BR not found in $REPO"; return; }
  [[ $(J .headRefOid) == "$head" ]] || print -r -- "PR head isn't $BR's local head"
}

[[ $(J .isDraft) == true ]] && print "run: gh pr ready $PR" && OUT=1
WHY=; [[ -n $REQ ]] && WHY=$(unclean)
[[ -n $REQ && -z $WHY ]] && print "run: gh pr merge --auto --$AUTO_MERGE $PR" && OUT=1
[[ -n $OUT ]] || print "ready: $PR"
[[ -n $WHY ]] && print -r -- "no auto-merge: $PR: $WHY"
exit 0
