# Sourced by has-skill and list-skills, with REPO set: where Copilot CLI finds skills for the repo, kept in one place so
# the two operations can't drift.
CH=${COPILOT_HOME:-$HOME/.copilot}
# skill_list: prints `<name><TAB><file>` for every skill in $COPILOT_HOME/skills, ~/.agents/skills and the repo's
# .github/skills, .agents/skills and .claude/skills (<file> is its SKILL.md), then the CLI's built-in skills (their
# SKILL.md, or `-`) and the built-in agents behind its slash commands (their .agent.yaml; `/security-review` runs the
# security-review agent). Unsorted; a name can repeat.
skill_list() {
  local f pkg
  # Only the newest installed CLI version counts: older versions stay under pkg/<platform>/<version> after an upgrade.
  pkg=$(for f in $CH/pkg/*/*/definitions(/N:h); do print -r -- "${f:t} $f"; done | sort -t. -k1,1n -k2,2n -k3,3n | tail -1)
  pkg=(${pkg#* })
  for f in $CH/skills/*/SKILL.md(N) $HOME/.agents/skills/*/SKILL.md(N); do print -r -- "${f:h:t}"$'\t'"$f"; done
  [[ -n $REPO ]] && for f in $REPO/{.github,.agents,.claude}/skills/*/SKILL.md(N); do print -r -- "${f:h:t}"$'\t'"$f"; done
  (( $#pkg )) || return 0
  for f in $pkg/builtin-skills/*(N); do
    if [[ -f $f/SKILL.md ]]; then print -r -- "${f:t}"$'\t'"$f/SKILL.md"; else print -r -- "${f:t}"$'\t-'; fi
  done
  for f in $pkg/definitions/*.agent.yaml(N); do print -r -- "${f:t:r:r}"$'\t'"$f"; done
  return 0
}
