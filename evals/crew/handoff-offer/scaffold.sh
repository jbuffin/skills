#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
. "$here/../fixtures/lib.sh"
init_repo
cat > design.md <<'DESIGN'
# Export API design (settled)

Three parts, each its own PR, each reviewed, then evaluated against staging:

1. Schema: the export record format and its migration.
2. Endpoint: POST /exports and the worker that builds the file.
3. Client SDK: export calls in the Python and JS clients.
DESIGN
