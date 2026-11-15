#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
. "$here/../fixtures/lib.sh"
init_repo
write_members
mkdir -p prompts
cat > prompts/t1.md <<'TASK'
Write the pull request body for the staged change in src/parser.py and reply with it.
TASK
