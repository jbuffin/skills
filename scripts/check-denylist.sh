#!/usr/bin/env bash
# usage: check-denylist.sh [--staged]  block names listed in the repo's .denylist (one regex per line)
# .denylist is gitignored: committing it would publish the names it keeps out.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
list="$root/.denylist"

if [[ ! -f "$list" ]]; then
  echo "skip: no .denylist file"
  exit 0
fi

patterns="$(grep -v -E '^[[:space:]]*(#|$)' "$list" | paste -sd '|' -)"
[[ -n "$patterns" ]] || { echo "skip: .denylist has no patterns"; exit 0; }

if [[ "${1:-}" == "--staged" ]]; then
  hits="$(git -C "$root" diff --cached -U0 --no-color -- . ':!.denylist' \
    | grep -E '^\+[^+]' | grep -i -E "$patterns" || true)"
else
  hits="$(git -C "$root" grep -n -i -E "$patterns" -- . ':!.denylist' || true)"
fi

if [[ -n "$hits" ]]; then
  echo "denylisted names found:" >&2
  echo "$hits" >&2
  exit 1
fi
echo "ok: no denylisted names"
