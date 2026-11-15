#!/usr/bin/env bash
# Sourced by each crew case's scaffold.sh: git repo, staged change and crew members in the workspace.

init_repo() {
  git init -q .
  mkdir -p src
  printf 'def parse(text):\n    return text.split(",")\n' > src/parser.py
  git add src/parser.py
  git -c user.name=eval -c user.email=eval@example.com commit -q -m "Add parser"
  printf 'def parse(text):\n    return [part.strip() for part in text.split(",")]\n' > src/parser.py
  git add src/parser.py
}

write_member() {
  local name=$1 role=$2 pick=$3
  mkdir -p .commodore/crew
  cat > ".commodore/crew/$name.md" <<MEMBER
---
name: $name
role: $role
pick-me-when: $pick
skills: []
---

# $name

Follow the $role role's fallback in references/roles.md.
MEMBER
}

write_members() {
  write_member pr-scribe scribe "Writing pull request bodies and descriptions for staged or finished work."
  write_member second-eyes reviewer "Reviewing a diff before it is merged, for a second opinion."
}
