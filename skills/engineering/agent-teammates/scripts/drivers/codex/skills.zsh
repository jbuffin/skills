# Sourced by has-skill and list-skills, with REPO set, so the two operations can't drift.
CH=${CODEX_HOME:-$HOME/.codex}
# skill_list: `<name><TAB><SKILL.md>` lines, unsorted, a name possibly repeated
skill_list() {
  local f
  for f in $HOME/.agents/skills/*/SKILL.md(N) $CH/skills/**/*/SKILL.md(ND) $CH/plugins/cache/**/skills/**/*/SKILL.md(N); do
    print -r -- "${f:h:t}"$'\t'"$f"
  done
  [[ -n $REPO ]] && for f in $REPO/.agents/skills/*/SKILL.md(N); do print -r -- "${f:h:t}"$'\t'"$f"; done
  return 0
}
