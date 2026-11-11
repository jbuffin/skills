#!/bin/zsh
# usage: crew-draft.sh init <user|repo> [harness] | skills <run> | check <run> | save <run>     (run it from the repo)
#   init   makes the run dir, its team.env and <run>/draft/, and copies the target's role-named members into the draft
#          (a symlink or a file outside the target is skipped with a WARN on stderr). Prints the run dir, `FROM <dir>`
#          or `NEW <dir>`, `ROLESJSON <file>` when the target holds a roles.json, then `ROLES <roles.md>`.
#   skills prints `<name><TAB><file><TAB><description>` per skill the harness can load, `-` for no file or description.
#   check  casts the crew with the draft as the run layer. Prints the cast table, SHADOWED, OUTRANKED and UNSET lines,
#          then `CLEAN` or `NOT CLEAN: <n> warnings`; WARN lines go to stderr.
#   save   copies the draft into the target and removes the role-named member of a role the draft leaves out. Prints
#          `SAVED <file>` or `REMOVED <file>`; refuses with exit 1, changing nothing, on a symlinked dir or member file.
# Exits 1 when cast, list-skills or save fails, 3 when the harness has no list-skills, 5 on a bad call.
usage() { sed -n 2,11p ${ZSH_ARGZERO:-$0} >&2; exit 5; }
# commodore and agent-teammates: siblings when installed, under skills/engineering in this repo's checkout.
for SK in ${0:A:h:h:h} ${0:A:h:h:h:h}/skills/engineering; do [[ -f $SK/commodore/scripts/crew.py ]] && break; done
[[ -f $SK/commodore/scripts/crew.py ]] || { print -u2 "can't find commodore's crew.py next to ${0:A:h:h}"; exit 5; }
CREW=$SK/commodore/scripts/crew.py
AT=$SK/agent-teammates/scripts
ROLES=(implementer test-writer reviewer security-reviewer brief-checker triager target-steward scribe)   # the fix checker has no members to draft

target_dir() {  # target_dir <user|repo>: the crew directory for the target; REPO must be set for repo
  case $1 in
    user) print -r -- ${XDG_CONFIG_HOME:-$HOME/.config}/commodore/crew ;;
    repo) [[ -n $REPO ]] || { print -u2 "the repo target needs a git repo: run this from the repo"; exit 5; }; print -r -- $REPO/.commodore/crew ;;
    *) usage ;;
  esac
}
env_value() { sed -n "s/^$1='\(.*\)'\$/\1/p" $RUN/team.env; }
load_run() {
  [[ -n $1 && -f $1/team.env && -d $1/draft ]] || { print -u2 "$1 isn't a run dir from crew-draft.sh init"; exit 5; }
  RUN=${1:A}
  HARNESS=$(env_value HARNESS); REPO=$(env_value REPO); TARGET=$(env_value TARGET)
}

(( $# )) || usage
cmd=$1; shift
case $cmd in
  init)
    [[ $# -ge 1 && $# -le 2 ]] || usage
    REPO=$(git rev-parse --show-toplevel 2>/dev/null)
    d=$(target_dir $1) || exit $?
    h=${2:-$($AT/detect-harness.sh)}
    [[ $h =~ '^[a-z0-9-]+$' ]] || { print -u2 "can't tell the harness (detect-harness.sh said '${h//$'\n'/, }'): name it, e.g. crew-draft.sh init $1 claude"; exit 5; }
    [[ $REPO == *[\'$'\n']* ]] && { print -u2 "the repo path has a quote or a line break in it: $REPO"; exit 5; }
    RUN=$(mktemp -d ${TMPDIR:-/tmp}/setup-commodore.XXXXXX) || exit 1
    print -rl -- "HARNESS='$h'" "REPO='$REPO'" "TARGET='$1'" > $RUN/team.env
    mkdir $RUN/draft
    for r in $ROLES; do
      f=$d/$r.md
      if [[ -L $f ]]; then print -u2 -r -- "WARN  $f is a symlink; not copied"; continue; fi
      [[ -f $f ]] || continue
      if [[ ${f:A} != ${d:A}/* ]]; then print -u2 -r -- "WARN  $f resolves outside $d; not copied"; continue; fi
      cp $f $RUN/draft/$r.md
    done
    print -r -- $RUN
    if [[ -d $d ]]; then print -r -- "FROM $d"; else print -r -- "NEW $d"; fi
    [[ -f ${d:h}/roles.json ]] && print -r -- "ROLESJSON ${d:h}/roles.json"
    print -r -- "ROLES $SK/commodore/references/roles.md"
    ;;
  skills)
    [[ $# -eq 1 ]] || usage
    load_run $1
    [[ -x $AT/drivers/$HARNESS/list-skills ]] || { print -u2 "harness $HARNESS has no list-skills: ask the engineer which skills to use"; exit 3; }
    list=$($AT/drivers/$HARNESS/list-skills $RUN) || { print -u2 "list-skills failed on $HARNESS"; exit 1; }
    print -r -- $list | while IFS=$'\t' read -r name file; do
      [[ -n $name ]] || continue
      desc=-
      # The first top-level `description:` line, within the frontmatter when the file starts with `---`; a folded or
      # literal block (>, |) joins its indented lines.
      [[ $file != - && -f $file ]] && desc=$(awk '
        NR == 1 && /^---[ \t]*$/ { fm = 1; next }
        fm && /^---[ \t]*$/ { exit }
        b { if ($0 ~ /^[ \t]/) { sub(/^[ \t]+/, ""); d = d (d == "" ? "" : " ") $0; next } else exit }
        /^description:/ { v = $0; sub(/^description:[ \t]*/, "", v)
          if (v ~ /^[>|][-+]?$/ || v == "") { b = 1; next }
          d = v; exit }
        END { if (d ~ /^".*"$/ || d ~ /^'\''.*'\''$/) d = substr(d, 2, length(d) - 2); print d }' $file)
      print -r -- "$name"$'\t'"$file"$'\t'"${desc:--}"
    done
    ;;
  check)
    [[ $# -eq 1 ]] || usage
    load_run $1; target_dir $TARGET >/dev/null || exit $?
    # The draft is the run layer, so each role it holds is pinned and the rest are cast as in this repo today.
    [[ -e $RUN/crew ]] || ln -s draft $RUN/crew
    # The Admiral variables would swap in the fleet and run layers, so the check runs without them.
    nocrew=(env -u ADMIRAL_SHIP -u ADMIRAL_CREW_DIR -u ADMIRAL_RUN_CREW)
    table=$($nocrew $CREW cast --run $RUN 2> $RUN/check.err); rc=$?
    if (( rc )); then cat $RUN/check.err >&2; exit $rc; fi
    print -r -- $table
    drafted=(${${(f)"$(print -rl -- $RUN/draft/*.md(N:t:r))"}:#})
    n=0
    while IFS= read -r w; do
      [[ $w == WARN* ]] || continue
      print -u2 -r -- $w
      [[ $w == 'WARN  security-reviewer has no role skill'* ]] || (( n++ ))
    done < $RUN/check.err
    for r in $drafted; do
      if [[ $TARGET == user && -f $REPO/.commodore/crew/$r.md ]]; then
        print -r -- "SHADOWED $r: $REPO/.commodore/crew/$r.md has the same name, so this member does nothing in this repo"
      fi
      for o in ${(f)"$($nocrew $CREW resolve --layer repo=$REPO/.commodore/crew | jq -r --arg r $r '.members[]? | select(.role == $r and .name != $r) | .name')"}; do
        print -r -- "OUTRANKED $r: $o"
      done
    done
    for r in $ROLES; do
      (( ${drafted[(Ie)$r]} )) && continue
      if [[ $TARGET == repo ]]; then print -r -- "UNSET $r: each engineer's user-global crew decides, else the built-in"
      else print -r -- "UNSET $r: the repo's crew decides, else the built-in"; fi
    done
    (( n )) && print -r -- "NOT CLEAN: $n warnings" || print -r -- CLEAN
    ;;
  save)
    [[ $# -eq 1 ]] || usage
    load_run $1; d=$(target_dir $TARGET) || exit $?
    # Refuse before any write: a symlink in the target path or at a member file would send the write elsewhere.
    for p in ${d:h} $d; do
      [[ -L $p ]] && { print -u2 -r -- "$p is a symlink; nothing saved"; exit 1; }
    done
    for f in $d/${^ROLES}.md $RUN/draft/*.md(N:t); do
      [[ -L $d/${f:t} ]] && { print -u2 -r -- "$d/${f:t} is a symlink; nothing saved"; exit 1; }
    done
    mkdir -p $d || exit 1
    for f in $RUN/draft/*.md(N); do
      tmp=$(mktemp $d/.crew-draft.XXXXXX) || exit 1
      cp $f $tmp && chmod 644 $tmp && mv $tmp $d/${f:t} || { rm -f $tmp; exit 1; }
      print -r -- "SAVED $d/${f:t}"
    done
    for r in $ROLES; do
      if [[ -f $d/$r.md && ! -f $RUN/draft/$r.md ]]; then rm $d/$r.md || exit 1; print -r -- "REMOVED $d/$r.md"; fi
    done
    ;;
  *) usage ;;
esac
