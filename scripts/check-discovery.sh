#!/usr/bin/env bash
# Check that `npx skills` discovers exactly the promoted skills: every skills/**/SKILL.md, and
# nothing from incubator/. Needs Node (npx).
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
version="${SKILLS_CLI_VERSION:-1.7.1}"

expected="$(find "$root/skills" -mindepth 2 -maxdepth 3 -name SKILL.md | sed -E 's#.*/([^/]+)/SKILL.md#\1#' | sort)"
found="$(env -u INSTALL_INTERNAL_SKILLS npx -y "skills@$version" add "$root" --list 2>&1 \
  | sed -E 's/\x1b\[[0-9;?]*[a-zA-Z]//g' | sed -n -E 's/^│    ([a-z0-9-]+)$/\1/p' | sort)"

if [[ "$expected" != "$found" ]]; then
  echo "skills CLI discovery doesn't match skills/:" >&2
  diff <(echo "$expected") <(echo "$found") | sed 's/^</  promoted, not discovered:/; s/^>/  discovered, not promoted:/' | grep -v '^[0-9]' >&2
  exit 1
fi
echo "ok: skills CLI discovers exactly the $(echo "$expected" | grep -c .) promoted skill(s)"
