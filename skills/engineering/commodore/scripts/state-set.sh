#!/bin/zsh
# usage: state-set.sh <run> mode <key> <value>
#        state-set.sh <run> mode --set <key>=<value> [<key>=<value> ...]
#        state-set.sh <run> <units|trace|findings> <row-key> <column> <value>
#        state-set.sh <run> <units|trace|findings> --set <row-key> <column>=<value> [<column>=<value> ...] [--set <row-key> ...]
#        state-set.sh <run> <units|trace|findings> --add <row-key> [<column>=<value> ...]
#        state-set.sh <run> <units|trace|findings> --drop <row-key>
# Edits <run>/state.md in place and prints nothing. `mode` adds or replaces a `key: value` line under
# `## Mode, phase, current unit`; the tables address a row by its first column and a column by its header, without the
# part in brackets. A status must be one of its table's set: units planned|building|review|shipping|closed, trace
# open|partial|done|blocked, findings open|fixed|human; --add starts it at the first. A value can't hold a newline, and
# a `|` in a cell is escaped. A section from before this format is refused: edit it by hand. --set changes several
# fields of one section in one call, the same as setting them one call at a time in order, or none of them: a
# `<key>=<value>` pair splits at its first `=`, and a table call takes one `--set <row-key> <column>=<value> ...` per row.
# Exits 1 on a refusal, with one line on stderr, and 5 on bad usage.
SELF=$0
usage() { sed -n 2,15p $SELF >&2; exit 5; }
# Fills FR, FC and FV with one entry per field from <key>=<value> pairs (mode) or --set groups (tables).
parsebatch() {
  local r p
  (( $# )) || usage
  FR=() FC=() FV=()
  if [[ $T == mode ]]; then
    for p in "$@"; do [[ $p == ?*=* ]] || usage; FR+=(''); FC+=("${p%%=*}"); FV+=("${p#*=}"); done
    return
  fi
  while (( $# )); do
    r=$1; shift; [[ $r != --set ]] || usage
    (( $# )) && [[ $1 != --set ]] || usage
    while (( $# )) && [[ $1 != --set ]]; do
      [[ $1 == ?*=* ]] || usage
      FR+=("$r"); FC+=("${1%%=*}"); FV+=("${1#*=}"); shift
    done
    if [[ $1 == --set ]]; then shift; (( $# )) || usage; fi
  done
}
[[ -z $1 || -z $2 || -z $3 || ! -f $1/team.env || ! -f $1/state.md ]] && usage
F=${1:A}/state.md; T=$2; shift 2
FR=() FC=() FV=(); BATCH=
if [[ $1 == --set ]]; then
  BATCH=1; shift
else
  for a in "$@"; do [[ $a == *[$'\n\r']* ]] && { print -r -- "a value can't hold a newline" >&2; exit 1; }; done
fi
case $T in
  mode) if [[ $BATCH ]]; then
          parsebatch "$@"
          for i in {1..${#FC}}; do
            [[ ${FC[i]}${FV[i]} == *[$'\n\r']* ]] && { print -r -- "mode key ${FC[i]//[$'\n\r']/ }: a value can't hold a newline" >&2; exit 1; }
            [[ ${FC[i]} =~ '^[a-z][a-z0-9 _-]*$' ]] || { print -r -- "mode key ${FC[i]}: invalid; use lowercase letters, digits, spaces, _ or -" >&2; exit 1; }
          done
        else
          (( $# == 2 )) || usage
          [[ $1 =~ '^[a-z][a-z0-9 _-]*$' ]] || { print -r -- "invalid mode key '$1': use lowercase letters, digits, spaces, _ or -" >&2; exit 1; }
          FR=(''); FC=("$1"); FV=("$2")
        fi
        HEAD='## Mode, phase, current unit'; OP=mode ;;
  units)    HEAD='## Units'; STATUSES='planned building review shipping closed' ;|
  trace)    HEAD='## Acceptance trace'; STATUSES='open partial done blocked' ;|
  findings) HEAD='## Non-blocking findings'; STATUSES='open fixed human' ;|
  units|trace|findings)
        if [[ $BATCH ]]; then
          parsebatch "$@"; OP=set
          for i in {1..${#FC}}; do
            [[ ${FR[i]}${FC[i]}${FV[i]} == *[$'\n\r']* ]] && { print -r -- "$T row ${FR[i]//[$'\n\r']/ } column ${FC[i]//[$'\n\r']/ }: a value can't hold a newline" >&2; exit 1; }
            FR[i]=${FR[i]//|/\\|}; FV[i]=${FV[i]//|/\\|}
          done
        else
          case $1 in
            --add)  [[ -n $2 ]] || usage; OP=add; KEY=$2; shift 2
                    i=0; for p in "$@"; do
                      [[ $p == ?*=* ]] || usage
                      (( i++ )); export ADDC$i=${p%%=*} ADDV$i=${${p#*=}//|/\\|}
                    done; export ADDN=$i ;;
            --drop) (( $# == 2 )) || usage; OP=drop; KEY=$2 ;;
            *)      (( $# == 3 )) || usage; OP=set; FR=("${1//|/\\|}"); FC=("$2"); FV=("${3//|/\\|}") ;;
          esac
          KEY=${KEY//|/\\|}
        fi ;;
  *) usage ;;
esac
export BN=${#FC}
for (( i = 1; i <= BN; i++ )); do export BR$i="${FR[i]}" BC$i="${FC[i]}" BV$i="${FV[i]}"; done
TMP=$(mktemp ${F:h}/.state.md.XXXXXX) || exit 1; trap 'rm -f $TMP' EXIT
T=$T HEAD=$HEAD OP=$OP KEY=$KEY STATUSES=$STATUSES BATCH=$BATCH awk '
function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
function norm(h) { sub(/[ \t]*\(.*\)$/, "", h); return tolower(trim(h)) }
function fail(m) { print PFX m > "/dev/stderr"; exit 1 }
function cells(line, a,   n, i) {
  gsub(/\\\|/, "\001", line); sub(/^[ \t]*\|/, "", line); sub(/\|[ \t]*$/, "", line)
  n = split(line, a, "|"); for (i = 1; i <= n; i++) { a[i] = trim(a[i]); gsub(/\001/, "\\|", a[i]) }
  return n
}
function row(a, n,   s, i) { s = "|"; for (i = 1; i <= n; i++) s = s " " a[i] " |"; return s }
function colidx(name,   i, l) {
  for (i = 1; i <= nc; i++) if (NH[i] == norm(name)) return i
  l = H[1]; for (i = 2; i <= nc; i++) l = l ", " H[i]
  fail("unknown column `" name "` in " ENVIRON["T"] "; columns: " l)
}
function checkstatus(v,   i, n, s) {
  n = split(ENVIRON["STATUSES"], s, " "); for (i = 1; i <= n; i++) if (v == s[i]) return
  fail("invalid status `" v "` for " ENVIRON["T"] "; use one of: " ENVIRON["STATUSES"])
}
function norow(key) { fail("no row `" key "` in " ENVIRON["T"] "; rows: " (keys == "" ? "(none)" : keys)) }
function put(at, text,   i) { for (i = N; i > at; i--) L[i + 1] = L[i]; L[at + 1] = text; N++; e++ }
function modeset(key, val,   i, q) {
  q = s
  for (i = s + 1; i < e; i++) {
    if (index(L[i], key ":") == 1) { L[i] = key ": " val; return }
    if (L[i] ~ /[^ \t]/) q = i
  }
  if (q == s) { put(s, ""); put(s + 1, key ": " val) } else put(q, key ": " val)
}
function setcell(r, name, val,   c, n, i) {
  c = colidx(name); if (c == 1) fail("the key column can" "\047" "t be set; --drop the row and --add it")
  n = cells(L[r], C); for (i = n + 1; i <= nc; i++) C[i] = ""
  C[c] = val; if (c == sc) checkstatus(C[c])
  L[r] = row(C, nc > n ? nc : n)
}
{ L[++N] = $0 }
END {
  op = ENVIRON["OP"]; key = ENVIRON["KEY"]; head = ENVIRON["HEAD"]; nf = ENVIRON["BN"] + 0
  for (i = 1; i <= N; i++) if (index(L[i], head) == 1) { s = i; break }
  if (!s) fail("state.md has no `" head "` section")
  for (e = s + 1; e <= N && L[e] !~ /^## /; e++) ;
  if (op == "mode") {
    for (j = 1; j <= nf; j++) modeset(ENVIRON["BC" j], ENVIRON["BV" j])
  } else {
    for (h = s + 1; h < e && L[h] !~ /^[ \t]*\|/; h++) ;
    if (h >= e || L[h + 1] !~ /^[ \t]*\|[ \t:|-]*-[ \t:|-]*$/)
      fail("section `" head "` isn" "\047" "t in table format; edit it by hand")
    nc = cells(L[h], H); for (i = 1; i <= nc; i++) NH[i] = norm(H[i])
    keys = ""; lr = h + 1
    for (i = h + 2; i < e && L[i] ~ /^[ \t]*\|/; i++) {
      lr = i; cells(L[i], C); keys = keys (keys == "" ? "" : ", ") C[1]
      RI[C[1]] = i
    }
    sc = 0; for (i = 1; i <= nc; i++) if (NH[i] == "status") sc = i
    if (op == "add") {
      if (key in RI) fail("row `" key "` is already in " ENVIRON["T"])
      split("", C); C[1] = key; for (i = 2; i <= nc; i++) C[i] = ""
      if (sc) { split(ENVIRON["STATUSES"], st, " "); C[sc] = st[1] }
      for (j = 1; j <= ENVIRON["ADDN"] + 0; j++) {
        c = colidx(ENVIRON["ADDC" j]); if (c == 1) fail("the key column is set by the row key")
        C[c] = ENVIRON["ADDV" j]; if (c == sc) checkstatus(C[c])
      }
      p = lr; ins = row(C, nc)
    } else if (op == "drop") {
      if (!(key in RI)) norow(key)
      drop = RI[key]
    } else {
      for (j = 1; j <= nf; j++) {
        rk = ENVIRON["BR" j]
        if (ENVIRON["BATCH"] != "") PFX = ENVIRON["T"] " row " rk " column " ENVIRON["BC" j] ": "
        if (!(rk in RI)) norow(rk)
        setcell(RI[rk], ENVIRON["BC" j], ENVIRON["BV" j])
      }
    }
  }
  for (i = 1; i <= N; i++) { if (i != drop) print L[i]; if (i == p && ins != "") print ins }
}' $F > $TMP || exit 1
mv $TMP $F
