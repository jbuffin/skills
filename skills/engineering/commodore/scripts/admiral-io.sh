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
# Same rule as the "id" pattern in the item schema; keep the two in step. answer needs it here, item gets it from the schema.
ID_RE='^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'

# schema-check.py validates the draft as strict JSON, then writes the parsed value (not the draft's bytes) through a
# dot-prefixed temp file in the destination directory, so Admiral's directory watch never sees a half-written .json.
case $1 in
  item)
    [[ -n $ADMIRAL_INBOX ]] || { echo "ADMIRAL_INBOX isn't set; no inbox item written" >&2; exit 0; }
    [[ ${ADMIRAL_INBOX%/} == "" ]] && { echo "ADMIRAL_INBOX is the root directory" >&2; exit 2; }
    # --into never replaces an existing entry (file, directory or symlink): Admiral never edits an item.
    "$CHECK" "$HERE/../references/admiral-inbox-item.schema.json" "$2" --into "${ADMIRAL_INBOX%/}" || exit 2
    ;;
  report)
    [[ -n $ADMIRAL_REPORT ]] || { echo "ADMIRAL_REPORT isn't set; no report written" >&2; exit 0; }
    "$CHECK" "$HERE/../references/admiral-report.schema.json" "$2" --to "$ADMIRAL_REPORT" || exit 2
    ;;
  answer)
    [[ $3 =~ $ID_RE ]] || { echo "invalid item id '$3'" >&2; exit 2; }
    [[ -f $2/$3.answer.json ]] || exit 3
    A=$(<"$2/$3.answer.json")
    print -r -- "$A" | "$CHECK" --json /dev/stdin 2>/dev/null \
      || { echo "$2/$3.answer.json isn't valid JSON yet; treating $3 as not answered" >&2; exit 3; }
    print -r -- "$A"
    ;;
esac
