#!/bin/zsh
# usage: crew-draft.sh init <user|repo> [harness] | skills <run> | check <run> | save <run>
# Drafts Commodore crew members (commodore/references/crew-members.md) in a scratch run dir, using commodore's crew.py and
# the harness driver's list-skills and has-skill. Run it from the repo.
#   init   makes the run dir, its team.env (HARNESS, REPO, TARGET) and <run>/draft/, and copies the target's role-named
#          members into the draft. Prints the run dir, then `FROM <dir>` or `NEW <dir>`, then `ROLESJSON <file>` when the
#          target still holds a roles.json, then `ROLES <commodore's references/roles.md>`. The harness comes from
#          detect-harness.sh unless named. check and save use this target alone.
#   skills prints `<name><TAB><file><TAB><description>` for each skill the harness can load here; <file> is the skill's
#          SKILL.md or agent file, `-` for none, and so is a missing description.
#   check  casts the crew with the draft as the run layer, which pins each role it holds. Prints the cast table, its WARN
#          lines, a SHADOWED line for each draft member the repo has a member of the same name for, an OUTRANKED line for
#          each differently named repo member of a draft role, an UNSET line for each role the draft leaves out (never the
#          fix checker), then `CLEAN` or `NOT CLEAN: <n> warnings`. The security reviewer's warning doesn't count.
#   save   copies each draft file into the target dir and removes the target's role-named member for a role the draft
#          leaves out. Prints `SAVED <file>` or `REMOVED <file>` per change. No other member is touched.
# Exits 1 when cast fails or list-skills fails, 3 when the harness has no list-skills, 5 on a bad call.
usage() { sed -n 2p $0 >&2; exit 5; }
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
load_run() {  # load_run <run>: sets RUN, HARNESS, REPO and TARGET from the run's team.env
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
    [[ $REPO == *\'* ]] && { print -u2 "the repo path has a quote in it: $REPO"; exit 5; }
    RUN=$(mktemp -d ${TMPDIR:-/tmp}/setup-commodore.XXXXXX) || exit 1
    print -rl -- "HARNESS='$h'" "REPO='$REPO'" "TARGET='$1'" > $RUN/team.env
    mkdir $RUN/draft
    for r in $ROLES; do [[ -f $d/$r.md ]] && cp $d/$r.md $RUN/draft/$r.md; done
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
    table=$($CREW cast --run $RUN 2> $RUN/check.err); rc=$?
    if (( rc )); then cat $RUN/check.err >&2; exit $rc; fi
    print -r -- $table
    drafted=(${${(f)"$(print -rl -- $RUN/draft/*.md(N:t:r))"}:#})
    n=0
    while IFS= read -r w; do
      [[ $w == WARN* ]] || continue
      print -r -- $w
      [[ $w == 'WARN  security-reviewer has no role skill'* ]] || (( n++ ))
    done < $RUN/check.err
    for r in $drafted; do
      if [[ $TARGET == user ]]; then
        [[ -f $REPO/.commodore/crew/$r.md ]] && print -r -- "SHADOWED $r: $REPO/.commodore/crew/$r.md has the same name, so this member does nothing in this repo"
        for o in ${(f)"$($CREW resolve --layer repo=$REPO/.commodore/crew | jq -r --arg r $r '.members[]? | select(.role == $r and .name != $r) | .name')"}; do
          print -r -- "OUTRANKED $r: $o"
        done
      fi
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
    mkdir -p $d || exit 1
    for f in $RUN/draft/*.md(N); do
      cp $f $d/${f:t}.tmp.$$ && mv $d/${f:t}.tmp.$$ $d/${f:t} || { rm -f $d/${f:t}.tmp.$$; exit 1; }
      print -r -- "SAVED $d/${f:t}"
    done
    for r in $ROLES; do
      if [[ -f $d/$r.md && ! -f $RUN/draft/$r.md ]]; then rm $d/$r.md || exit 1; print -r -- "REMOVED $d/$r.md"; fi
    done
    ;;
  *) usage ;;
esac
