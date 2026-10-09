#!/usr/bin/env bash
# Scaffold a new in-development skill under incubator/.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
name="${1:-}"

if [[ ! "$name" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]] || (( ${#name} > 64 )); then
  echo "usage: $0 <name>   (lowercase letters, digits, hyphens; max 64 chars)" >&2
  exit 1
fi
for dir in skills incubator; do
  if [[ -e "$root/$dir/$name" ]]; then
    echo "error: $dir/$name already exists" >&2
    exit 1
  fi
done

title="$(echo "$name" | tr '-' ' ' | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) substr($i,2)} 1')"
mkdir -p "$root/incubator/$name"
sed -e "s/__NAME__/$name/g" -e "s/__TITLE__/$title/g" \
  "$root/templates/SKILL.template.md" > "$root/incubator/$name/SKILL.md"

echo "created incubator/$name/SKILL.md"
