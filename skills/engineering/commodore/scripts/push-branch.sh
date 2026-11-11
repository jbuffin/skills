#!/bin/zsh
# usage: push-branch.sh <run> <branch> [<expected-sha>]
# Force-pushes <branch> with --force-with-lease, only when it's one of the run's own branches (registered in
# <run>/worktrees.tsv) and is still checked out in the worktree recorded there. Runs from any directory.
# The refspec is pinned to refs/heads/<branch>:refs/heads/<branch>, so an allow rule on this script can't reach main
# or any other branch, which a prefix rule on `git push --force-with-lease origin <prefix>*` can
# (`origin agent/x:main` matches it). With <expected-sha>, the lease is that commit: the push fails unless the remote
# branch is still exactly there.
[[ -z $1 || -z $2 || ! -f $1/team.env ]] && { sed -n 2,9p $0; exit 5; }
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
