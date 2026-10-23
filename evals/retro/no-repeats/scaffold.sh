#!/usr/bin/env bash
# Copy this case's fixture into the run's working directory. The retro writes its run
# directory under fixture/teams, so the copy has to be writable.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cp -R "$here/../fixtures/no-repeats" fixture
