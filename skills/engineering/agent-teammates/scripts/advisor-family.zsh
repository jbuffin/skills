# Sourced, never run: the one place that decides whether a Claude teammate has the built-in advisor. No side effects on source.
# A model in the same family as ADVISOR has no advisor by design: the advisor is meant to be stronger, and it re-reads the
# teammate's whole transcript on every consult. Launch, Admiral launch, the direct probe and the preflight all ask here.
# advisor_family <model>                prints opus, sonnet, haiku or fable (case-insensitive substring, tested in that order),
#                                       or nothing when none matches ("sonnet[1m]" and "claude-opus-5.5" both resolve)
# advisor_same_family <model> <advisor> returns 0 only when both have a recognised family and the families are equal;
#                                       an unrecognised family on either side returns 1, so the flag is kept
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
