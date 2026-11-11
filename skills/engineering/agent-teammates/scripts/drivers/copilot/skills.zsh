# Sourced by has-skill and list-skills, with REPO set, so the two operations can't drift.
CH=${COPILOT_HOME:-$HOME/.copilot}
# skill_list: `<name><TAB><file>` lines, unsorted, a name possibly repeated; the CLI's slash commands such as
# `/security-review` are built-in agents, listed by their .agent.yaml
skill_list() {
  local f pkg
  # older versions stay under pkg/<platform>/<version> after an upgrade
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
