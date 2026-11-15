#!/usr/bin/env bash
# A local repo with a spec and a set of config files: no issue to build, no PR to review, no feedback to answer.
set -euo pipefail
git init -q .
mkdir -p configs
cat > SPEC.md <<'SPEC'
# Config spec

1. Every config file sets `name`.
2. Every config file sets `timeout` to a number of seconds.
3. No config file sets `debug: true`.
SPEC
printf 'name: api\ntimeout: 30\n' > configs/api.yaml
printf 'name: worker\ndebug: true\n' > configs/worker.yaml
printf 'timeout: 10\n' > configs/cron.yaml
git add .
git -c user.name=eval -c user.email=eval@example.com commit -q -m "Add config spec and configs"
