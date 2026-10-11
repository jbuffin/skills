# Modes and worktrees

Read the section for the mode you picked. Every mode works in git worktrees, one per unit, so the engineer's checkout stays untouched. `<team>/unit-worktree.sh` creates them and records each one in `<run>/worktrees.tsv`, and those branches are the run's own, the only ones `<team>/push-branch.sh` will push. The agent-teammates launch script starts each teammate in its unit's worktree and refuses anywhere inside the repository's own checkout (`REPO` in `team.env`).

Worktrees stay until the engineer says otherwise, and the final report lists them.

## Single unit

One unit, with one worktree, one branch and one draft PR.

```bash
<team>/unit-worktree.sh <run> new <unit> <branch> [base]
```

Phase 1 still runs, just smaller. The manifest might be five lines and the team four teammates, and the probe still runs whenever anything is gated. If the unit grows past what one reviewer can hold, split it into a stack and tell the engineer.

## Stack

Several phases, passes or layers, or several related issues worked in order where each builds on the last. Each phase or issue is one unit with its own worktree, and the whole thing ships as a gh stack of draft PRs. Read the gh-stack skill first if it's installed, or `gh stack --help`.

```bash
<team>/unit-worktree.sh <run> stack <base> u1=<branch> u2=<branch> u3=<branch>   # all planned units
<team>/unit-worktree.sh <run> stack-add <unit> <branch>                           # a unit added mid-run
```

`stack` creates each branch from the one below it, each in its own worktree, and then `gh stack init` adopts them all without moving any checkout. A branch that already exists is used as it is, fast-forwarded to its pushed copy, and refused if it's checked out in the engineer's own checkout. It records the order in `<run>/stack.txt`. `stack-add` does the same for a new unit on top.

A fix belongs to the unit that owns the change. That unit's implementer makes the fix in that unit's worktree. Running `gh stack rebase --upstack` from there updates every clean worktree above it, and `gh stack push` publishes.

Needs gh-stack 0.2.0 or later, for stack tracking shared across worktrees. Pre-flight checks it.

## Independent units

Several issues that don't build on each other. Each gets one worktree and one PR from the base and goes through the same loop.

```bash
<team>/unit-worktree.sh <run> new <unit> <branch> [base]    # once per unit
```

## Existing PR

A PR to finish or get green. There's no new PR, just one worktree on the PR's branch.

```bash
<team>/unit-worktree.sh <run> pr <unit> <pr-number>
```

If the branch is checked out in the engineer's own checkout, the script stops and asks them to switch off it, which they do before leaving. If it's checked out in another worktree, the script uses that worktree instead of taking the branch away from it; confirm nobody else is working there. Either way it fast-forwards the branch to the PR's head, and stops if the local branch has diverged, so nobody builds on a stale head. All units work in that one worktree, one implementer at a time.

Pushing to the PR's branch is a gated action, so ask for it in the phase 1 batch.

To get CI green, make each unit a group of failing jobs with the same cause. The test writer reproduces each failure locally first.
