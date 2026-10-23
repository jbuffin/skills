#!/bin/zsh
# usage: state-set.sh <run> mode <key> <value>
#        state-set.sh <run> <units|trace|findings> <row-key> <column> <value>
#        state-set.sh <run> <units|trace|findings> --add <row-key> [<column>=<value> ...]
#        state-set.sh <run> <units|trace|findings> --drop <row-key>
# Edits one field of <run>/state.md in place and prints nothing. `mode` adds or replaces a `key: value` line under
# `## Mode, phase, current unit`; the tables address a row by its first column and a column by its header, without the
# part in brackets. A status must be one of its table's set: units planned|building|review|shipping|closed, trace
# open|partial|done|blocked, findings open|fixed|human; --add starts it at the first. A value can't hold a newline, and
# a `|` in a cell is escaped. A section from before this format is refused: edit it by hand. Exits 1 on a refusal, with
# one line on stderr, and 5 on bad usage.
usage() { sed -n 2,11p $0 >&2; exit 5; }
[[ -z $1 || -z $2 || -z $3 || ! -f $1/team.env || ! -f $1/state.md ]] && usage
F=${1:A}/state.md; T=$2; shift 2
for a in "$@"; do [[ $a == *[$'\n\r']* ]] && { print -r -- "a value can't hold a newline" >&2; exit 1; }; done
case $T in
  mode) (( $# == 2 )) || usage
        [[ $1 =~ '^[a-z][a-z0-9 _-]*$' ]] || { print -r -- "invalid mode key '$1': use lowercase letters, digits, spaces, _ or -" >&2; exit 1; }
        HEAD='## Mode, phase, current unit'; OP=mode; KEY=$1; VAL=$2 ;;
  units)    HEAD='## Units'; STATUSES='planned building review shipping closed' ;|
  trace)    HEAD='## Acceptance trace'; STATUSES='open partial done blocked' ;|
  findings) HEAD='## Non-blocking findings'; STATUSES='open fixed human' ;|
  units|trace|findings)
        case $1 in
          --add)  [[ -n $2 ]] || usage; OP=add; KEY=$2; shift 2
                  i=0; for p in "$@"; do
                    [[ $p == ?*=* ]] || usage
                    (( i++ )); export ADDC$i=${p%%=*} ADDV$i=${${p#*=}//|/\\|}
                  done; export ADDN=$i ;;
          --drop) (( $# == 2 )) || usage; OP=drop; KEY=$2 ;;
          *)      (( $# == 3 )) || usage; OP=set; KEY=$1; COL=$2; VAL=${3//|/\\|} ;;
        esac
        KEY=${KEY//|/\\|} ;;
  *) usage ;;
esac
TMP=$(mktemp ${F:h}/.state.md.XXXXXX) || exit 1; trap 'rm -f $TMP' EXIT
T=$T HEAD=$HEAD OP=$OP KEY=$KEY COL=$COL VAL=$VAL STATUSES=$STATUSES awk '
function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
function norm(h) { sub(/[ \t]*\(.*\)$/, "", h); return tolower(trim(h)) }
function fail(m) { print m > "/dev/stderr"; exit 1 }
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
{ L[++N] = $0 }
END {
  op = ENVIRON["OP"]; key = ENVIRON["KEY"]; head = ENVIRON["HEAD"]
  for (i = 1; i <= N; i++) if (index(L[i], head) == 1) { s = i; break }
  if (!s) fail("state.md has no `" head "` section")
  for (e = s + 1; e <= N && L[e] !~ /^## /; e++) ;
  if (op == "mode") {
    p = s
    for (i = s + 1; i < e; i++) {
      if (index(L[i], key ":") == 1) { L[i] = key ": " ENVIRON["VAL"]; p = 0; break }
      if (L[i] ~ /[^ \t]/) p = i
    }
    if (p == s) ins = "\n" key ": " ENVIRON["VAL"]; else if (p) ins = key ": " ENVIRON["VAL"]
  } else {
    for (h = s + 1; h < e && L[h] !~ /^[ \t]*\|/; h++) ;
    if (h >= e || L[h + 1] !~ /^[ \t]*\|[ \t:|-]*-[ \t:|-]*$/)
      fail("section `" head "` isn" "\047" "t in table format; edit it by hand")
    nc = cells(L[h], H); for (i = 1; i <= nc; i++) NH[i] = norm(H[i])
    r = 0; keys = ""; lr = h + 1
    for (i = h + 2; i < e && L[i] ~ /^[ \t]*\|/; i++) {
      lr = i; cells(L[i], C); keys = keys (keys == "" ? "" : ", ") C[1]
      if (C[1] == key) r = i
    }
    sc = 0; for (i = 1; i <= nc; i++) if (NH[i] == "status") sc = i
    if (op == "add") {
      if (r) fail("row `" key "` is already in " ENVIRON["T"])
      split("", C); C[1] = key; for (i = 2; i <= nc; i++) C[i] = ""
      if (sc) { split(ENVIRON["STATUSES"], st, " "); C[sc] = st[1] }
      for (j = 1; j <= ENVIRON["ADDN"] + 0; j++) {
        c = colidx(ENVIRON["ADDC" j]); if (c == 1) fail("the key column is set by the row key")
        C[c] = ENVIRON["ADDV" j]; if (c == sc) checkstatus(C[c])
      }
      p = lr; ins = row(C, nc)
    } else {
      if (!r) fail("no row `" key "` in " ENVIRON["T"] "; rows: " (keys == "" ? "(none)" : keys))
      if (op == "drop") drop = r
      else {
        c = colidx(ENVIRON["COL"]); if (c == 1) fail("the key column can" "\047" "t be set; --drop the row and --add it")
        n = cells(L[r], C); for (i = n + 1; i <= nc; i++) C[i] = ""
        C[c] = ENVIRON["VAL"]; if (c == sc) checkstatus(C[c])
        L[r] = row(C, nc > n ? nc : n)
      }
    }
  }
  for (i = 1; i <= N; i++) { if (i != drop) print L[i]; if (i == p && ins != "") print ins }
}' $F > $TMP || exit 1
mv $TMP $F
