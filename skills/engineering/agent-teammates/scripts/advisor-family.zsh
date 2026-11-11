# Sourced, never run: the one place that decides whether a Claude teammate has the built-in advisor.
# A same-family advisor is off by design: it is meant to be stronger, and it re-reads the whole transcript on every consult.
advisor_family() {
  local m=${(L)1} f
  for f in opus sonnet haiku fable; do
    [[ $m == *$f* ]] && { print -r -- $f; return 0; }
  done
  return 0
}
advisor_same_family() {
  local a=$(advisor_family $1) b=$(advisor_family $2)
  [[ -n $a && $a == $b ]]
}
