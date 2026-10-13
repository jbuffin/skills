#!/bin/zsh
# usage: roles-draft.sh init <user|repo> [harness] | skills <run> | check <run> | save <run>
# Drafts a Commodore role-override file (docs/adr/0004) in a scratch run dir, using commodore's role-skills.sh and the
# harness driver's list-skills and has-skill. Run it from the repo.
#   init   makes the run dir and its team.env (HARNESS, REPO, TARGET), and starts <run>/draft.json from the target file,
#          or {}. Prints the run dir, then `FROM <file>` or `NEW <file>`, then `ROLES <commodore's references/roles.md>`.
#          The harness comes from detect-harness.sh unless named. check and save use this target alone.
#   skills prints `<name><TAB><file><TAB><description>` for each skill the harness can load here; <file> is the skill's
#          SKILL.md or agent file, `-` for none, and so is a missing description.
#   check  resolves the draft as the run layer, which wins for every role it names. Prints the table's rows for those
#          roles, their WARN lines, a SHADOWED line for each user entry the repo's file overrides, an UNSET line for each
#          role the draft leaves out, then `CLEAN` or `NOT CLEAN: <n> warnings`. The security reviewer's warning doesn't
#          count.
#   save   writes the draft to the target file, each `skills` an ordered array of bare names, and prints `SAVED <file>`.
# Exits 1 when a layer or the draft isn't valid JSON or list-skills fails, 3 when the harness has no list-skills, 5 on a
# bad call.
usage() { sed -n 2p $0 >&2; exit 5; }
command -v jq >/dev/null || { print -u2 "roles-draft.sh needs jq on PATH"; exit 5; }
# commodore and agent-teammates: siblings when installed, under skills/engineering in this repo's checkout.
for SK in ${0:A:h:h:h} ${0:A:h:h:h:h}/skills/engineering; do [[ -x $SK/commodore/scripts/role-skills.sh ]] && break; done
[[ -x $SK/commodore/scripts/role-skills.sh ]] || { print -u2 "can't find commodore's role-skills.sh next to ${0:A:h:h}"; exit 5; }
RESOLVE=$SK/commodore/scripts/role-skills.sh
AT=$SK/agent-teammates/scripts

target_file() {  # target_file <user|repo>: the override file for the target; REPO must be set for repo
  case $1 in
    user) print -r -- ${XDG_CONFIG_HOME:-$HOME/.config}/commodore/roles.json ;;
    repo) [[ -n $REPO ]] || { print -u2 "the repo target needs a git repo: run this from the repo"; exit 5; }; print -r -- $REPO/.commodore/roles.json ;;
    *) usage ;;
  esac
}
load_run() {  # load_run <run>: sets RUN, HARNESS, REPO and TARGET from the run's team.env
  [[ -n $1 && -f $1/team.env && -f $1/draft.json ]] || { print -u2 "$1 isn't a run dir from roles-draft.sh init"; exit 5; }
  RUN=${1:A}
  HARNESS=$(sed -n 's/^HARNESS=//p' $RUN/team.env); REPO=$(sed -n 's/^REPO=//p' $RUN/team.env); TARGET=$(sed -n 's/^TARGET=//p' $RUN/team.env)
}
valid_draft() { jq -e 'type == "object"' $RUN/draft.json >/dev/null 2>&1 || { print -u2 "draft $RUN/draft.json isn't a JSON object"; exit 1; }; }

(( $# )) || usage
cmd=$1; shift
case $cmd in
  init)
    [[ $# -ge 1 && $# -le 2 ]] || usage
    REPO=$(git rev-parse --show-toplevel 2>/dev/null)
    f=$(target_file $1) || exit $?
    h=${2:-$($AT/detect-harness.sh)}
    [[ $h =~ '^[a-z0-9-]+$' ]] || { print -u2 "can't tell the harness (detect-harness.sh said '${h//$'\n'/, }'): name it, e.g. roles-draft.sh init $1 claude"; exit 5; }
    RUN=$(mktemp -d ${TMPDIR:-/tmp}/setup-commodore.XXXXXX) || exit 1
    print -rl -- "HARNESS=$h" "REPO=$REPO" "TARGET=$1" > $RUN/team.env
    if [[ -f $f ]]; then cp $f $RUN/draft.json; print -rl -- $RUN "FROM $f"
    else print -r -- '{}' > $RUN/draft.json; print -rl -- $RUN "NEW $f"; fi
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
    load_run $1; target_file $TARGET >/dev/null || exit $?
    valid_draft
    # As the run layer, the draft wins for every role it names, so those roles' rows and warnings are the draft's alone.
    # The other roles' rows come from files this draft doesn't decide, so they're left out.
    layer=$RUN/roles.json
    cp $RUN/draft.json $layer
    table=(${(f)"$($RESOLVE $RUN 2> $RUN/check.err)"}); rc=$?
    if (( rc )); then while IFS= read -r w; do print -u2 -r -- ${w//$layer/draft}; done < $RUN/check.err; exit $rc; fi
    roles=(${(f)"$(jq -r 'keys_unsorted[]' $RUN/draft.json)"})
    print -rl -- $table[1,2]
    for row in $table[3,-1]; do
      r=${${row#\| }%% *}
      (( ${roles[(Ie)$r]} )) && print -r -- ${row/%\| run \|/| draft |}
    done
    n=0
    while IFS= read -r w; do
      w=${w//$layer/draft}
      if [[ $w == 'WARN  draft: '* ]]; then print -r -- $w; (( n++ ))
      elif [[ $w == "WARN  can't check"* ]]; then print -r -- $w
      elif [[ $w == 'WARN  security-reviewer has no role skill'* ]]; then (( ${roles[(Ie)security-reviewer]} )) && print -r -- $w
      elif [[ $w == WARN\ \ *': skill '*' is not available on '* ]] && (( ${roles[(Ie)${${w#WARN  }%%:*}]} )); then print -r -- $w; (( n++ ))
      fi
    done < $RUN/check.err
    repo_roles=()
    [[ $TARGET == user && -f $REPO/.commodore/roles.json ]] && repo_roles=(${(f)"$(jq -r 'keys_unsorted[]' $REPO/.commodore/roles.json)"})
    for row in $table[3,-1]; do
      r=${${row#\| }%% *}
      if (( ${roles[(Ie)$r]} )); then
        (( ${repo_roles[(Ie)$r]} )) && print -r -- "SHADOWED $r: $REPO/.commodore/roles.json sets it, so this entry does nothing in this repo"
      elif [[ $TARGET == repo ]]; then print -r -- "UNSET $r: each engineer's user-global file decides, else the fallback"
      else print -r -- "UNSET $r: the repo's file decides, else the fallback"; fi
    done
    (( n )) && print -r -- "NOT CLEAN: $n warnings" || print -r -- CLEAN
    ;;
  save)
    [[ $# -eq 1 ]] || usage
    load_run $1; f=$(target_file $TARGET) || exit $?
    valid_draft
    mkdir -p ${f:h} || exit 1
    jq --indent 2 'map_values(if type == "object" and has("skills")
      then .skills |= ((if type == "string" then [.] else . end) | map(if type == "string" then sub("^[/$]"; "") else . end))
      else . end)' $RUN/draft.json > $f.tmp.$$ && mv $f.tmp.$$ $f || { rm -f $f.tmp.$$; exit 1; }
    print -r -- "SAVED $f"
    ;;
  *) usage ;;
esac
