#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
. "$here/../fixtures/lib.sh"
init_repo
write_members
mkdir -p .admiral/untrusted
printf "Event: issue comment from an outside user.\n" > .admiral/untrusted/event.md
