#!/bin/zsh
# usage: review-round.sh <run> <unit>
# Starts <unit>'s next review round and prints its number and rules. Run it before launching a round's reviewers.
# Round 1 is the full review: the reviewer and the security reviewer on the unit's diff. Round 2 is the last: one
# reviewer on the fix range, where only HIGH blocks. A third round is refused (exit 1): what's left goes to a human.
# Rounds are counted in <run>/rounds.tsv, one `<unit> <round>` line per round started.
[[ -z $1 || -z $2 || ! -f $1/team.env ]] && { sed -n 2,6p $0; exit 5; }
RUN=${1:A}; U=$2; CAP=2
[[ $U =~ '^[A-Za-z0-9._-]+$' ]] || { echo "invalid unit name '$U'"; exit 5; }
F=$RUN/rounds.tsv
N=$(awk -v u=$U '$1==u && $2>n {n=$2} END {print n+0}' $F 2>/dev/null)
(( N >= CAP )) && { echo "CAP $U: $CAP review rounds done; launch no more reviewers. Hand what's left to a human (the round-cap PR comment)"; exit 1; }
N=$(( N + 1 ))
print -r -- "$U $N" >> $F
case $N in
  1) echo "round 1 of $CAP for $U: full review. Launch $U-reviewer-1, and $U-security-reviewer-1 when the run has a security reviewer, on the unit's diff" ;;
  *) echo "round $N of $CAP for $U, the last: launch $U-reviewer-$N alone, on the fix range. Only HIGH blocks; everything else goes to a human" ;;
esac
