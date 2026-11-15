#!/usr/bin/env bash
# A run directory for an ad hoc mission that is finished except for its end-of-run steps, in a local repo.
set -euo pipefail
git init -q .
printf '# Docs\n' > README.md
git add .
git -c user.name=eval -c user.email=eval@example.com commit -q -m "Add readme"
run="$PWD/teams/docs-audit-run"
mkdir -p "$run/missions" "$run/prompts" "$run/reports" xdg
cat > "$run/team.env" <<ENV
HARNESS=claude
REPO=$PWD
WORKTREE=$PWD
ENV
cat > "$run/missions/docs-audit.md" <<'MISSION'
---
name: docs-audit
pick-me-when: The engineer wants pages checked against a written checklist and the findings written down.
source-of-truth: The checklist file the engineer names.
task-force: [implementer, reviewer]
builder: implementer
checker: reviewer
stop-rule: FINDINGS.md lists every page that breaks a rule.
delivery: A findings file in the repo.
---

Run phase 1 of SKILL.md, then Phase 2 and Phase 3 of missions/build.md with the reviewer as the checker.
MISSION
cat > "$run/state.md" <<STATE
# Run state (read this first on every start)

## Mode, phase, current unit

mission: docs-audit
ad-hoc file: $run/missions/docs-audit.md
ship: none, the findings stay in the repo

## Units (head is a snapshot; git is the source of truth)

| unit | branch | worktree | base | head (as of) | PR | reviewed SHA | status | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| u1 | main | $PWD | main | none | none | none | closed | findings written |
STATE
