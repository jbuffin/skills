# Sourced by has-skill and list-skills, with REPO set: where Claude Code finds skills for the repo, kept in one place so
# the two operations can't drift.
# Built into Claude Code, so there's no SKILL.md to find. From the CLI's own skill list (Claude Code 2.x, October 2026);
# a name missing here is dropped with a warning, which says which name to check.
BUILTIN=(code-review security-review simplify init loop schedule run claude-api update-config keybindings-help fewer-permission-prompts)
CFG=${CLAUDE_CONFIG_DIR:-$HOME/.claude}
# skill_list [plugin]: prints `<name><TAB><SKILL.md>` for every skill in the installed plugins in effect for the repo
# (user-scoped ones, and project-scoped ones for the repo or a parent of it), only <plugin>'s when given. Without
# <plugin>, then the user's skills, the repo's .claude/skills and `<name><TAB>-` for each built-in. Unsorted; a name
# can repeat.
skill_list() {
  local i f plugins
  plugins=(${(f)"$(jq -r --arg p "$1" --arg repo "$REPO" '.plugins // {} | to_entries[]
    | select($p == "" or (.key | split("@")[0]) == $p) | .value[]
    | select(.scope != "project" or ($repo != "" and ($repo + "/" | startswith(.projectPath + "/")))) | .installPath' \
    $CFG/plugins/installed_plugins.json 2>/dev/null)"})
  for i in $plugins; do for f in $i/skills/**/*/SKILL.md(N); do print -r -- "${f:h:t}"$'\t'"$f"; done; done
  [[ -n $1 ]] && return 0
  for f in $CFG/skills/*/SKILL.md(N); do print -r -- "${f:h:t}"$'\t'"$f"; done
  [[ -n $REPO ]] && for f in $REPO/.claude/skills/*/SKILL.md(N); do print -r -- "${f:h:t}"$'\t'"$f"; done
  for f in $BUILTIN; do print -r -- "$f"$'\t-'; done
  return 0
}
