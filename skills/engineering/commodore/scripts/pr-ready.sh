#!/bin/zsh
# usage: pr-ready.sh <run-dir> <unit>
# Reads <unit>'s PR once with `gh pr view` (no gh write, no merge) and decides what leaves it ready for review.
# Exit 0, PR open: prints `run: gh pr ready <url>` while it is draft, else `ready: <url>`. Run the `run:` line as its
#   own tool call, so Admiral's guard sees it.
# Exit 1: prints `not ready: <url>: <reason>`. Exit 5: bad usage or a failed precondition, one line on stderr.
usage() { sed -n 2,6p ${ZSH_ARGZERO:-$0} >&2; exit 5; }
refuse() { print -ru2 -r -- "pr-ready.sh: $1"; exit 5; }
[[ -z $1 || -z $2 || $# -gt 2 || ! -f $1/state.md ]] && usage
command -v jq >/dev/null || refuse "needs jq on PATH"
RUN=${1:A}; U=$2
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
ROW=$(rows "## Units" unit,PR); RC=$?
(( RC )) && refuse "state.md's units table is missing, lacks a needed column (unit, PR) or can't be read"
[[ -n $ROW ]] || refuse "no row for unit '$U' in state.md"
PR=${ROW#*$'\t'}
[[ $PR =~ '^https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/pull/[0-9]+$' ]] \
  || refuse "unit '$U' has no full PR URL in its PR cell ('$PR'); Admiral's guard refuses a bare number or branch"

notready() { print -r -- "not ready: $PR: $1"; exit 1; }
JSON=$(gh pr view $PR --json isDraft,state) || notready "gh pr view failed"
J() { print -r -- "$JSON" | jq -r "$1"; }
[[ $(J .state) == OPEN ]] || notready "PR is $(J .state), not OPEN"

if [[ $(J .isDraft) == true ]]; then print "run: gh pr ready $PR"; else print "ready: $PR"; fi
exit 0
