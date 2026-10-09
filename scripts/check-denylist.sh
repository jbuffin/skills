#!/usr/bin/env bash
# Block names that must never appear in this repo (employers, internal systems, private repos).
#
# usage: check-denylist.sh            scan every tracked file
#        check-denylist.sh --staged   scan only what's staged (the pre-commit hook uses this)
#
# Patterns come from .denylist at the repo root: one case-insensitive extended regex per line,
# with # comments. The file is gitignored on purpose, since committing it would publish the names
# it exists to keep out. Without it, the check does nothing and says so.
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
