#!/bin/zsh
# usage: role-skills.sh <run-dir>
# Resolves each role's skills from the override layers (docs/adr/0004): built-in (empty), then user-global
# ${XDG_CONFIG_HOME:-~/.config}/commodore/roles.json, then the repo's .commodore/roles.json, then <run-dir>/roles.json.
# A layer that names a role replaces that role's whole entry. Prints the resolved table for profile.md on stdout and
# WARN lines on stderr. Exits 1 when a layer isn't valid JSON (naming the file), 5 on a bad call; either message goes
# to stderr.
[[ -z $1 || ! -f $1/team.env ]] && { sed -n 2p $0 >&2; exit 5; }
command -v jq >/dev/null || { print -u2 "role-skills.sh needs jq on PATH"; exit 5; }
unset HARNESS   # HARNESS comes from team.env alone, never from the caller's environment
source $1/team.env
HARNESS=${HARNESS:-claude}; REPO=${REPO:-$WORKTREE}   # an old team.env has WORKTREE and no REPO
DRIVER=${0:A:h:h:h}/agent-teammates/scripts/drivers/$HARNESS
PREFIX=$(sed -n 's/^SKILL_PREFIX=//p' $DRIVER/driver.env 2>/dev/null | tail -1); PREFIX=${PREFIX:-/}

ROLES=(implementer test-writer reviewer security-reviewer brief-checker triager target-steward scribe)
typeset -A SKILLS INSTR SRC
for role in $ROLES; do SKILLS[$role]=; INSTR[$role]=; SRC[$role]=built-in; done
warn() { print -u2 -r -- "WARN  $*"; }

# One line per entry from a layer file: "R<US>role<US>skill skill...<US>instructions" (US is \x1f, so empty fields
# survive `read`), or "W<TAB>message".
# Names lose one leading / or $; instructions come out ready for a table cell.
JQ='
def name: "^[/$]?[A-Za-z0-9][A-Za-z0-9._:-]*$";
def cell: gsub("\r?\n"; "<br>") | gsub("\t"; " ") | gsub("[|]"; "\\|");
if type != "object" then error("the file must hold a JSON object keyed by role") else . end
| to_entries[] | .key as $role | .value as $v
| if ($ARGS.positional | index([$role])) == null then "W\tunknown role \"\($role)\" skipped"
  elif ($v | type) != "object" then "W\t\($role): its entry is not an object; skipped"
  else
    ( ($v | keys_unsorted - ["skills", "instructions"])[] | "W\t\($role): unknown field \"\(.)\" skipped" ),
    ( ($v.skills // []) | if type == "string" then [.] else . end ) as $s
    | if ($s | type) != "array" then "W\t\($role): skills is neither a list nor a name; entry skipped"
      else
        ( $s[] | select(type != "string" or (test(name) | not))
          | "W\t\($role): skill \(tojson) is not a skill name; dropped" ),
        ( if ($v.instructions != null and ($v.instructions | type) != "string")
          then "W\t\($role): instructions is not a string; ignored" else empty end ),
        "R\u001f\($role)\u001f\([ $s[] | strings | select(test(name)) | sub("^[/$]"; "") ] | join(" "))\u001f\(($v.instructions | strings | cell) // "")"
      end
  end'

layer() {  # layer <source> <file>
  [[ -f $2 ]] || return 0
  local out line t role skills instr
  # An empty file parses as no JSON at all, so it's refused like any other invalid file.
  [[ -n ${"$(<$2)"//[[:space:]]/} ]] || { print -u2 -r -- "$2 isn't a valid override file: it's empty"; exit 1; }
  out=$(jq -r $JQ $2 --args $ROLES 2>&1) || { print -u2 -r -- "$2 isn't a valid override file: ${out##*$'\n'}"; exit 1; }
  for line in ${(f)out}; do
    if [[ $line == W$'\t'* ]]; then warn "$2: ${line#W$'\t'}"; continue; fi
    IFS=$'\x1f' read -r t role skills instr <<< $line
    SKILLS[$role]=$skills; INSTR[$role]=$instr; SRC[$role]=$1
  done
}
layer user ${XDG_CONFIG_HOME:-$HOME/.config}/commodore/roles.json
[[ -n $REPO ]] && layer repo $REPO/.commodore/roles.json
layer run $1/roles.json

# Drop each skill the harness can't load. A driver without has-skill can't say, so every named skill is kept.
nocheck=
for role in $ROLES; do
  kept=()
  for n in ${=SKILLS[$role]}; do
    if [[ ! -x $DRIVER/has-skill ]]; then kept+=$n; nocheck=1
    elif $DRIVER/has-skill $1 $n >/dev/null 2>&1; then kept+=$n
    else warn "$role: skill $PREFIX$n is not available on $HARNESS; dropped"; fi
  done
  SKILLS[$role]=${(j: :)kept}
done
[[ -n $nocheck ]] && warn "can't check which skills are installed on $HARNESS (its driver has no has-skill); kept every named skill"

print -r -- '| Role | Skills | Instructions | Source |'
print -r -- '| --- | --- | --- | --- |'
for role in $ROLES; do
  names=(${=SKILLS[$role]})
  if (( $#names )); then cell=${(j:, :)${names/#/\`$PREFIX}/%/\`}
  elif [[ $role == security-reviewer ]]; then
    cell='none: not launched'
    warn "security-reviewer has no role skill: no security review this run"
  else cell='none (fallback procedure)'; fi
  print -r -- "| $role | $cell | ${INSTR[$role]:--} | ${SRC[$role]} |"
done
