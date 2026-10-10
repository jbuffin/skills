#!/bin/zsh
# usage: team-init.sh <run-name> <repo>
# Creates ${AGENT_TEAMS_DIR:-${CLAUDE_CONFIG_DIR:-~/.claude}/teams}/<run-name>/ with team.env, state.md, teammates.tsv,
# prompts/ and reports/, and prints the run directory and the resolved script directories of this skill, agent-teammates and run-preflight.
# Safe to re-run: never overwrites existing files.
# Exits 6, before creating anything, if agent-teammates, run-preflight or target-evaluation isn't installed next to this skill.
set -e
NAME=$1; WT=${2:A}
[[ -z $NAME || -z $WT ]] && { echo "usage: team-init.sh <run-name> <repo>"; exit 5; }
SKILL=${0:A:h:h}
# The skills this one runs alongside sit next to it; without them the paths below point nowhere.
missing=()
for dep in agent-teammates run-preflight target-evaluation; do
  [[ -f ${SKILL:h}/$dep/SKILL.md ]] || missing+=($dep)
done
if (( $#missing )); then
  echo "missing skills next to ${SKILL:t} in ${SKILL:h}: ${missing[*]}"
  echo "agent-team-build needs agent-teammates, run-preflight and target-evaluation installed alongside it."
  exit 6
fi
RUN=${AGENT_TEAMS_DIR:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/teams}/$NAME
mkdir -p $RUN/prompts $RUN/reports

CMUX_BIN=${CMUX_BUNDLED_CLI_PATH:-/Applications/cmux.app/Contents/Resources/bin/cmux}
# Only for optional cmux viewer panes (VIEWER=cmux). `cmux identify` beats CMUX_WORKSPACE_ID/CMUX_SURFACE_ID, which
# go stale in restored or background sessions: prefer the calling pane, else the focused one.
WS=; SF=
if [[ -x $CMUX_BIN ]]; then
  read -r WS SF < <($CMUX_BIN identify 2>/dev/null | python3 -c 'import json,sys
try: d=json.load(sys.stdin)
except Exception: d={}
c=d.get("caller") or d.get("focused") or {}
print(c.get("workspace_ref",""), c.get("surface_ref",""))' 2>/dev/null) || true
fi

if [[ ! -f $RUN/team.env ]]; then
  cat > $RUN/team.env <<EOF
# Read by every script in $SKILL/scripts. Edit freely.
RUN=$RUN
# The repository (any checkout of it). Nobody works here: every unit gets its own worktree
# (scripts/unit-worktree.sh), and teammates start in their unit's worktree.
REPO=$WT
WORKTREE=$WT
WORKTREES_DIR=$WT/.claude/worktrees
SKILL=$SKILL
SKILLS_DIR=${SKILL:h}
# Resolved script directories. Briefs and allow rules use these literal paths: a symlinked skills folder
# resolves to a different path, and an allow rule matches only the path typed.
TEAM_SCRIPTS=$SKILL/scripts
TEAMMATES_SCRIPTS=${SKILL:h}/agent-teammates/scripts
PREFLIGHT_SCRIPTS=${SKILL:h}/run-preflight/scripts
# Untracked files every unit worktree needs from the repository's checkout (git worktree add brings only tracked
# files): copy:<path> or clone:<path>, space separated, e.g. "copy:.env clone:node_modules". Fill from the profile.
WORKTREE_SETUP=""
# Ignored top-level names team-preflight.sh shouldn't flag as missing from WORKTREE_SETUP
WORKTREE_SETUP_SKIP=".DS_Store .vscode .idea coverage"
# Checked by run-preflight's preflight.sh. agent-teammates' teammate-tail.sh needs jq, and teammates use it to
# parse JSON from server and CLI calls.
REQUIRED_TOOLS="git gh python3 jq security curl"
# Teammates are Claude Code background sessions (agent-teammates). VIEWER: none | cmux | tmux; optional panes that
# attach to each teammate; closing one never stops it.
VIEWER=none
CMUX=$CMUX_BIN
# For VIEWER=cmux: the pane to split from, from \`cmux identify\`. Fix by hand if wrong.
CMUX_WORKSPACE=$WS
CMUX_SURFACE=$SF
MODEL=sonnet
PERMISSION_MODE=auto
CLAUDE_CONFIG_DIR=${CLAUDE_CONFIG_DIR:-$HOME/.claude}
# Fill from the profile:
# MODEL is the fallback for a teammate launched without --role. REQUIRE_ROLE=1 makes every launch pass --role or --model.
# MODEL_<ROLE> is the model for --role <role>; an empty one refuses that launch.
REQUIRE_ROLE=1
MODEL_BRIEF_CHECKER=opus
MODEL_TEST_WRITER=sonnet
MODEL_IMPLEMENTER=sonnet
MODEL_REVIEWER=opus
MODEL_TARGET_STEWARD=sonnet
MODEL_SCRIBE=sonnet
MODE=            # single | stack | independent | pr
BASE_BRANCH=
BRANCH_PREFIX=
CI_WORKFLOW=
# Evaluation target (target-evaluation skill): set what applies
TARGET_TYPE=
TARGET_URL=
# Keychain service names the run needs, space separated (never the values)
SECRETS=""
EOF
fi
[[ -f $RUN/state.md ]] || cat > $RUN/state.md <<'EOF'
# Run state (read this first on every start)

## Mode, phase, current unit

## Units (unit → branch → worktree → head SHA → PR)

## Acceptance trace (criterion from the source of truth → owning unit → test or scenario → status → evidence path)

## Ground rules (from the engineer)

## Decisions and assumptions (assumptions are reversible defaults taken without asking)

## Open questions for the engineer (with recommended default)

## Live teammates (name → session id → task)

## Review rounds per PR

## Carry-forward checks

## Misses (where a brief or decision was wrong)
EOF
touch $RUN/teammates.tsv
[[ -f $RUN/profile.md ]] || cp $SKILL/references/profile-template.md $RUN/profile.md
source $RUN/team.env
echo "run:       $RUN"
echo "team:      $TEAM_SCRIPTS"
echo "teammates: $TEAMMATES_SCRIPTS"
echo "preflight: $PREFLIGHT_SCRIPTS"
