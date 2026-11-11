# Sourced by has-skill and list-skills, with REPO set, so the two operations can't drift.
# The CLI's built-in skills have no SKILL.md; this list is from Claude Code 2.x, October 2026.
BUILTIN=(code-review security-review simplify init loop schedule run claude-api update-config keybindings-help fewer-permission-prompts)
CFG=${CLAUDE_CONFIG_DIR:-$HOME/.claude}
# skill_list [plugin]: `<name><TAB><SKILL.md>` lines, unsorted, a name possibly repeated; only <plugin>'s when given
skill_list() {
  local i f m plugins
  plugins=(${(f)"$(jq -r --arg p "$1" --arg repo "$REPO" '.plugins // {} | to_entries[]
    | select($p == "" or (.key | split("@")[0]) == $p) | .value[]
    | select(.scope != "project" or ($repo != "" and (.projectPath as $pp | $repo + "/" | startswith($pp + "/")))) | .installPath' \
    $CFG/plugins/installed_plugins.json 2>/dev/null)"})
  # a synced plugin's folder is its name, with `~g<generation>` when the manifest gives one
  for m in $CFG/plugins/synced/*/manifest.json(N); do
    plugins+=(${(f)"$(jq -r --arg p "$1" --arg d ${m:h} '.plugins // [] | .[] | select($p == "" or .name == $p)
      | $d + "/" + .name + (if .generation then "~g\(.generation)" else "" end)' $m 2>/dev/null)"})
  done
  for i in $plugins; do for f in $i/skills/**/*/SKILL.md(N); do print -r -- "${f:h:t}"$'\t'"$f"; done; done
  [[ -n $1 ]] && return 0
  for f in $CFG/skills/*/SKILL.md(N) $CFG/skills/synced/*/*/SKILL.md(N); do print -r -- "${f:h:t}"$'\t'"$f"; done
  [[ -n $REPO ]] && for f in $REPO/.claude/skills/*/SKILL.md(N); do print -r -- "${f:h:t}"$'\t'"$f"; done
  for f in $BUILTIN; do print -r -- "$f"$'\t-'; done
  return 0
}
