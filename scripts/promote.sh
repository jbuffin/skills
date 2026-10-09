#!/usr/bin/env bash
# Promote an incubator skill to skills/[<category>/] so it becomes installable.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
name="${1:-}"
category="${2:-}"
src="$root/incubator/$name"
rel="skills/${category:+$category/}$name"
dst="$root/$rel"

[[ -n "$name" && -f "$src/SKILL.md" ]] || { echo "usage: $0 <incubator-skill-name> [category]" >&2; exit 1; }
[[ ! -e "$dst" ]] || { echo "error: $rel already exists" >&2; exit 1; }

if grep -q 'TODO' "$src/SKILL.md"; then
  echo "error: incubator/$name/SKILL.md still contains TODO placeholders" >&2
  exit 1
fi

mkdir -p "$(dirname "$dst")"
git -C "$root" mv "$src" "$dst" 2>/dev/null || mv "$src" "$dst"

# Drop `internal: true`, and the metadata block if that leaves it empty.
awk '
  /^---$/ { fm++ }
  fm == 1 && /^  internal: true$/ { next }
  { lines[++n] = $0 }
  END {
    for (i = 1; i <= n; i++) {
      if (lines[i] == "metadata:" && lines[i+1] !~ /^  /) continue
      print lines[i]
    }
  }
' "$dst/SKILL.md" > "$dst/SKILL.md.tmp" && mv "$dst/SKILL.md.tmp" "$dst/SKILL.md"

"$root/scripts/validate.sh"
echo "promoted $name -> $rel"
