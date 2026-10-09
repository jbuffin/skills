#!/usr/bin/env bash
# Check every SKILL.md in skills/ and incubator/ against the Agent Skills frontmatter rules,
# plus this repo's convention: incubator skills are internal, promoted skills are not.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
errors=0
count=0

fail() { echo "  ✗ $1: $2" >&2; errors=$((errors + 1)); }

frontmatter() { awk '/^---$/ { n++; next } n == 1 { print } n >= 2 { exit }' "$1"; }

for file in "$root"/skills/*/SKILL.md "$root"/incubator/*/SKILL.md; do
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

if (( errors > 0 )); then
  echo "validation failed: $errors error(s) across $count skill(s)" >&2
  exit 1
fi
echo "ok: $count skill(s) valid"
