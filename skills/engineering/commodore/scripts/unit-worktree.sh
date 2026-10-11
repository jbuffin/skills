#!/bin/zsh
# Every unit works in its own git worktree, never in the engineer's checkout. Records "unit branch path"
# in <run>/worktrees.tsv; agent-teammates' launch-teammate.sh starts each teammate in its unit's worktree.
#
# usage:
#   unit-worktree.sh <run> new   <unit> <branch> [base]     single unit / independent units: new branch from origin/<base>
#   unit-worktree.sh <run> pr    <unit> <pr-number>         existing PR: a worktree on the PR's head branch, brought up
#                                                           to date with origin (fails if the local branch has diverged)
#   unit-worktree.sh <run> stack <base> <unit>=<branch>...  a stack: branch + worktree per unit, each from the one below,
#                                                           then `gh stack init` adopts them (needs gh-stack >= 0.2.0)
#   unit-worktree.sh <run> stack-add <unit> <branch>        add a unit on top of the existing stack
#   unit-worktree.sh <run> path  <unit>                     print a unit's worktree path
# Worktrees go in $WORKTREES_DIR/<run-name>-<unit> (default <repo>/.claude/worktrees).
# WORKTREE_SETUP in team.env lists the untracked files each worktree needs from the repository's checkout,
# space separated: copy:<path> (cp) or clone:<path> (an APFS clone, cp -c, for large trees like node_modules).
# A path already present in the worktree is left alone. Stack order (bottom to top) is kept in <run>/stack.txt.
[[ -z $1 || -z $2 || ! -f $1/team.env ]] && { sed -n 2,16p $0; exit 5; }
source $1/team.env; RUN=${1:A}; MODE=$2; shift 2
REPO=${REPO:-$WORKTREE}
WT_DIR=${WORKTREES_DIR:-$REPO/.claude/worktrees}
NAME=${RUN:t}
REG=$RUN/worktrees.tsv; touch $REG
G=(git -C $REPO)
setup() {
  local e kind rel
  for e in ${=WORKTREE_SETUP}; do
    kind=${e%%:*}; rel=${e#*:}
    [[ -e $1/$rel ]] && continue
    [[ -e $REPO/$rel ]] || { echo "WORKTREE_SETUP: $REPO/$rel missing; $1 has no $rel"; continue; }
    mkdir -p ${1}/${rel:h}
    case $kind in
      copy)  cp -R $REPO/$rel $1/$rel ;;
      clone) cp -cR $REPO/$rel $1/$rel 2>/dev/null || cp -R $REPO/$rel $1/$rel ;;
      *)     echo "WORKTREE_SETUP: unknown kind $kind in $e (use copy: or clone:)"; continue ;;
    esac && echo "  $kind $rel"
  done
}
record() { setup $3; grep -v -E "^$1 " $REG > $REG.tmp; print -r -- "$1 $2 $3" >> $REG.tmp; mv $REG.tmp $REG; echo "unit $1: branch $2 at $3"; }
path_of() { awk -v u=$1 '$1==u {print $3}' $REG | tail -1; }
owner_of() { $G worktree list --porcelain | awk -v b="refs/heads/$1" '/^worktree /{w=$2} $0=="branch " b {print w}'; }
# The engineer's checkout is never a unit's worktree: launch-teammate.sh refuses to start anyone there.
not_repo() {
  [[ ${1:A} == ${REPO:A} ]] || return 0
  echo "branch $2 is checked out in the repository's own checkout ($REPO). Switch that checkout off $2 (e.g. git switch ${BASE_BRANCH:-main}) and rerun, so the unit gets its own worktree."
  exit 1
}
# A branch that already exists locally may be behind the PR; working on it and then pushing --force-with-lease
# against the freshly fetched ref would throw the newer commits away. Fast-forward it, or stop.
catch_up() {
  local wt=$1 b=$2
  [[ -z $(git -C $wt rev-list -1 HEAD..origin/$b 2>/dev/null) ]] && return 0
  git -C $wt merge -q --ff-only origin/$b 2>/dev/null && { echo "fast-forwarded $b to origin/$b"; return 0; }
  echo "$b at $wt is behind origin/$b and can't fast-forward (diverged or uncommitted changes); reconcile it, then rerun"
  exit 1
}
need_stack_v2() {
  v=$(gh extension list 2>/dev/null | awk '/gh-stack/ {print $NF}' | tr -d v)
  [[ -n $v && $(printf '%s\n0.2.0\n' $v | sort -V | head -1) == 0.2.0 ]] \
    || { echo "gh-stack $v keeps stack tracking per worktree; one worktree per unit needs >= 0.2.0 (gh extension upgrade gh-stack)"; exit 4; }
}

case $MODE in
  new)
    U=$1; B=$2; BASE=${3:-$BASE_BRANCH}; P=$WT_DIR/$NAME-$U
    [[ -z $U || -z $B || -z $BASE ]] && { echo "usage: new <unit> <branch> [base]"; exit 5; }
    $G fetch -q origin $BASE || exit 1
    $G worktree add -q --no-track -b $B $P origin/$BASE || exit 1
    record $U $B $P ;;
  pr)
    U=$1; N=$2; P=$WT_DIR/$NAME-$U
    B=$(gh pr view $N -R "$($G remote get-url origin)" --json headRefName -q .headRefName) || exit 1
    $G fetch -q origin $B || exit 1
    o=$(owner_of $B)
    if [[ -n $o ]]; then
      not_repo $o $B
      echo "branch $B is already checked out at $o; using that worktree (not stealing it). Make sure no one else is working there."
      catch_up $o $B
      record $U $B $o
    else
      if $G show-ref -q --verify refs/heads/$B; then $G worktree add -q $P $B; else $G worktree add -q --track -b $B $P origin/$B; fi || exit 1
      catch_up $P $B
      record $U $B $P
    fi ;;
  stack)
    need_stack_v2
    BASE=$1; shift; prev=origin/$BASE; branches=(); : > $RUN/stack.txt
    $G fetch -q origin $BASE || exit 1
    for pair in "$@"; do
      U=${pair%%=*}; B=${pair#*=}; P=$WT_DIR/$NAME-$U
      if $G show-ref -q --verify refs/heads/$B; then
        o=$(owner_of $B); if [[ -n $o ]]; then not_repo $o $B; P=$o; else $G worktree add -q $P $B || exit 1; fi
        # a local branch may be behind its pushed copy; build on the newer one or stop
        $G fetch -q origin $B 2>/dev/null && catch_up $P $B
      else
        $G worktree add -q --no-track -b $B $P $prev || exit 1
      fi
      record $U $B $P; branches+=$B; prev=$B; print -r -- $U >> $RUN/stack.txt
    done
    first=$(path_of ${${1}%%=*})
    (cd $first && gh stack init --base $BASE $branches) || exit 1 ;;
  stack-add)
    need_stack_v2
    U=$1; B=$2; P=$WT_DIR/$NAME-$U
    topu=$(tail -1 $RUN/stack.txt 2>/dev/null)
    [[ -z $topu ]] && { echo "no stack recorded in $RUN/stack.txt; create it with the stack mode first"; exit 5; }
    topb=$(awk -v u=$topu '$1==u {b=$2} END {print b}' $REG); topp=$(path_of $topu)
    [[ -n $(git -C $topp status --porcelain) ]] && { echo "top unit's worktree $topp has uncommitted changes; commit first"; exit 1; }
    $G worktree add -q -b $B $P $topb || exit 1
    (cd $topp && gh stack add $B) || exit 1
    record $U $B $P; print -r -- $U >> $RUN/stack.txt ;;
  path) path_of $1 ;;
  *) sed -n 2,16p $0; exit 5 ;;
esac
