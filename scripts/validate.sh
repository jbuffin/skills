#!/usr/bin/env bash
# Check every SKILL.md in skills/ and incubator/ against the Agent Skills frontmatter rules,
# plus this repo's conventions: incubator skills are internal, promoted skills are not; every
# category is in plugin.json; every promoted skill is in the README; scripts are executable;
# relative links resolve.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
errors=0
count=0

fail() { echo "  ✗ $1: $2" >&2; errors=$((errors + 1)); }

frontmatter() { awk '/^---$/ { n++; next } n == 1 { print } n >= 2 { exit }' "$1"; }

for file in "$root"/skills/*/SKILL.md "$root"/skills/*/*/SKILL.md "$root"/incubator/*/SKILL.md; do
  [[ -f "$file" ]] || continue
  count=$((count + 1))
  rel="${file#"$root"/}"
  dir="$(basename "$(dirname "$file")")"
  tree="${rel%%/*}"

  [[ "$(head -n1 "$file")" == "---" ]] || { fail "$rel" "missing frontmatter"; continue; }
  fm="$(frontmatter "$file")"

  name="$(sed -n 's/^name:[[:space:]]*//p' <<<"$fm" | head -n1 | tr -d "\"'")"
  desc="$(sed -n 's/^description:[[:space:]]*//p' <<<"$fm" | head -n1)"

  [[ -n "$name" ]] || fail "$rel" "missing name"
  [[ "$name" == "$dir" ]] || fail "$rel" "name '$name' does not match directory '$dir'"
  [[ "$name" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]] || fail "$rel" "name must be lowercase letters, digits, hyphens"
  (( ${#name} <= 64 )) || fail "$rel" "name longer than 64 chars"
  [[ -n "$desc" ]] || fail "$rel" "missing description"
  (( ${#desc} <= 1024 )) || fail "$rel" "description longer than 1024 chars"

  internal=false
  grep -Eq '^[[:space:]]+internal:[[:space:]]*true' <<<"$fm" && internal=true
  if [[ "$tree" == "incubator" && "$internal" != true ]]; then
    fail "$rel" "incubator skills must set metadata.internal: true"
  fi
  if [[ "$tree" == "skills" ]]; then
    [[ "$internal" == false ]] || fail "$rel" "promoted skill is still marked internal"
    grep -q 'TODO' "$file" && fail "$rel" "promoted skill contains TODO placeholders"
  fi
done

for json in "$root"/.claude-plugin/*.json; do
  python3 -m json.tool "$json" >/dev/null 2>&1 || fail "${json#"$root"/}" "invalid JSON"
done

# The Claude Code plugin only loads category folders listed in plugin.json.
plugin_skills="$(python3 -c 'import json,sys; s=json.load(open(sys.argv[1])).get("skills",[]); print("\n".join([s] if isinstance(s,str) else s))' \
  "$root/.claude-plugin/plugin.json" 2>/dev/null || true)"
for category in "$root"/skills/*/; do
  ls "$category"*/SKILL.md >/dev/null 2>&1 || continue
  rel="skills/$(basename "$category")/"
  grep -qxF "./$rel" <<<"$plugin_skills" || fail ".claude-plugin/plugin.json" "skills array is missing \"./$rel\""
done

# Every promoted skill is listed in the README catalogue.
for file in "$root"/skills/*/SKILL.md "$root"/skills/*/*/SKILL.md; do
  [[ -f "$file" ]] || continue
  name="$(basename "$(dirname "$file")")"
  grep -qF "| \`$name\` |" "$root/README.md" || fail "README.md" "skill '$name' has no row in the Skills table"
done

# Scripts with a shebang must be executable.
while IFS= read -r script; do
  [[ -x "$root/$script" ]] || fail "$script" "has a shebang but isn't executable"
done < <(git -C "$root" grep -l -I '^#!' -- skills incubator scripts 2>/dev/null || true)

python3 "$root/scripts/check-links.py" "$root" >/dev/null || {
  python3 "$root/scripts/check-links.py" "$root" | sed 's/^/  ✗ /' >&2 || true
  fail "links" "broken relative links (see above)"
}

if (( errors > 0 )); then
  echo "validation failed: $errors error(s) across $count skill(s)" >&2
  exit 1
fi
echo "ok: $count skill(s) valid"
