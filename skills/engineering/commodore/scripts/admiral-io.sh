#!/bin/zsh
# usage: admiral-io.sh item <draft.json>          publish an inbox item to $ADMIRAL_INBOX/<id>.json
#        admiral-io.sh report <draft.json>        publish the Admiral report to $ADMIRAL_REPORT
#        admiral-io.sh answer <inbox-dir> <id>    print <inbox-dir>/<id>.answer.json to stdout
# Write the draft with a file tool, never on a command line. item and report validate the draft, then publish it through a
# dot-prefixed temp file in the destination directory. With ADMIRAL_INBOX (item) or ADMIRAL_REPORT (report) unset or empty
# they read nothing, write nothing and exit 0. Exit codes: 0 done or nothing to do; 2 invalid draft, id, or item already
# exists; 3 answer not there yet (missing, or not valid JSON yet); 5 usage.
# An item is never overwritten (a re-asked question gets a new id); a report is replaced.
# Schemas: references/admiral-inbox-item.schema.json (item), references/admiral-report.schema.json (report).
# Validator: scripts/schema-check.py.
case $1:$# in
  item:2|report:2|answer:3) ;;
  *) sed -n 2,9p $0; exit 5 ;;
esac
HERE=${0:A:h}
CHECK=$HERE/schema-check.py
ID_RE='^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'

# A leading-dot temp name with a non-.json suffix, so Admiral's directory watch never sees a half-written file.
publish() { # publish <draft> <schema> <dest-dir> <dest-name> <replace|keep>
  local tmp
  mkdir -p $3 && tmp=$(mktemp $3/.$4.tmp.XXXXXX) || { echo "can't write in $3" >&2; exit 2; }
  if ! cp $1 $tmp || ! $CHECK $2 $tmp; then rm -f $tmp; echo "can't copy or validate the draft" >&2; exit 2; fi
  if [[ $5 == replace ]]; then
    mv -f $tmp $3/$4 || { rm -f $tmp; exit 2; }
  else
    # ln fails when the target exists; mv would replace it.
    ln $tmp $3/$4 2>/dev/null || { rm -f $tmp; echo "$3/$4 already exists; an item is never overwritten, use a new id" >&2; exit 2; }
    rm -f $tmp
  fi
}

case $1 in
  item)
    [[ -n $ADMIRAL_INBOX ]] || { echo "ADMIRAL_INBOX isn't set; no inbox item written" >&2; exit 0; }
    $CHECK $HERE/../references/admiral-inbox-item.schema.json $2 || exit 2
    ID=$(python3 -I -c 'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["id"])' $2) || exit 2
    [[ $ID =~ $ID_RE ]] || { echo "invalid item id '$ID'" >&2; exit 2; }
    publish $2 $HERE/../references/admiral-inbox-item.schema.json ${ADMIRAL_INBOX%/} $ID.json keep
    ;;
  report)
    [[ -n $ADMIRAL_REPORT ]] || { echo "ADMIRAL_REPORT isn't set; no report written" >&2; exit 0; }
    $CHECK $HERE/../references/admiral-report.schema.json $2 || exit 2
    publish $2 $HERE/../references/admiral-report.schema.json ${ADMIRAL_REPORT:h} ${ADMIRAL_REPORT:t} replace
    ;;
  answer)
    [[ $3 =~ $ID_RE ]] || { echo "invalid item id '$3'" >&2; exit 2; }
    [[ -f $2/$3.answer.json ]] || exit 3
    A=$(<$2/$3.answer.json)
    print -r -- $A | python3 -I -c 'import json, sys; json.load(sys.stdin)' 2>/dev/null \
      || { echo "$2/$3.answer.json isn't valid JSON yet; treating $3 as not answered" >&2; exit 3; }
    print -r -- $A
    ;;
esac
