# Sourced by has-skill and list-skills, with REPO set: where Codex finds skills for the repo, kept in one place so the
# two operations can't drift.
CH=${CODEX_HOME:-$HOME/.codex}
# skill_list: prints `<name><TAB><SKILL.md>` for every skill in ~/.agents/skills, $CODEX_HOME/skills (its .system skills
# included), the installed plugins and the repo's .agents/skills. Unsorted; a name can repeat.
skill_list() {
  local f
  for f in $HOME/.agents/skills/*/SKILL.md(N) $CH/skills/**/*/SKILL.md(ND) $CH/plugins/cache/**/skills/**/*/SKILL.md(N); do
    print -r -- "${f:h:t}"$'\t'"$f"
  done
  [[ -n $REPO ]] && for f in $REPO/.agents/skills/*/SKILL.md(N); do print -r -- "${f:h:t}"$'\t'"$f"; done
  return 0
}
