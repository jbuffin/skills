#!/bin/zsh
# usage: push-branch.sh <run> <branch> [<expected-sha>]
# Force-pushes <branch> with --force-with-lease, only when it's one of the run's branches in <run>/worktrees.tsv and
# still checked out in its worktree there. With <expected-sha>, the push fails unless the remote branch is exactly there.
# The refspec is pinned to refs/heads/<branch>, so an allow rule on this script can't reach main.
[[ -z $1 || -z $2 || ! -f $1/team.env ]] && { sed -n 2,5p $0; exit 5; }
RUN=${1:A}; B=$2
[[ $B =~ '^[A-Za-z0-9._/-]+$' && $B != -* && $B != *..* ]] || { echo "invalid branch name '$B'"; exit 5; }
P=$(awk -v b=$B '$2==b {p=$3} END {print p}' $RUN/worktrees.tsv 2>/dev/null)
[[ -n $P ]] || { echo "$B isn't one of this run's branches (worktrees.tsv); refusing to push it"; exit 5; }
CUR=$(git -C $P symbolic-ref -q --short HEAD)
[[ $CUR == $B ]] || { echo "$P has ${CUR:-a detached HEAD} checked out, not $B; fix the worktree before pushing"; exit 5; }
L=--force-with-lease
if [[ -n $3 ]]; then
  [[ $3 =~ '^[0-9a-f]{7,40}$' ]] || { echo "invalid expected sha '$3'"; exit 5; }
  L=--force-with-lease=refs/heads/${B}:$3
fi
git -C $P push $L origin refs/heads/${B}:refs/heads/${B}
