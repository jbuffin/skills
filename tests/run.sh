#!/bin/zsh
# usage: tests/run.sh [--record] [name-filter]
# Deterministic checks for the team skills' harness seam (agent-teammates + commodore). Exits 0 only when every check
# passes. No network, no real `claude`, `codex` or `copilot`: tests/bin holds fakes (claude, codex, copilot, date, sleep,
# tmux, cmux, and a stat shim on Linux) that go first on PATH, and every script under test runs under `env -i` with an
# explicit environment inside a scratch directory.
#
#   D4  The scripts' behaviour matches goldens in tests/golden, recorded from the reference commit (dfb39c8) with
#       `tests/run.sh --record`. A golden holds the fake claude's argv log (with cwd), stdout, exit code, and the
#       files the scenario left in the team directory. Normalised: only the scratch directory's path (as @SB@) and
#       one `HARNESS=claude` line in team.env (added by team-init; stripped so a golden fits both sides of the change).
#       The clock is the fake date (FAKE_NOW) and file mtimes are set with touch, so nothing else varies.
#       Not compared: stderr.
#   C1  No shared script calls `claude` or `copilot`, or reads their transcript paths.
#   C2  Claude-only words appear only in the two harness-claude.md files. C6  The Markdown lint and the descriptions.
#   C3  team-init detects the harness. C4  team-preflight checks HARNESS against the environment.
#   S1  HARNESS comes from team.env alone. N1/N3/N6  team-init with a driver-less or test-only driver, and its re-runs.
#   D1  The advisor operation and the `ADVISOR n/a (<harness>)` path. D2  The Claude driver's shape.
#   D3  The Claude default table lives in commodore's harness-claude.md.
#   RESEND  retask.sh gives a teammate its next job through the driver's `send`.
#   CP  The Copilot driver: launch, resume, status, tail, close, the read-only flags, effort plumbing and the driver's
#       shape. Driven through the shared scripts against tests/bin/copilot.
#   CODEX  The Codex driver (turn-based): launch, send/retask, status, tail, stop, preflight, the read-only marker, effort
#       plumbing and the driver's shape. Assertion style (no goldens); `tests/run.sh codex` runs just these.
#   U4  Tail output per the driver contract, codex without its CLI, codex .state without PERM, copilot effort shape check,
#       REPO over WORKTREE. The RESEND and D2 checks read drivers/CONTRACT.md. The tail-* and init-* goldens were
#       edited by hand to match; `--record` would revert them.
#   U5  Copilot passes any well-formed effort through to the CLI (which validates it), and claude launch without its CLI.
#   ROLES role-skills.sh resolves the role-skill override layers (issue #71, ADR 0004), each driver's has-skill finds
#       installed skills, and team-preflight passes the warnings through. The preflight-* goldens were edited by hand
#       to add the security reviewer's warning; `--record` would revert them. `tests/run.sh roles` runs just these.
#   ADMIRAL  admiral-io.sh (publish an Admiral report or inbox item, read an answer) and schema-check.py, with the
#       two JSON Schemas in commodore/references that encode the Admiral contract (issue #116, admiral#112). Assertion
#       style; `tests/run.sh admiral` runs just these.
#   AUTOPILOT  Doc checks for the autopilot mode text in commodore (issue #116): the SKILL.md section, the gate pointers, the
#       mission files, the Codex and Copilot rows, and the lines that must read as before with it off (AC1). Assertion
#       style; `tests/run.sh autopilot` runs just these.
#   LINT  zsh -n on every zsh script and every sourced file without a shebang; shellcheck on the test fakes.
#
# --record rebuilds tests/golden from `git archive dfb39c8` and runs only the D4 scenarios.
# [name-filter] runs only the scenarios whose name contains it.
ROOT=${0:A:h:h}
REF=dfb39c8
GOLD=$ROOT/tests/golden
RECORD=; FILTER=
for a in "$@"; do case $a in --record) RECORD=1 ;; *) FILTER=$a ;; esac; done

SB=$(mktemp -d ${TMPDIR:-/tmp}/harness-tests.XXXXXX) || exit 1
SB=${SB:A}
trap 'reap_fakes; rm -rf $SB' EXIT
trap 'exit 130' INT TERM HUP

NOW=1790000000                       # the fake clock, 2026-09-21T13:33:20Z
SKILLS=$SB/src/skills/engineering
AT=$SKILLS/agent-teammates/scripts
CM=$SKILLS/commodore/scripts
TREE=$SKILLS
HL=                                  # the HARNESS line for team.env, when a scenario wants one

typeset -i NPASS=0 NFAIL=0
FAILED=()
pass() { NPASS+=1; echo "ok    $1"; }
fail() { NFAIL+=1; FAILED+=$1; echo "FAIL  $1"; [[ -n $2 ]] && print -r -- "$2" | sed 's/^/        /'; return 0; }
want() { [[ -z $FILTER || $1 == *$FILTER* ]]; }
norm() { sed "s#$SB#@SB@#g"; }

# ---- the scratch directory: fakes, and the skills under test -----------------------------------------------------
mkdir -p $SB/bin $SB/w $SB/src/skills $SB/actual $GOLD
cp $ROOT/tests/bin/* $SB/bin/
[[ $(uname -s) == Linux ]] || rm -f $SB/bin/stat
if [[ -n $RECORD ]]; then
  git -C $ROOT archive $REF skills/engineering | tar -x -C $SB/src || { echo "can't extract $REF"; exit 1; }
else
  cp -R $ROOT/skills/engineering $SB/src/skills/
fi
SANDBOX_PATH=$SB/bin:/usr/bin:/bin:/usr/sbin:/sbin

# ---- scenario helpers -----------------------------------------------------------------------------------------
# sc <name>: a fresh scenario directory and its base environment (BASE). Nothing leaks in from the caller.
sc() {
  NAME=${SCDIR:-$1}; SC=$SB/w/$NAME; D=$SC/run; RC=
  rm -rf $SC; mkdir -p $SC/{cwd,cfg,home,tmp,fake,repo,wt,teams} $D/prompts
  : > $SC/claude.log
  print -r -- "do the thing" > $D/prompts/t1.md
  BASE=( PATH=$SANDBOX_PATH HOME=$SC/home TMPDIR=$SC/tmp TZ=UTC LC_ALL=C GIT_CONFIG_GLOBAL=/dev/null
         GIT_CONFIG_NOSYSTEM=1 CLAUDE_CONFIG_DIR=$SC/cfg AGENT_TEAMS_DIR=$SC/teams
         CMUX_BUNDLED_CLI_PATH=$SC/no-cmux FAKE_LOG=$SC/claude.log FAKE_DIR=$SC/fake FAKE_NOW=$NOW )
}
# env_file [line...]: team.env for the scenario; extra lines go last, so they override.
env_file() {
  {
    print -r -- "RUN=$D"
    print -r -- "REPO=$SC/repo"
    print -r -- "WORKTREE=$SC/repo"
    print -r -- "WORKTREES_DIR=$SC/worktrees"
    print -r -- "SKILL=$TREE/commodore"
    print -r -- "SKILLS_DIR=$TREE"
    print -r -- "TEAM_SCRIPTS=$TREE/commodore/scripts"
    print -r -- "TEAMMATES_SCRIPTS=$TREE/agent-teammates/scripts"
    print -r -- "PREFLIGHT_SCRIPTS=$TREE/run-preflight/scripts"
    print -r -- 'REQUIRED_TOOLS="git"'
    print -r -- "VIEWER=none"
    print -r -- "MODEL=sonnet"
    print -r -- "ADVISOR=opus"
    print -r -- "PERMISSION_MODE=auto"
    print -r -- "CLAUDE_CONFIG_DIR=$SC/cfg"
    print -r -- "MODE=single"
    [[ -n $HL ]] && print -r -- "$HL"
    (( $# )) && print -rl -- "$@"
  } > $D/team.env
}
mk() { sc $1; env_file "$@[2,-1]"; }
reg() { print -r -- "$*" >> $D/teammates.tsv; }
# xrun [VAR=val ...] cmd args...: run in the scratch directory with only BASE (plus the given variables) in the environment.
xrun() {
  ( cd $SC/cwd && exec env -i $BASE "$@" ) > $SC/out 2> $SC/err
  RC=$?
}
# xrun_watch <polls> [VAR=val ...] cmd args...: run the watchdog until it has polled <polls> times, then stop it.
xrun_watch() {
  local polls=$1 i=0 pid; shift
  ( cd $SC/cwd && exec env -i $BASE FAKE_SLEEP_POLLS=$polls "$@" ) > $SC/out 2> $SC/err &
  pid=$!
  while [[ ! -e $SC/fake/sleep.reached ]] && (( i++ < 300 )) && kill -0 $pid 2>/dev/null; do /bin/sleep 0.1; done
  REACHED=; [[ -e $SC/fake/sleep.reached ]] && REACHED=1
  kill $pid 2>/dev/null; : > $SC/fake/sleep.release; wait $pid 2>/dev/null
  RC=-
}
settime() { local e=$1 s; shift; s=$(/bin/date -u -r $e +%Y%m%d%H%M.%S 2>/dev/null) || s=$(/bin/date -u -d @$e +%Y%m%d%H%M.%S); TZ=UTC touch -t $s "$@"; }
# mk_repo: the engineer's checkout (git identity set), the trust record, a probe stub, and a worktree for probes.
mk_repo() {
  env -i PATH=/usr/bin:/bin HOME=$SC/home GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 git init -q $SC/repo
  env -i PATH=/usr/bin:/bin HOME=$SC/home GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 git -C $SC/repo config user.email test@example.com
  print -r -- '{"projects": {"'$SC'/repo": {"hasTrustDialogAccepted": true}}}' > $SC/cfg/.claude.json
  printf '#!/bin/sh\necho "ADVISOR ON $2"\n' > $SC/probe-stub; chmod +x $SC/probe-stub
  printf '#!/bin/sh\necho "ADVISOR OFF $2: advisor unavailable (feature_disabled)"\n' > $SC/probe-stub-off; chmod +x $SC/probe-stub-off
  print -r -- "u1 branch-u1 $SC/wt" > $D/worktrees.tsv
}

serialize() {  # serialize <out-file> [dir]: the golden form of the finished scenario
  local out=$1 rd=${2:-$D} f
  {
    echo '## argv'; norm < $SC/claude.log
    echo '## stdout'; norm < $SC/out
    echo '## exit'; print -r -- "$RC"
    echo '## files'
    if [[ -d $rd ]]; then
      for f in ${(f)"$(cd $rd && find . -mindepth 1 | LC_ALL=C sort)"}; do
        if [[ -d $rd/$f ]]; then echo "$f/"; continue; fi
        echo "$f"
        case ${f:t} in
          profile.md) if cmp -s $rd/$f $SKILLS/commodore/references/profile-template.md; then echo '  (copy of references/profile-template.md)'; else echo '  (differs from references/profile-template.md)'; fi ;;
          team.env)   awk '!d && $0=="HARNESS=claude" {d=1; next} 1' $rd/$f | norm | sed 's/^/  | /' ;;
          *)          norm < $rd/$f | sed 's/^/  | /' ;;
        esac
      done
    fi
  } > $out
}
# d4 <scenario> [golden] [dir]: compare the finished scenario to its golden, or record the golden.
d4() {
  local g=${2:-$1} d
  serialize $SB/actual/$1.txt $3
  if [[ -n $RECORD ]]; then [[ $g == $1 ]] && { cp $SB/actual/$1.txt $GOLD/$g.txt; echo "recorded $g"; }; return; fi
  if [[ ! -f $GOLD/$g.txt ]]; then fail "D4 $1" "no golden tests/golden/$g.txt"; return; fi
  if d=$(diff -u $GOLD/$g.txt $SB/actual/$1.txt); then pass "D4 $1"; else fail "D4 $1" "$(print -r -- $d | head -24)"; fi
}
d4_watch() {  # d4_watch <scenario>: like d4, after checking the watcher reached its last poll
  if [[ -z $REACHED ]]; then fail "D4 $1" "the watcher never reached its poll limit; stdout: $(<$SC/out) stderr: $(<$SC/err)"; return; fi
  d4 $1
}

# ---- sandbox sanity -------------------------------------------------------------------------------------------
sc sanity
if [[ -z $RECORD ]]; then
  got=$(env -i PATH=$SANDBOX_PATH /bin/sh -c 'command -v claude')
  [[ $got == $SB/bin/claude ]] && pass "SANDBOX claude resolves to the fake" || fail "SANDBOX claude resolves to the fake" "got '$got'"
  got=$(env -i PATH=$SANDBOX_PATH /bin/sh -c 'command -v codex')
  [[ $got == $SB/bin/codex ]] && pass "SANDBOX codex resolves to the fake" || fail "SANDBOX codex resolves to the fake" "got '$got'"
  got=$(env -i PATH=$SANDBOX_PATH /bin/sh -c 'command -v copilot')
  [[ $got == $SB/bin/copilot ]] && pass "SANDBOX copilot resolves to the fake" || fail "SANDBOX copilot resolves to the fake" "got '$got'"
fi

# ======================================================================================================================
# D4: no behaviour change. Goldens come from dfb39c8.
# ======================================================================================================================

# ---- launch-teammate.sh ------------------------------------------------------------------------------------------
want launch-plain && { mk launch-plain; xrun $AT/launch-teammate.sh $D t1 $SC/wt; d4 launch-plain; }
want launch-plain-harness-claude && { HL=HARNESS=claude SCDIR=launch-plain; mk launch-plain-harness-claude; HL=; SCDIR=; xrun $AT/launch-teammate.sh $D t1 $SC/wt; d4 launch-plain-harness-claude launch-plain; }
want launch-readonly && { mk launch-readonly; xrun $AT/launch-teammate.sh --read-only $D t1 $SC/wt; d4 launch-readonly; }
want launch-role && { mk launch-role MODEL_TEST_WRITER=opus; xrun $AT/launch-teammate.sh --role test-writer $D t1 $SC/wt; d4 launch-role; }
want launch-role-unset && { mk launch-role-unset; xrun $AT/launch-teammate.sh --role test-writer $D t1 $SC/wt; d4 launch-role-unset; }
want launch-require-role && { mk launch-require-role REQUIRE_ROLE=1; xrun $AT/launch-teammate.sh $D t1 $SC/wt; d4 launch-require-role; }
want launch-model-flag && { mk launch-model-flag; xrun $AT/launch-teammate.sh --model haiku $D t1 $SC/wt; d4 launch-model-flag; }
want launch-advisor-none && { mk launch-advisor-none ADVISOR=none; xrun $AT/launch-teammate.sh $D t1 $SC/wt; d4 launch-advisor-none; }
want launch-unit-lookup && { mk launch-unit-lookup; print -r -- "u1 branch-u1 $SC/wt" > $D/worktrees.tsv; xrun $AT/launch-teammate.sh $D t1 u1; d4 launch-unit-lookup; }
want launch-ansi && { mk launch-ansi; xrun FAKE_BG_ANSI=1 $AT/launch-teammate.sh $D t1 $SC/wt; d4 launch-ansi; }
want launch-nobg-notrust && { mk launch-nobg-notrust; xrun FAKE_BG=notrust $AT/launch-teammate.sh --read-only $D t1 $SC/wt; d4 launch-nobg-notrust; }
want launch-nobg-other && { mk launch-nobg-other; xrun FAKE_BG=fail $AT/launch-teammate.sh $D t1 $SC/wt; d4 launch-nobg-other; }
want launch-noid && { mk launch-noid; xrun FAKE_BG=noid $AT/launch-teammate.sh $D t1 $SC/wt; d4 launch-noid; }
want launch-list-fails && { mk launch-list-fails; xrun FAKE_AGENTS_FAIL=1 $AT/launch-teammate.sh $D t1 $SC/wt; d4 launch-list-fails; }
want launch-already-live && {
  mk launch-already-live
  print -r -- '[{"id": "aaaa1111", "name": "t1", "status": "working", "state": "working"}]' > $SC/fake/agents.json
  xrun $AT/launch-teammate.sh $D t1 $SC/wt; d4 launch-already-live
}
want launch-tmux-viewer && { mk launch-tmux-viewer VIEWER=tmux; xrun TMUX=/fake/tmux,1,0 $AT/launch-teammate.sh $D t1 $SC/wt; d4 launch-tmux-viewer; }
want launch-cmux-viewer && {
  mk launch-cmux-viewer VIEWER=cmux CMUX=$SB/bin/cmux CMUX_WORKSPACE=workspace:2 CMUX_SURFACE=surface:1
  xrun $AT/launch-teammate.sh $D t1 $SC/wt; d4 launch-cmux-viewer
}
want launch-repo-checkout && { mk launch-repo-checkout; xrun $AT/launch-teammate.sh $D t1 $SC/repo; d4 launch-repo-checkout; }
want launch-missing-prompt && { mk launch-missing-prompt; xrun $AT/launch-teammate.sh $D t1 $SC/wt $SC/nope.md; d4 launch-missing-prompt; }
want launch-invalid-name && { mk launch-invalid-name; xrun $AT/launch-teammate.sh $D .bad $SC/wt; d4 launch-invalid-name; }

# ---- retasked.sh, close-teammate.sh ---------------------------------------------------------------------------------
want retasked-ok && { mk retasked-ok; reg t1 c51dbe46 1789999000 - $SC/wt; xrun $AT/retasked.sh $D t1; d4 retasked-ok; }
want retasked-closed && { mk retasked-closed; reg t1 c51dbe46 closed - $SC/wt; xrun $AT/retasked.sh $D t1; d4 retasked-closed; }
want retasked-unregistered && { mk retasked-unregistered; xrun $AT/retasked.sh $D ghost; d4 retasked-unregistered; }
want close-stopped && { mk close-stopped; reg t1 c51dbe46 1789999000 - $SC/wt; xrun $AT/close-teammate.sh $D t1; d4 close-stopped; }
want close-not-running && { mk close-not-running; reg t1 c51dbe46 1789999000 - $SC/wt; xrun FAKE_STOP_RC=1 $AT/close-teammate.sh $D t1; d4 close-not-running; }
want close-stop-rc9 && { SCDIR=close-not-running; mk close-stop-rc9; SCDIR=; reg t1 c51dbe46 1789999000 - $SC/wt; xrun FAKE_STOP_RC=9 $AT/close-teammate.sh $D t1; d4 close-stop-rc9 close-not-running; }
want close-mixed && { mk close-mixed; reg t1 c51dbe46 1789999000 - $SC/wt; xrun $AT/close-teammate.sh $D ghost t1; d4 close-mixed; }
want close-viewer-tmux && { mk close-viewer-tmux; reg t1 c51dbe46 1789999000 %7 $SC/wt; xrun $AT/close-teammate.sh $D t1; d4 close-viewer-tmux; }
want close-viewer-cmux && {
  mk close-viewer-cmux CMUX=$SB/bin/cmux CMUX_WORKSPACE=workspace:2
  reg t1 c51dbe46 1789999000 surface:5 $SC/wt; xrun $AT/close-teammate.sh $D t1; d4 close-viewer-cmux
}

# ---- teammate-tail.sh -------------------------------------------------------------------------------------------
tail_fixture() {
  mkdir -p $SC/cfg/projects/p1
  {
    echo '{"type":"user","message":{"content":"go"}}'
    echo '{"type":"assistant","message":{"content":[{"type":"text","text":"Reading the brief"},{"type":"tool_use","name":"Read","input":{"file_path":"/x/brief.md"}}]}}'
    echo '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"ls -la","description":"List files"}}]}}'
    echo '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"git status"}}]}}'
    echo '{"type":"assistant","message":{"content":[{"type":"text","text":"All done here"}]}}'
  } > $SC/cfg/projects/p1/b7e2a911.jsonl
  settime $((NOW - 420)) $SC/cfg/projects/p1/b7e2a911.jsonl
  reg t1 b7e2a911 1789999000 - $SC/wt
}
want tail-ok && { mk tail-ok; tail_fixture; xrun $AT/teammate-tail.sh $D t1; d4 tail-ok; }
want tail-by-id && { mk tail-by-id; tail_fixture; xrun $AT/teammate-tail.sh $D b7e2a911; d4 tail-by-id; }
want tail-n && { mk tail-n; tail_fixture; xrun $AT/teammate-tail.sh $D t1 2; d4 tail-n; }
want tail-missing && { mk tail-missing; reg t1 b7e2a911 1789999000 - $SC/wt; xrun $AT/teammate-tail.sh $D t1; d4 tail-missing; }

# ---- watch-teammates.sh ---------------------------------------------------------------------------------------------
# One teammate per scenario. The fake claude answers poll n from agents-all.<n>.json (the last file repeats), the fake
# sleep stops the watcher after <polls> polls, and the clock is NOW.
agents_all() {  # agents_all <n> <id> <name> <status> <state>
  print -r -- "[{\"id\": \"$2\", \"name\": \"$3\", \"status\": \"$4\", \"state\": \"$5\"}]" > $SC/fake/agents-all.$1.json
}
want watch-done && {
  mk watch-done; mkdir -p $D/reports; reg t1 d0e1f2a3 $((NOW - 600)) - $SC/wt
  : > $D/reports/t1.done; settime $((NOW - 100)) $D/reports/t1.done
  agents_all 1 d0e1f2a3 t1 idle done
  xrun_watch 1 $AT/watch-teammates.sh $D; d4_watch watch-done
}
want watch-blocked && {
  mk watch-blocked; reg t1 d0e1f2a3 $((NOW - 600)) - $SC/wt
  agents_all 1 d0e1f2a3 t1 idle blocked
  xrun_watch 3 $AT/watch-teammates.sh $D; d4_watch watch-blocked
}
want watch-blocked-once && {
  mk watch-blocked-once; reg t1 d0e1f2a3 $((NOW - 600)) - $SC/wt
  agents_all 1 d0e1f2a3 t1 idle blocked; agents_all 2 d0e1f2a3 t1 working working
  xrun_watch 3 $AT/watch-teammates.sh $D; d4_watch watch-blocked-once
}
want watch-stall && {
  mk watch-stall; reg t1 d0e1f2a3 $((NOW - 1200)) - $SC/wt
  mkdir -p $SC/cfg/projects/p1; : > $SC/cfg/projects/p1/d0e1f2a3.jsonl; settime $((NOW - 900)) $SC/cfg/projects/p1/d0e1f2a3.jsonl
  agents_all 1 d0e1f2a3 t1 working working
  xrun_watch 1 $AT/watch-teammates.sh $D; d4_watch watch-stall
}
want watch-stale && {
  mk watch-stale; reg t1 d0e1f2a3 $((NOW - 3000)) - $SC/wt
  mkdir -p $SC/cfg/projects/p1; : > $SC/cfg/projects/p1/d0e1f2a3.jsonl; settime $((NOW - 60)) $SC/cfg/projects/p1/d0e1f2a3.jsonl
  agents_all 1 d0e1f2a3 t1 working working
  xrun_watch 1 $AT/watch-teammates.sh $D; d4_watch watch-stale
}
want watch-gone-stopped && {
  mk watch-gone-stopped; reg t1 d0e1f2a3 $((NOW - 600)) - $SC/wt
  agents_all 1 d0e1f2a3 t1 stopped stopped
  xrun_watch 1 $AT/watch-teammates.sh $D; d4_watch watch-gone-stopped
}
want watch-gone-missing && {
  mk watch-gone-missing; reg t1 d0e1f2a3 $((NOW - 600)) - $SC/wt
  agents_all 1 ffffffff other idle idle
  xrun_watch 1 $AT/watch-teammates.sh $D; d4_watch watch-gone-missing
}
want watch-closed && {
  mk watch-closed; reg t1 d0e1f2a3 $((NOW - 600)) - $SC/wt; reg t1 d0e1f2a3 closed - $SC/wt
  agents_all 1 d0e1f2a3 t1 stopped stopped
  xrun_watch 1 $AT/watch-teammates.sh $D; d4_watch watch-closed
}
want watch-list-fails && {
  mk watch-list-fails; reg t1 d0e1f2a3 $((NOW - 600)) - $SC/wt
  xrun_watch 2 FAKE_AGENTS_FAIL=1 $AT/watch-teammates.sh $D; d4_watch watch-list-fails
}

# ---- advisor-probe.sh ---------------------------------------------------------------------------------------------
probe_sc() { mk $1 "${@[2,-1]}"; print -r -- "u1 branch-u1 $SC/wt" > $D/worktrees.tsv; }
want probe-on && { probe_sc probe-on; xrun FAKE_PROBE=on FAKE_BG_ID=9a1b0c2d ADVISOR_PROBE_TIMEOUT=20 $CM/advisor-probe.sh $D sonnet; d4 probe-on; }
want probe-off-unavailable && { probe_sc probe-off-unavailable; xrun FAKE_PROBE=off FAKE_BG_ID=9a1b0c2d ADVISOR_PROBE_TIMEOUT=20 $CM/advisor-probe.sh $D sonnet; d4 probe-off-unavailable; }
want probe-none && { probe_sc probe-none; xrun FAKE_BG_ID=9a1b0c2d ADVISOR_PROBE_TIMEOUT=0 $CM/advisor-probe.sh $D sonnet; d4 probe-none; }
want probe-advisor-none && { probe_sc probe-advisor-none ADVISOR=none; xrun FAKE_PROBE=on FAKE_BG_ID=9a1b0c2d ADVISOR_PROBE_TIMEOUT=20 $CM/advisor-probe.sh $D opus; d4 probe-advisor-none; }
want probe-bg-fails && { probe_sc probe-bg-fails; xrun FAKE_BG=notrust FAKE_BG_ID=9a1b0c2d $CM/advisor-probe.sh $D sonnet; d4 probe-bg-fails; }
want probe-no-dir && { mk probe-no-dir WORKTREES_DIR=; xrun $CM/advisor-probe.sh $D sonnet; d4 probe-no-dir; }
want probe-list-fails && { probe_sc probe-list-fails; xrun FAKE_AGENTS_FAIL=1 $CM/advisor-probe.sh $D sonnet; d4 probe-list-fails; }
want probe-live-name && {
  probe_sc probe-live-name
  print -r -- '[{"id": "aaaa1111", "name": "advisor-probe-sonnet", "status": "working", "state": "working"}]' > $SC/fake/agents.json
  xrun $CM/advisor-probe.sh $D sonnet; d4 probe-live-name
}
want probe-hints && {
  probe_sc probe-hints
  xrun DISABLE_TELEMETRY=1 ANTHROPIC_BASE_URL=http://gateway.invalid FAKE_BG_ID=9a1b0c2d ADVISOR_PROBE_TIMEOUT=0 $CM/advisor-probe.sh $D sonnet; d4 probe-hints
}

# ---- team-preflight.sh --------------------------------------------------------------------------------------------
# A fixture the reference preflight passes (git identity, trusted repo, stub probe), so a FAIL means something changed.
pf_sc() { mk $1 "ADVISOR_PROBE=$SB/w/${SCDIR:-$1}/probe-stub" "${@[2,-1]}"; mk_repo; }
want preflight-ok && { pf_sc preflight-ok; xrun CLAUDECODE=1 $CM/team-preflight.sh $D; d4 preflight-ok; }
want preflight-ok-harness-claude && { HL=HARNESS=claude SCDIR=preflight-ok; pf_sc preflight-ok-harness-claude; HL=; SCDIR=; xrun CLAUDECODE=1 $CM/team-preflight.sh $D; d4 preflight-ok-harness-claude preflight-ok; }
want preflight-two-models && { pf_sc preflight-two-models MODEL_REVIEWER=opus; xrun CLAUDECODE=1 $CM/team-preflight.sh $D; d4 preflight-two-models; }
want preflight-probe-off && { pf_sc preflight-probe-off "ADVISOR_PROBE=$SB/w/preflight-probe-off/probe-stub-off"; xrun CLAUDECODE=1 $CM/team-preflight.sh $D; d4 preflight-probe-off; }
want preflight-advisor-none && { pf_sc preflight-advisor-none ADVISOR=none; xrun CLAUDECODE=1 $CM/team-preflight.sh $D; d4 preflight-advisor-none; }
want preflight-real-probe && {
  mk preflight-real-probe; mk_repo
  xrun CLAUDECODE=1 FAKE_PROBE=on FAKE_BG_ID=9a1b0c2d ADVISOR_PROBE_TIMEOUT=20 $CM/team-preflight.sh $D; d4 preflight-real-probe
}
want preflight-no-claude && { pf_sc preflight-no-claude; xrun CLAUDECODE=1 PATH=/usr/bin:/bin:/usr/sbin:/sbin $CM/team-preflight.sh $D; d4 preflight-no-claude; }
want preflight-agents-fail && { pf_sc preflight-agents-fail; xrun CLAUDECODE=1 FAKE_AGENTS_FAIL=1 $CM/team-preflight.sh $D; d4 preflight-agents-fail; }
want preflight-no-trust && { pf_sc preflight-no-trust; rm -f $SC/cfg/.claude.json; xrun CLAUDECODE=1 $CM/team-preflight.sh $D; d4 preflight-no-trust; }

# ---- team-init.sh --------------------------------------------------------------------------------------------------
want init-claude && { sc init-claude; xrun CLAUDECODE=1 $CM/team-init.sh run1 $SC/repo; d4 init-claude init-claude $SC/teams/run1; }
want init-rerun && {
  sc init-rerun; xrun CLAUDECODE=1 $CM/team-init.sh run1 $SC/repo; xrun CLAUDECODE=1 $CM/team-init.sh run1 $SC/repo
  d4 init-rerun init-rerun $SC/teams/run1
}
want init-missing-skills && {
  sc init-missing-skills; cp -R $SKILLS $SB/src-noskills; rm -rf $SB/src-noskills/run-preflight
  xrun CLAUDECODE=1 $SB/src-noskills/commodore/scripts/team-init.sh run1 $SC/repo; d4 init-missing-skills init-missing-skills $SC/teams
}

[[ -n $RECORD ]] && { echo "recorded goldens from $REF into tests/golden"; exit 0; }

# ======================================================================================================================
# RESEND: retask.sh gives a registered teammate its next job through the driver's `send` (SEND=script harnesses).
# The test driver `other` lives in a scratch copy of the skills tree, never in the shipped one: its `send` logs its argv
# to $SEND_LOG (and can fail or be absent), its `status` reports the teammate blocked, and its driver.env varies.
# ======================================================================================================================
RT=$SB/src-resend; RAT=$RT/agent-teammates/scripts
rdrv() {  # rdrv <ok|fail|none> <driver.env line...|NOENV>: rebuild the test driver in the scratch tree
  local m=$1 dd=$RT/agent-teammates/scripts/drivers/other; shift
  rm -rf $dd; mkdir -p $dd
  [[ $1 == NOENV ]] || print -rl -- "$@" > $dd/driver.env
  case $m in
    ok)   printf '#!/bin/sh\n{ printf send; for a in "$@"; do printf " [%%s]" "$a"; done; echo; } >> "${SEND_LOG:-/dev/null}"\nexit 0\n' > $dd/send ;;
    fail) printf '#!/bin/sh\n{ printf send; for a in "$@"; do printf " [%%s]" "$a"; done; echo; } >> "${SEND_LOG:-/dev/null}"\necho "driver says: session $2 could not be started"\nexit 3\n' > $dd/send ;;
  esac
  [[ -f $dd/send ]] && chmod +x $dd/send
  printf '#!/bin/sh\necho "d0e1f2a3 idle blocked -"\n' > $dd/status; chmod +x $dd/status
}
rs() {  # rs <scenario>: a run with HARNESS=other, t1 registered (viewer %7), a message file, and a snapshot of the registry
  TREE=$RT; mk $1 HARNESS=other; TREE=$SKILLS
  reg t1 d0e1f2a3 $((NOW - 600)) %7 $SC/wt
  print -r -- "next job" > $SC/msg.md; : > $SC/send.log; cp $D/teammates.tsv $SC/tsv.before
}
P=()
verdict() { (( $#P )) && fail "$1" "${(j:; :)P}" || pass "$1"; P=(); }
tsv_same() { cmp -s $D/teammates.tsv $SC/tsv.before || P+="teammates.tsv changed: $(diff $SC/tsv.before $D/teammates.tsv | tr '\n' '|')"; }
no_send() { [[ -s $SC/send.log ]] && P+="send ran: $(<$SC/send.log)"; return 0; }
out_has() { [[ "$(cat $SC/out $SC/err)" == *$1* ]] || P+="output lacks '$1': $(cat $SC/out $SC/err | head -c 300 | tr '\n' '|')"; }

want resend && {
  cp -R $SKILLS $RT
  OKENV=('# SEND=tool in a comment must not count' 'LIVE_MESSAGING=0' 'SEND=script')

  # AC1: send gets the session id and the message file; the registry gets the row retasked.sh would append.
  rdrv ok $OKENV; rs resend-ok
  xrun SEND_LOG=$SC/send.log $RAT/retask.sh $D t1 $SC/msg.md
  [[ $RC == 0 ]] || P+="exit $RC (want 0): $(cat $SC/out $SC/err | head -c 300)"
  [[ $(<$SC/send.log) == "send [$D] [d0e1f2a3] [$SC/msg.md]" ]] || P+="send argv: '$(<$SC/send.log)' (want send [<team-dir>] [d0e1f2a3] [<message-file>])"
  [[ $(tail -1 $D/teammates.tsv) == "t1 d0e1f2a3 $NOW %7 $SC/wt" && $(wc -l < $D/teammates.tsv) -eq 2 ]] || P+="registry: $(tr '\n' '|' < $D/teammates.tsv) (want the old row, then t1 d0e1f2a3 $NOW %7 $SC/wt)"
  out_has t1; out_has d0e1f2a3
  verdict "RESEND SEND=script: send gets the session id and message file, one retasked.sh-style row, confirmation"

  # AC1, watchdog: the old .done marker stops counting after retask.sh. Control: without it the marker is still reported.
  watch_sc() {
    rdrv ok $OKENV; rs $1; mkdir -p $D/reports; : > $D/reports/t1.done; settime $((NOW - 100)) $D/reports/t1.done
    print -r -- "$D/reports/t1.done $((NOW - 100))" > $D/.watch-seen
  }
  watch_sc resend-watch
  xrun SEND_LOG=$SC/send.log $RAT/retask.sh $D t1 $SC/msg.md; retask_rc=$RC
  xrun_watch 3 $RAT/watch-teammates.sh $D
  [[ $retask_rc == 0 ]] || P+="retask.sh exit $retask_rc (want 0)"
  [[ -n $REACHED ]] || P+="the watcher never reached its poll limit"
  grep -qx 'BLOCKED t1 d0e1f2a3' $SC/out || P+="no 'BLOCKED t1 d0e1f2a3' after retask.sh; stdout: $(tr '\n' '|' < $SC/out)"
  grep -q '^DONE t1' $SC/out && P+="the old marker was reported DONE after retask.sh"
  verdict "RESEND after retask.sh the watchdog doesn't report the old marker as DONE, and fires BLOCKED"
  watch_sc resend-watch-control
  xrun_watch 3 $RAT/watch-teammates.sh $D
  [[ -n $REACHED && ! -s $SC/out ]] && pass "RESEND control: without retask.sh the old marker counts and nothing fires" || fail "RESEND control: without retask.sh the old marker counts and nothing fires" "reached: ${REACHED:-no}; stdout: $(tr '\n' '|' < $SC/out)"

  # AC2: a failing send leaves the registry byte-for-byte alone; its exit code and message come through (D3).
  rdrv fail $OKENV; rs resend-fail
  xrun SEND_LOG=$SC/send.log $RAT/retask.sh $D t1 $SC/msg.md
  [[ $RC == 3 ]] || P+="exit $RC (want send's own code, 3)"
  [[ -s $SC/send.log ]] || P+="send never ran"
  tsv_same; out_has "driver says: session d0e1f2a3 could not be started"
  verdict "RESEND failing send: registry unchanged, send's exit code and message come through"

  # AC3 / D2: refusals. Nothing is sent and the registry doesn't change.
  rdrv ok $OKENV; rs resend-unregistered
  xrun SEND_LOG=$SC/send.log $RAT/retask.sh $D ghost $SC/msg.md
  [[ $RC == 5 ]] || P+="exit $RC (want 5)"; out_has "ghost is not registered in $D/teammates.tsv"; no_send; tsv_same
  verdict "RESEND unregistered teammate: retasked.sh's message, exit 5, nothing sent"

  rdrv ok $OKENV; rs resend-closed; reg t1 d0e1f2a3 closed - $SC/wt; cp $D/teammates.tsv $SC/tsv.before
  xrun SEND_LOG=$SC/send.log $RAT/retask.sh $D t1 $SC/msg.md
  [[ $RC == 5 ]] || P+="exit $RC (want 5)"; out_has "t1 is closed; launch a new teammate instead"; no_send; tsv_same
  verdict "RESEND closed teammate: retasked.sh's message, exit 5, nothing sent"

  rdrv ok $OKENV; rs resend-usage
  xrun SEND_LOG=$SC/send.log $RAT/retask.sh $D t1
  [[ $RC == 5 ]] || P+="exit $RC (want 5)"; out_has "usage: retask.sh"; no_send; tsv_same
  verdict "RESEND missing argument: usage, exit 5, nothing sent"

  rdrv ok $OKENV; rs resend-no-message-file
  xrun SEND_LOG=$SC/send.log $RAT/retask.sh $D t1 $SC/nope.md
  [[ $RC != 0 && $RC != 127 && $RC != 126 ]] || P+="exit $RC (want a refusal)"; out_has "nope.md"; no_send; tsv_same
  verdict "RESEND missing message file: refused before send, registry unchanged"

  rdrv ok $OKENV; rs resend-empty-message; : > $SC/msg.md
  xrun SEND_LOG=$SC/send.log $RAT/retask.sh $D t1 $SC/msg.md
  [[ $RC != 0 && $RC != 127 && $RC != 126 ]] || P+="exit $RC (want a refusal)"; out_has "msg.md"; no_send; tsv_same
  verdict "RESEND empty message file: refused before send, registry unchanged"

  # D2's order: unregistered/closed come before the message file, which comes before the SEND value.
  rdrv ok $OKENV; rs resend-order-unregistered
  xrun SEND_LOG=$SC/send.log $RAT/retask.sh $D ghost $SC/nope.md
  [[ $RC == 5 ]] || P+="exit $RC (want 5)"; out_has "ghost is not registered"; no_send
  verdict "RESEND order: an unregistered name is refused before the message file is checked"
  rdrv ok 'SEND=bogus'; rs resend-order-message; : > $SC/msg.md
  xrun SEND_LOG=$SC/send.log $RAT/retask.sh $D t1 $SC/msg.md
  [[ $RC != 0 && $RC != 127 && $RC != 126 ]] || P+="exit $RC (want a refusal)"
  [[ "$(cat $SC/out $SC/err)" == *driver.env* ]] && P+="an empty message was refused for the SEND value: $(cat $SC/out $SC/err | head -c 200 | tr '\n' '|')"
  no_send; tsv_same
  verdict "RESEND order: an empty message file is refused before the SEND value is read"

  # AC4 / D3: SEND=tool sends nothing (even if the driver has a send), changes nothing, exits 4, and points at the
  # harness's own tool and retasked.sh. The message names $HARNESS.
  rdrv ok 'SEND=tool'; rs resend-tool
  xrun SEND_LOG=$SC/send.log $RAT/retask.sh $D t1 $SC/msg.md
  [[ $RC == 4 ]] || P+="exit $RC (want 4)"; no_send; tsv_same
  out_has "references/harness-other.md"; out_has "retasked.sh"
  verdict "RESEND SEND=tool: nothing sent, registry unchanged, exit 4, names harness-<HARNESS>.md and retasked.sh"
  sc resend-claude; env_file; reg t1 c51dbe46 1789999000 - $SC/wt; print -r -- "next job" > $SC/msg.md; cp $D/teammates.tsv $SC/tsv.before
  xrun $AT/retask.sh $D t1 $SC/msg.md
  [[ $RC == 4 ]] || P+="exit $RC (want 4)"; [[ -s $SC/claude.log ]] && P+="claude was called: $(head -c 200 $SC/claude.log)"; tsv_same
  out_has "references/harness-claude.md"; out_has "retasked.sh"
  verdict "RESEND Claude driver (SEND=tool): no claude call, registry unchanged, exit 4, the use-the-harness's-tool message"

  # AC5: SEND=script without a send executable.
  rdrv none $OKENV; rs resend-nosend
  xrun SEND_LOG=$SC/send.log $RAT/retask.sh $D t1 $SC/msg.md
  [[ $RC == 5 ]] || P+="exit $RC (want 5)"; tsv_same; out_has "no send operation"
  verdict "RESEND SEND=script with no send executable: exit 5, registry unchanged"

  # D1: SEND comes from the ^SEND= line of driver.env; anything else is refused with exit 5 and a message naming the file.
  d1_case() {  # d1_case <check name> <scenario> <driver.env line...|NOENV>
    local nm=$1 s=$2; shift 2
    rdrv ok $@; rs $s
    xrun SEND_LOG=$SC/send.log $RAT/retask.sh $D t1 $SC/msg.md
    [[ $RC == 5 ]] || P+="exit $RC (want 5)"; no_send; tsv_same; out_has "driver.env"
    verdict "$nm"
  }
  d1_case "RESEND D1: no driver.env is refused, naming the file" resend-d1-nofile NOENV
  d1_case "RESEND D1: driver.env with SEND= only in a comment is refused" resend-d1-comment '# SEND=script' 'LIVE_MESSAGING=0'
  d1_case "RESEND D1: an unknown SEND value is refused" resend-d1-bogus 'SEND=bogus'
}

# RESEND docs: the contract's send text, and SKILL.md. Key phrases only.
want resend && {
  DE=$ROOT/skills/engineering/agent-teammates/scripts/drivers/claude/driver.env
  CT=$ROOT/skills/engineering/agent-teammates/scripts/drivers/CONTRACT.md
  snd=$(awk '/^### send$/{p=1; next} p && /^#/{p=0} p{print}' $CT)
  [[ -n $snd ]] || P+="no '### send' section in ${CT#$ROOT/}"
  print -r -- $snd | grep -qi 'resum' || P+="the send text doesn't say it resumes the session"
  print -r -- $snd | grep -qi 'exit' || P+="the send text doesn't mention the process having exited"
  verdict "RESEND contract send text: gives the session its next job, resuming it if its process exited"
  print -r -- $snd | grep -qiE 'without waiting' || P+="the send text doesn't say it returns without waiting for the turn"
  print -r -- $snd | grep -qiE 'once .*(started|start)' || P+="the send text doesn't say it returns once the job has started"
  verdict "RESEND contract send text: returns once the job has started, without waiting for the turn"
  print -r -- $snd | grep -qiE 'non-zero' && print -r -- $snd | grep -qiE "couldn't|could not|cannot|can't" || P+="the send text doesn't say it exits non-zero if it couldn't start the job"
  verdict "RESEND contract send text: exits non-zero if it couldn't start the job"
  sed -n 1,3p $CT | grep -q 'retask\.sh' || P+="the contract's opening doesn't mention retask.sh reading the SEND= line"
  verdict "RESEND contract opening says retask.sh reads the SEND= line"
  [[ ! -e ${DE:h}/send ]] && grep -q '^SEND=tool$' $DE || P+="the Claude driver must keep SEND=tool and have no send executable"
  verdict "RESEND the Claude driver keeps SEND=tool and no send executable"

  sm=$ROOT/skills/engineering/agent-teammates/SKILL.md
  grep -qE '^<teammates>/retask\.sh ' $sm || P+="the Launch, re-task, close command list has no '<teammates>/retask.sh' line"
  verdict "RESEND SKILL.md command list has retask.sh"
  para=$(awk -v RS= '/LIVE_MESSAGING=0/ && /retasked\.sh/' $sm)
  [[ -n $para ]] || P+="no paragraph mentions LIVE_MESSAGING=0 and retasked.sh"
  print -r -- $para | grep -qE 'retask\.sh' || P+="the re-tasking paragraph never mentions retask.sh"
  print -r -- $para | grep -q 'SEND=script' || P+="the re-tasking paragraph never mentions SEND=script"
  verdict "RESEND SKILL.md re-tasking section points LIVE_MESSAGING=0 and SEND=script at retask.sh"
}

# commodore re-tasks a live teammate the way agent-teammates' re-tasking section says. Key phrases only.
want commodore-retask && {
  CMD=$ROOT/skills/engineering/commodore
  mb=$CMD/references/mission-build.md
  phase2=$(awk '/^## Phase 2/{p=1; next} p && /^## /{p=0} p' $mb)
  rule=$(print -r -- $phase2 | awk '/^1\. /{exit} {print}')
  print -r -- $rule | grep -q 'agent-teammates' || P+="the Phase 2 text before the per-unit steps never mentions agent-teammates"
  print -r -- $rule | grep -qiE 're-?task' || P+="the Phase 2 text before the per-unit steps never says re-task"
  verdict "COMMODORE-RETASK Phase 2 has one rule: every re-task of a live teammate follows agent-teammates' re-tasking section"
  step5=$(print -r -- $phase2 | grep -E '^5\. ')
  [[ -n $step5 ]] || P+="no Phase 2 step 5"
  print -r -- $step5 | grep -qE 'retask\.sh' || P+="step 5 never mentions retask.sh"
  print -r -- $step5 | grep -q 'agent-teammates' || P+="step 5 never points at agent-teammates"
  print -r -- $step5 | grep -qiE 'file' || P+="step 5 doesn't write the merged findings to a file"
  verdict "COMMODORE-RETASK Phase 2 step 5 writes the findings to a file and defers to agent-teammates' re-tasking section"
  vl=$(grep 'verdict: unverified' $CMD/SKILL.md)
  print -r -- $vl | grep -qiE 're-?task' || P+="SKILL.md's verify-FAIL line doesn't say re-task"
  print -r -- $vl | grep -q 'agent-teammates' || P+="SKILL.md's verify-FAIL line doesn't point at agent-teammates"
  print -r -- $vl | grep -q 'next instruction' && P+="SKILL.md's verify-FAIL line still says 'next instruction'"
  verdict "COMMODORE-RETASK SKILL.md verify-FAIL line re-tasks the teammate"
  grep -qE 'fix-round message|by message|stay alive|live for the whole run' $CMD/references/roles.md && P+="roles.md still says 'fix-round message', 'by message', 'stay alive' or 'live for the whole run'"
  verdict "COMMODORE-RETASK roles.md holds under both LIVE_MESSAGING variants"
}

# The watchdog nudges and two commodore lines hold under both LIVE_MESSAGING variants (#61). Text checks: they pin the
# questions the text must settle, not exact sentences.
want watchdog-retask && {
  ATS=$ROOT/skills/engineering/agent-teammates/SKILL.md
  CMD=$ROOT/skills/engineering/commodore
  row() { grep -F -- "| \`$1 " $ATS | head -1; }
  # AC1: the DONE and BLOCKED rows defer to the re-tasking paragraph.
  for r in DONE BLOCKED; do
    line=$(row $r)
    [[ -n $line ]] || P+="no $r row in the Watch table"
    print -r -- $line | grep -qiE 're-tasking paragraph|Launch, re-task, close' || P+="the $r row doesn't point at the re-tasking paragraph or 'Launch, re-task, close'"
    print -r -- $line | grep -qiE 're-?task' || P+="the $r row doesn't say re-task"
    print -r -- $line | grep -qE 'send it the FAIL lines as its next instruction|message it one concrete next instruction' && P+="the $r row still gives only the send/message instruction"
    verdict "WATCHDOG-RETASK Watch table $r row defers to the re-tasking paragraph"
  done
  # AC2: STALL covers LIVE_MESSAGING=0 and keeps the LIVE_MESSAGING=1 advice.
  st=$(row STALL)
  [[ -n $st ]] || P+="no STALL row in the Watch table"
  print -r -- $st | grep -qE 'LIVE_MESSAGING=0|no live messaging' || P+="the STALL row never names LIVE_MESSAGING=0 or 'no live messaging'"
  print -r -- $st | grep -q 'close-teammate\.sh' || P+="the STALL row never mentions close-teammate.sh"
  print -r -- $st | grep -qi 'relaunch' || P+="the STALL row never says relaunch"
  verdict "WATCHDOG-RETASK STALL row closes and relaunches when the harness has no live messaging"
  print -r -- $st | grep -qE 'LIVE_MESSAGING=1' || P+="the STALL row doesn't name LIVE_MESSAGING=1 for the nudge advice"
  print -r -- $st | grep -qi 'message it one concrete next command' || P+="the STALL row lost 'message it one concrete next command'"
  print -r -- $st | grep -qi 'stalls again' && print -r -- $st | grep -qi 'close it and relaunch\|close and relaunch' || P+="the STALL row lost close and relaunch on a repeat stall"
  verdict "WATCHDOG-RETASK STALL row keeps the LIVE_MESSAGING=1 advice, scoped to LIVE_MESSAGING=1"
  # AC3: the implementer section.
  imp=$(awk '/^## /{p=($0 ~ /^## Implementer/); next} p' $CMD/references/roles.md)
  [[ -n $imp ]] || P+="no '## Implementer' section found in roles.md"
  print -r -- $imp | grep -qiE 'wait for|stay alive' && P+="the implementer section still says 'wait for' or 'stay alive'"
  verdict "WATCHDOG-RETASK roles.md implementer section has neither 'wait for' nor 'stay alive'"
  # AC4: one statement of the job-file rule; the verify-FAIL line and Phase 2 reach it.
  n=0
  for f in $CMD/SKILL.md $CMD/references/*.md(N); do
    c=$(awk -v RS= '/prompts\/<name>\.job-<n>\.md/ && /file-writing tool/ && /coordinator/ && /reports\// {n++} END{print n+0}' $f 2>/dev/null)
    (( n += c ))
  done
  (( n == 1 )) || P+="found $n paragraphs stating the job-file rule (prompts/<name>.job-<n>.md with file-writing tool, coordinator and reports/) under commodore/, want 1"
  verdict "WATCHDOG-RETASK commodore states the job-file rule exactly once"
  reach() { print -r -- $1 | grep -qE 'prompts/<name>\.job-<n>\.md|job file|\]\([^)]*#[^)]*job' ; }
  vl=$(grep 'verdict: unverified' $CMD/SKILL.md)
  reach $vl || P+="SKILL.md's verify-FAIL line neither names the job file (prompts/<name>.job-<n>.md or 'job file') nor links the section stating the rule"
  mb=$CMD/references/mission-build.md
  rule=$(awk '/^## Phase 2/{p=1; next} p && /^## /{p=0} p' $mb | awk '/^1\. /{exit} {print}')
  reach $rule || P+="the Phase 2 rule neither names the job file nor links the section stating the rule"
  (( n == 1 )) || P+="reach means nothing without exactly one statement (found $n)"
  verdict "WATCHDOG-RETASK verify-FAIL line and Phase 2 rule reach the one job-file rule"
}

# ======================================================================================================================
# CP: the Copilot driver (#40), driven through the shared scripts against tests/bin/copilot, with HARNESS=copilot and
# MODEL_<ROLE> written into team.env (the cp-effort scenario also pins reasoning effort, #63). Every `copilot -p` call lands in
# $FAKE_DIR/copilot.call.<n> (cwd first, then argv, NUL-separated) and is parsed into flag -> values, so the checks accept
# `--f v`, `--f=v`, variadic and comma-separated tool lists. The fake exits on its own, stays alive until killed
# (FAKE_COPILOT_MODE=stay), or prints nothing (silent). Everything the driver does after `launch` returns is
# asynchronous, so the scenarios poll with `await`; scenarios that leave a fake alive kill it (reap_fakes).
# ======================================================================================================================
reap_fakes() {  # kill every fake copilot (and child) a scenario left alive
  local f p
  for f in $SB/w/*/fake/copilot.pids(N) $SB/w/*/fake/copilot.children(N); do
    for p in ${(f)"$(<$f)"}; do kill -9 $p 2>/dev/null; done
  done
  return 0
}
cpwant() { [[ -z $RECORD ]] && want $1; }
CPSTOP=0
cpmk() {  # cpmk <scenario> [team.env line...]: a copilot run with a reviewer (t1, read-only) and an implementer (w1) prompt
  mk $1 HARNESS=copilot MODEL_IMPLEMENTER=claude-sonnet-5.5 MODEL_REVIEWER=claude-opus-5.5 "$@[2,-1]"
  print -r -- "write it" > $D/prompts/w1.md; print -r -- "next job" > $SC/job.md
  CPSTOP=0; NOTE=
}
cpnote() { NOTE+="[$1: exit $RC; stdout: $(head -c 240 $SC/out | tr '\n' '|'); stderr: $(head -c 240 $SC/err | tr '\n' '|')] "; }
# txrun [VAR=val ...] cmd args...: xrun with a 20 s limit, for scripts that start a long-lived fake. A non-zero exit
# (a refused launch, or a hang) ends the scenario's waits.
txrun() {
  ( cd $SC/cwd && exec env -i $BASE "$@" ) > $SC/out 2> $SC/err &
  local pid=$! i=0
  while kill -0 $pid 2>/dev/null && (( i++ < 200 )); do /bin/sleep 0.1; done
  if kill -0 $pid 2>/dev/null; then kill -9 $pid 2>/dev/null; wait $pid 2>/dev/null; RC=124; else wait $pid; RC=$?; fi
  (( RC )) && CPSTOP=1
  return 0
}
await() {  # await <seconds> <command...>: poll until the command succeeds; gives up at once after a failed step
  local n=$1 i=0; shift
  until "$@"; do (( CPSTOP || i++ >= n * 10 )) && return 1; /bin/sleep 0.1; done
}
cp_pids() { cat $SC/fake/copilot.pids 2>/dev/null; }
cp_runs() { local p=(${(f)"$(cp_pids)"}); (( $#p >= $1 )); }       # at least n copilot -p runs have started
cp_alive() { local p; for p in ${(f)"$(cp_pids)"}; do kill -0 $p 2>/dev/null && return 0; done; return 1; }
cp_settled() { cp_runs $1 && ! cp_alive; }                          # n runs have started and none is alive
cp_calls() { local f=($SC/fake/copilot.call.*(N)); (( $#f >= $1 )); }
cp_id() { awk -v n=$1 '$1==n {v=$2} END {print v}' $D/teammates.tsv; }
cp_sd() { print -r -- $SC/home/.copilot/session-state/$(cp_id $1); }
cp_lock() { local p=(${(f)"$(cp_pids)"}); [[ -n $p[-1] && -e $(cp_sd $1)/inuse.$p[-1].lock ]]; }   # the newest run holds its lock
cp_child_gone() { local c=(${(f)"$(cat $SC/fake/copilot.children 2>/dev/null)"}) p; (( $#c )) || return 1; for p in $c; do kill -0 $p 2>/dev/null && return 1; done; return 0; }
cp_has() { [[ -e $1 ]]; }
cpverdict() { if (( $#P )); then fail "$1" "${(F)P}"$'\n'"$NOTE"; else pass "$1"; fi }
cpstate() { awk -v i=$(cp_id $1) '$1==i {print $3}' $SC/out; }   # the state column of `status` output for a teammate
cpact() { awk -v i=$(cp_id $1) '$1==i {print $4}' $SC/out; }

# cparse <call-file>: CCWD, CARGS, and F: flag -> its values one per line (1 for a flag with none). Handles `--f=v`,
# `--f v`, `--f a b c` for the three tool flags, and comma-separated --available-tools.
typeset -A F
typeset -a CARGS RUNS
cpadd() { local f=$1 v=$2 t NL=$'\n'; if [[ $f == --available-tools ]]; then for t in ${(s:,:)v}; do F[$f]+="${F[$f]:+$NL}$t"; done; else F[$f]+="${F[$f]:+$NL}$v"; fi; }
cparse() {
  local -a a; local -i i=1; local x f
  F=(); a=("${(@0)$(<$1)}")
  [[ -z $a[-1] ]] && a[-1]=()
  CCWD=$a[1]; CARGS=("${(@)a[2,-1]}")
  while (( i <= $#CARGS )); do
    x=$CARGS[i]; i+=1
    case $x in
      --*=*) cpadd ${x%%=*} ${x#*=} ;;
      -*) f=$x
          case $f in
            -p|--session-id|--model|--add-dir|-C|-n|--name|--reasoning-effort|--output-format|--config-dir|-r|--resume)
              cpadd $f $CARGS[i]; i+=1 ;;
            --available-tools|--allow-tool|--deny-tool)
              F[$f]=${F[$f]-}
              while (( i <= $#CARGS )) && [[ $CARGS[i] != -* ]]; do cpadd $f $CARGS[i]; i+=1; done ;;
            *) F[$f]=1 ;;
          esac ;;
    esac
  done
}
cp_load() {  # RUNS: the `copilot -p` calls so far, in order
  local c; RUNS=()
  for c in $SC/fake/copilot.call.*(nN); do cparse $c; [[ -n ${F[-p]+x} ]] && RUNS+=$c; done
}
hasv() { local x; for x in ${(f)F[$1]}; do [[ $x == "$2" ]] && return 0; done; return 1; }   # flag $1 has the value $2
hasf() { [[ -n ${F[$1]+x} ]]; }                                                              # flag $1 is present
sorted() { print -r -- ${(j:,:)${(o)${(f)F[$1]}}}; }
toolsig() { print -r -- "avail=$(sorted --available-tools) allow=$(sorted --allow-tool) deny=$(sorted --deny-tool) all=${F[--allow-all-tools]-} model=${F[--model]-} adddir=${F[--add-dir]-} s=${F[-s]-}${F[--silent]-}"; }
UUID='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
READ_ALLOW=( 'shell(git log)' 'shell(git show)' 'shell(git diff)' 'shell(git status)' 'shell(gh pr view)' 'shell(gh pr diff)' 'shell(gh issue view)' )
WRITE_DENY=( 'shell(git push:*)' 'shell(gh pr merge:*)' 'shell(gh pr create:*)' 'shell(gh api:*)' 'shell(gh issue:*)' )

# ---- AC1, AC2, AC4, engineer decisions: the command lines ------------------------------------------------------------
cpwant cp-argv && {
  cpmk cp-argv
  txrun $AT/launch-teammate.sh --read-only --role reviewer $D t1 $SC/wt; cpnote "launch t1"
  txrun $AT/launch-teammate.sh --role implementer $D w1 $SC/wt; cpnote "launch w1"
  await 10 cp_settled 2
  txrun $AT/retask.sh $D t1 $SC/job.md; cpnote "retask t1"
  await 10 cp_settled 3
  txrun $AT/retask.sh $D w1 $SC/job.md; cpnote "retask w1"
  await 10 cp_settled 4
  xrun $AT/drivers/copilot/preflight $D; cpnote "driver preflight"
  CPSTOP=0; await 5 cp_calls 6
  reap_fakes; cp_load
  id1=$(cp_id t1); id2=$(cp_id w1)
  typeset -A by; for c in $RUNS; do cparse $c; by[${F[--session-id]}]+="$c "; done
  l1=(${=by[$id1]}); l2=(${=by[$id2]})
  want5="want 6 copilot -p calls (a launch and a resume for each of t1 and w1, and the driver preflight's read-only and writer turns), got $#RUNS"

  P=()
  (( $#RUNS >= 6 )) || P+=$want5
  for c in $RUNS; do cparse $c
    hasf --available-tools && [[ -n ${F[--available-tools]} ]] || P+="${c:t}: no --available-tools list"
    [[ ${F[--session-id]} =~ $UUID ]] || P+="${c:t}: no --session-id <lowercase uuid> (got '${F[--session-id]}')"
    hasf --no-ask-user || P+="${c:t}: no --no-ask-user"
    { hasf -n || hasf --name; } && P+="${c:t}: names the session with -n/--name"
  done
  cpverdict "CP AC1 every copilot command line has --available-tools, --session-id <uuid>, --no-ask-user and no -n"

  P=()
  (( $#l1 == 2 )) || P+="t1 (registry session '$id1'): $#l1 copilot calls carry that --session-id, want 2 (launch, resume)"
  (( $#l2 == 2 )) || P+="w1 (registry session '$id2'): $#l2 copilot calls carry that --session-id, want 2 (launch, resume)"
  cpverdict "CP AC1 a resume passes the launch's --session-id (the id launch-teammate.sh registered)"

  P=()
  if (( $#l1 )); then
    cparse $l1[1]
    [[ $(sorted --available-tools) == bash,glob,grep,view ]] || P+="read-only launch --available-tools is '$(sorted --available-tools)', want bash glob grep view"
    hasv --deny-tool write || P+="read-only launch has no --deny-tool=write (deny tools: '$(sorted --deny-tool)')"
    for e in $READ_ALLOW; do hasv --allow-tool $e || P+="read-only launch lacks the allow entry $e"; done
    for fl in --allow-all-tools --allow-all --yolo; do hasf $fl && P+="read-only launch passes $fl"; done
    [[ ${(j: :)CARGS} == *'shell(gh api)'* ]] && P+="read-only launch mentions shell(gh api)"
  else P+="no read-only launch call"; fi
  cpverdict "CP AC2 read-only launch: bash view glob grep, --deny-tool write, the seven read entries, no allow-all or gh api"

  P=()
  if (( $#l2 )); then
    cparse $l2[1]
    hasf --allow-all-tools || P+="writer launch has no --allow-all-tools"
    for e in $WRITE_DENY; do hasv --deny-tool $e || P+="writer launch lacks the deny entry $e"; done
    [[ -n ${F[--available-tools]} ]] || P+="writer launch has no --available-tools list"
  else P+="no writer launch call"; fi
  cpverdict "CP AC2 writer launch: --allow-all-tools and the five deny entries"

  P=()
  for pair in "t1 $id1 claude-opus-5.5" "w1 $id2 claude-sonnet-5.5"; do
    set -- ${=pair}; cs=(${=by[$2]})
    (( $#cs == 2 )) || { P+="$1: need a launch and a resume to compare, found $#cs calls"; continue; }
    cparse $cs[1]; s1=$(toolsig); w1=$CCWD; c1=${F[-C]-}; m1=${F[--model]-}; p1=${F[-p]}
    cparse $cs[2]; s2=$(toolsig); w2=$CCWD; c2=${F[-C]-}; p2=${F[-p]}
    [[ $s1 == $s2 ]] || P+="$1: the resume's tool flags differ from the launch's: launch '$s1', resume '$s2'"
    [[ $m1 == $3 ]] || P+="$1: launch --model is '$m1', want $3 (from MODEL_<ROLE> in team.env)"
    [[ $w1 == $SC/wt || $c1 == $SC/wt ]] || P+="$1: launch runs in '$w1' (-C '$c1'), want the workdir $SC/wt"
    [[ $w2 == $SC/wt || $c2 == $SC/wt ]] || P+="$1: resume runs in '$w2' (-C '$c2'), want the workdir $SC/wt"
    [[ $p1 == *$D/prompts/$1.md* || $p1 == *"$(<$D/prompts/$1.md)"* ]] || P+="$1: launch prompt names neither the prompt file nor its content: '$p1'"
    [[ $p2 == *$SC/job.md* || $p2 == *"next job"* ]] || P+="$1: resume prompt names neither the message file nor its content: '$p2'"
  done
  cpverdict "CP AC4 a resume runs in the teammate's workdir with the launch's tool flags and model, and the message as its prompt"

  P=()
  (( $#l1 == 2 && $#l2 == 2 )) || P+="want a launch and a resume for each of t1 and w1 (matched by the registered session id), got $#l1 and $#l2"
  for c in ${=by[$id1]} ${=by[$id2]}; do cparse $c
    hasv --add-dir $D || P+="${c:t}: no --add-dir $D (add-dir: '${F[--add-dir]}')"
    { hasf -s || hasf --silent; } || P+="${c:t}: no -s"
  done
  for c in ${=by[$id1]}; do cparse $c; hasv --deny-tool write || P+="${c:t} (read-only): no --deny-tool=write"; done
  cpverdict "CP engineer decisions: every launch and resume has --add-dir <team-dir> and -s; read-only keeps --deny-tool=write"
}

# ---- AC4: the resumed process is the one status watches --------------------------------------------------------------
cpwant cp-retask-live && {
  cpmk cp-retask-live
  txrun $AT/launch-teammate.sh --read-only --role reviewer $D t1 $SC/wt; cpnote "launch"
  await 10 cp_settled 1
  txrun FAKE_COPILOT_MODE=stay $AT/retask.sh $D t1 $SC/job.md; cpnote "retask"
  await 10 cp_runs 2; await 10 cp_lock t1
  P=()
  (( ${#${(f)"$(cp_pids)"}} == 2 )) || P+="want 2 copilot runs (launch, resume), got ${#${(f)"$(cp_pids)"}}"
  cp_alive || P+="the resumed copilot isn't running right after retask.sh returned"
  grep -q 're-tasked' $SC/out || P+="retask.sh didn't print 're-tasked'"
  [[ $(awk '$1=="t1" {n++} END {print n}' $D/teammates.tsv) == 2 ]] || P+="teammates.tsv should hold the launch row and the re-task row for t1"
  xrun $AT/drivers/copilot/status $D; cpnote "status"
  [[ $(cpstate t1) == working ]] || P+="status after retask (resumed copilot alive, holding its lock) reports '$(cpstate t1)' for t1, want working"
  [[ $(cpact t1) == $NOW ]] || P+="status last activity is '$(cpact t1)', want $NOW (events.jsonl's mtime and timestamps)"
  reap_fakes
  cpverdict "CP AC4 after retask.sh with the fake still alive, status reports working with the session's last activity"
}

# ---- Status: working, done or blocked, stopped; and close -----------------------------------------------------------
cpwant cp-status && {
  cpmk cp-status
  txrun FAKE_COPILOT_MODE=stay FAKE_COPILOT_TS=$((NOW - 300)) $AT/launch-teammate.sh --role implementer $D w1 $SC/wt; cpnote "launch w1 (stay)"
  P=()
  await 10 cp_lock w1
  (( CPSTOP )) || cp_alive || P+="launch-teammate.sh returned but no copilot is running"
  xrun $AT/drivers/copilot/status $D; cpnote "status while running"
  [[ $(cpstate w1) == working ]] || P+="alive copilot with its lock: status reports '$(cpstate w1)', want working"
  [[ $(cpact w1) == $((NOW - 300)) ]] || P+="last activity is '$(cpact w1)', want $((NOW - 300)) (events.jsonl's mtime and last event)"
  [[ $(awk 'NF != 4' $SC/out | wc -l | tr -d ' ') == 0 ]] || P+="status rows must have 4 fields: $(head -c 200 $SC/out)"
  reap_fakes
  cpverdict "CP status: working while the copilot is alive with its lock; last activity from events.jsonl; 4 columns"

  cpmk cp-status-exit
  txrun $AT/launch-teammate.sh --role implementer $D w1 $SC/wt; cpnote "launch w1 (exit)"
  await 10 cp_settled 1
  P=()
  cp_runs 1 || P+="no copilot run happened"
  xrun $AT/drivers/copilot/status $D; cpnote "status after exit"
  case $(cpstate w1) in done|blocked) ;; *) P+="after the process exited, status reports '$(cpstate w1)' for w1, want done or blocked (never stopped or failed)" ;; esac
  cpverdict "CP status: done or blocked, never stopped or failed, after the process exits"
}
cpwant cp-close && {
  cpmk cp-close
  txrun FAKE_COPILOT_MODE=stay FAKE_COPILOT_CHILD=1 $AT/launch-teammate.sh --role implementer $D w1 $SC/wt; cpnote "launch w1 (stay, child)"
  await 10 cp_lock w1; await 5 cp_has $SC/fake/copilot.children
  P=()
  cp_alive || P+="the fake copilot isn't running before close-teammate.sh, so the check proves nothing"
  [[ -s $SC/fake/copilot.children ]] || P+="the fake copilot started no child"
  txrun $AT/close-teammate.sh $D w1; cpnote "close w1"
  CPSTOP=0; await 5 cp_child_gone
  cp_alive && P+="the copilot process is still alive after close-teammate.sh"
  cp_child_gone || P+="the copilot's child process is still alive: the process group wasn't killed"
  [[ $RC == 0 && $(<$SC/out) == "stopped w1 ($(cp_id w1))" ]] || P+="close-teammate.sh exit $RC, stdout '$(head -c 200 $SC/out)', want 'stopped w1 (<id>)'"
  [[ -s $(cp_sd w1)/events.jsonl ]] || P+="the session-state dir or its events.jsonl is gone: $(cp_sd w1)"
  xrun $AT/drivers/copilot/status $D; cpnote "status after close"
  [[ $(cpstate w1) == stopped ]] || P+="status after the driver's stop reports '$(cpstate w1)', want stopped"
  reap_fakes
  cpverdict "CP AC6 close-teammate.sh kills the process group, leaves the session-state dir, and status reports stopped"
}

# ---- AC5: the watchdog -----------------------------------------------------------------------------------------------
cpwant cp-watch && {
  # DONE: a teammate that wrote its marker and exited. status must also list the exited session (state done or blocked).
  cpmk cp-watch-done
  txrun FAKE_COPILOT_DONE=$D/reports/w1.done $AT/launch-teammate.sh --role implementer $D w1 $SC/wt; cpnote "launch w1"
  await 10 cp_settled 1; await 5 cp_has $D/reports/w1.done
  xrun $AT/drivers/copilot/status $D; cpnote "status"; st=$(cpstate w1)
  xrun_watch 1 $AT/watch-teammates.sh $D
  P=()
  [[ $st == done || $st == blocked ]] || P+="status reports '$st' for the exited w1, want done or blocked"
  [[ -n $REACHED ]] || P+="the watcher never finished a poll; stdout: $(head -c 200 $SC/out) stderr: $(head -c 200 $SC/err)"
  grep -q '^DONE w1$' $SC/out || P+="no 'DONE w1' line; stdout: $(head -c 200 $SC/out)"
  grep -qE '^(GONE|WATCH)' $SC/out && P+="unexpected GONE/WATCH line: $(grep -E '^(GONE|WATCH)' $SC/out | head -2 | tr '\n' '|')"
  cpverdict "CP AC5 watch-teammates.sh reports DONE, no GONE, for a teammate that wrote its marker and exited"
  reap_fakes

  # BLOCKED: the teammate exited after a retask without a new marker; the old marker doesn't count. status must list the
  # exited session from the driver's own state, or the watcher says GONE.
  cpmk cp-watch-blocked
  txrun FAKE_COPILOT_DONE=$D/reports/w1.done $AT/launch-teammate.sh --role implementer $D w1 $SC/wt; cpnote "launch w1"
  await 10 cp_settled 1; await 5 cp_has $D/reports/w1.done
  settime $((NOW - 1000)) $D/reports/w1.done
  txrun $AT/retask.sh $D w1 $SC/job.md; cpnote "retask w1"
  await 10 cp_settled 2
  xrun_watch 2 $AT/watch-teammates.sh $D
  P=()
  cp_runs 2 || P+="want 2 copilot runs (launch, resume); the scenario never got there"
  [[ -n $REACHED ]] || P+="the watcher never finished two polls; stdout: $(head -c 200 $SC/out) stderr: $(head -c 200 $SC/err)"
  grep -q "^BLOCKED w1 $(cp_id w1)\$" $SC/out || P+="no 'BLOCKED w1 <id>' line after two polls; stdout: $(head -c 300 $SC/out | tr '\n' '|')"
  grep -qE '^(GONE|WATCH)' $SC/out && P+="unexpected GONE/WATCH line: $(grep -E '^(GONE|WATCH)' $SC/out | head -2 | tr '\n' '|')"
  cpverdict "CP AC4/AC5 after a retask the old marker no longer counts: BLOCKED on the second poll, no GONE"
  reap_fakes

  # STALL: a live teammate whose last activity is older than STALL_MIN (10): 30 min.
  cpmk cp-watch-stall
  txrun FAKE_COPILOT_MODE=stay FAKE_COPILOT_TS=$((NOW - 1800)) $AT/launch-teammate.sh --role implementer $D w1 $SC/wt; cpnote "launch w1 (stay)"
  await 10 cp_lock w1
  xrun_watch 1 $AT/watch-teammates.sh $D
  P=()
  cp_alive || P+="the fake copilot isn't running"
  [[ -n $REACHED ]] || P+="the watcher never finished a poll; stdout: $(head -c 200 $SC/out) stderr: $(head -c 200 $SC/err)"
  grep -q "^STALL w1 $(cp_id w1) 30\$" $SC/out || P+="no 'STALL w1 <id> 30' line; stdout: $(head -c 300 $SC/out | tr '\n' '|')"
  grep -qE '^(GONE|WATCH)' $SC/out && P+="unexpected GONE/WATCH line: $(grep -E '^(GONE|WATCH)' $SC/out | head -2 | tr '\n' '|')"
  cpverdict "CP AC5 STALL for a live teammate whose events.jsonl is 30 minutes old"
  reap_fakes
  # control: the same teammate with fresh activity doesn't stall
  cpmk cp-watch-fresh
  txrun FAKE_COPILOT_MODE=stay $AT/launch-teammate.sh --role implementer $D w1 $SC/wt; cpnote "launch w1 (stay)"
  await 10 cp_lock w1
  xrun_watch 1 $AT/watch-teammates.sh $D
  P=()
  cp_alive || P+="the fake copilot isn't running"
  [[ -n $REACHED ]] || P+="the watcher never finished a poll; stdout: $(head -c 200 $SC/out) stderr: $(head -c 200 $SC/err)"
  grep -qE '^(STALL|GONE|WATCH|BLOCKED)' $SC/out && P+="unexpected line for a fresh working teammate: $(head -c 200 $SC/out | tr '\n' '|')"
  cpverdict "CP AC5 no STALL, GONE or BLOCKED for a live teammate with fresh activity"
  reap_fakes
}

# ---- Tail ------------------------------------------------------------------------------------------------------------
cpwant cp-tail && {
  cpmk cp-tail
  txrun FAKE_COPILOT_SAY='all green' $AT/launch-teammate.sh --role implementer $D w1 $SC/wt; cpnote "launch w1"
  await 10 cp_settled 1
  xrun $AT/teammate-tail.sh $D w1; cpnote "tail"
  P=()
  cp_runs 1 || P+="no copilot run happened"
  [[ $RC == 0 ]] || P+="teammate-tail.sh exit $RC, want 0"
  [[ $(head -1 $SC/out) == "transcript: "* ]] || P+="first line isn't 'transcript: ...': $(head -1 $SC/out)"
  grep -qE '^TOOL +.*git status' $SC/out || P+="no TOOL line naming the bash call (git status)"
  grep -qE '^SAID +.*all green' $SC/out || P+="no SAID line with the final message"
  cpverdict "CP tail prints TOOL and SAID lines from events.jsonl"
}

# ---- Read-only reports written by the driver (engineer decision, option b) --------------------------------------------
cp_report_is() { [[ -f $D/reports/t1.md && $(<$D/reports/t1.md) == $1 && $D/reports/t1.done -nt $SC/oldref ]]; }
cpwant cp-report && {
  cpmk cp-report
  txrun FAKE_COPILOT_SAY='first report' $AT/launch-teammate.sh --read-only --role reviewer $D t1 $SC/wt; cpnote "launch t1"
  await 10 cp_has $D/reports/t1.done
  P=()
  cp_runs 1 || P+="no copilot run happened"
  [[ -s $D/reports/t1.md ]] || P+="reports/t1.md is missing or empty when t1.done appeared (.md must come first)"
  [[ -f $D/reports/t1.md && $(<$D/reports/t1.md) == 'first report' ]] || P+="reports/t1.md holds '$(head -c 200 $D/reports/t1.md 2>/dev/null)', want the final message 'first report'"
  [[ -f $D/reports/t1.done ]] || P+="no reports/t1.done"
  [[ ! -f $D/reports/t1.md || ! $D/reports/t1.md -nt $D/reports/t1.done ]] || P+="reports/t1.md is newer than t1.done: the marker must come second"
  cpverdict "CP read-only launch: the driver writes reports/<name>.md from the final message, then <name>.done"
  await 5 cp_settled 1
  : > $SC/oldref; settime 1500000001 $SC/oldref; settime 1500000000 $D/reports/t1.md $D/reports/t1.done
  txrun FAKE_COPILOT_SAY='second report' $AT/retask.sh $D t1 $SC/job.md; cpnote "retask t1"
  await 10 cp_report_is 'second report'
  P=()
  cp_runs 2 || P+="no resumed copilot run happened"
  [[ -f $D/reports/t1.md && $(<$D/reports/t1.md) == 'second report' ]] || P+="after the resume reports/t1.md holds '$(head -c 200 $D/reports/t1.md 2>/dev/null)', want 'second report'"
  [[ $D/reports/t1.done -nt $SC/oldref ]] || P+="reports/t1.done wasn't touched after the resume"
  cpverdict "CP read-only retask: the resumed session's final message replaces the report, and the marker is touched again"
  reap_fakes

  # no final message: neither file; the session reads done or blocked with no marker
  cpmk cp-report-none
  txrun FAKE_COPILOT_MODE=silent $AT/launch-teammate.sh --read-only --role reviewer $D t1 $SC/wt; cpnote "launch t1 (silent)"
  await 10 cp_settled 1
  txrun FAKE_COPILOT_MODE=silent $AT/retask.sh $D t1 $SC/job.md; cpnote "retask t1 (silent)"
  await 10 cp_settled 2
  /bin/sleep 1.5
  P=()
  cp_runs 2 || P+="want 2 silent runs (launch, resume), got ${#${(f)"$(cp_pids)"}}"
  [[ ! -e $D/reports/t1.md ]] || P+="reports/t1.md was written with no final message"
  [[ ! -e $D/reports/t1.done ]] || P+="reports/t1.done was written with no final message"
  cpverdict "CP read-only with no final message: the driver writes neither the report nor the marker"
  reap_fakes

  # writers write their own report
  cpmk cp-report-writer
  txrun FAKE_COPILOT_SAY='writer text' $AT/launch-teammate.sh --role implementer $D w1 $SC/wt; cpnote "launch w1"
  await 10 cp_settled 1
  /bin/sleep 1.5
  P=()
  cp_runs 1 || P+="no copilot run happened"
  [[ ! -e $D/reports/w1.md && ! -e $D/reports/w1.done ]] || P+="the driver wrote a report or marker for a writer: $(ls $D/reports | tr '\n' ' ')"
  cpverdict "CP a writer session gets no driver-written report or marker"
  reap_fakes
}

# ---- Preflight (AC1 for the headless turn, and the two FAILs) -------------------------------------------------------
cpwant cp-preflight && {
  cpmk cp-preflight-ok
  xrun FAKE_COPILOT_EVIDENCE=1 $AT/drivers/copilot/preflight $D; cpnote "preflight"
  P=()
  [[ $RC == 0 ]] || P+="driver preflight exit $RC with the fake copilot on PATH, want 0"
  grep -q '^FAIL' $SC/out && P+="FAIL line: $(grep '^FAIL' $SC/out | head -2 | tr '\n' '|')"
  grep -q '^OK' $SC/out || P+="no OK line"
  cp_calls 2 || P+="want 2 copilot calls logged (a read-only and a writer headless turn)"
  cpverdict "CP preflight passes with the fake copilot (running evidence.sh when its dir is added) and runs two headless turns"

  cpmk cp-preflight-nopath
  xrun PATH=/usr/bin:/bin:/usr/sbin:/sbin $AT/drivers/copilot/preflight $D; cpnote "preflight, no copilot"
  P=()
  [[ $RC == 1 ]] || P+="exit $RC, want 1"
  grep -qiE '^FAIL.*copilot' $SC/out || P+="no FAIL line naming copilot (copilot not on PATH)"
  cpverdict "CP preflight FAILs, naming copilot, when copilot isn't on PATH"

  cpmk cp-preflight-silent
  xrun FAKE_COPILOT_MODE=silent $AT/drivers/copilot/preflight $D; cpnote "preflight, silent copilot"
  P=()
  cp_calls 1 || P+="no copilot call logged: the preflight ran no headless turn"
  [[ $RC == 1 ]] || P+="exit $RC, want 1"
  grep -qiE '^FAIL.*(no output|empty|nothing|overflow|context)' $SC/out || P+="no FAIL line about the headless turn printing nothing"
  cpverdict "CP preflight FAILs when the headless turn prints nothing (the context-overflow symptom)"
}

# ---- #81: writers get --add-dir for the skill script dirs (the path guard refuses the rest) -------------------------
# The writer's --add-dir set is <team-dir>, the driver's own scripts dir ($AT: the driver lives in $AT/drivers/copilot),
# and PREFLIGHT_SCRIPTS and TEAM_SCRIPTS from team.env when each is an absolute path to an existing directory. Every
# check compares the whole sorted set, so a missing, extra or duplicated dir all show.
cpenv() {  # cpenv KEY[=value]...: drop each KEY's lines from team.env, then append KEY=value (no value: just drop)
  local a k
  for a in "$@"; do
    k=${a%%=*}
    grep -v "^$k=" $D/team.env > $D/team.env.tmp; mv $D/team.env.tmp $D/team.env
    [[ $a == *=* ]] && print -r -- $a >> $D/team.env
  done
  return 0
}
cp_adds_str() { print -r -- "${(j:, :)${(o)${(f)F[--add-dir]}}}"; }
cp_adds_is() { local -a g=(${(o)${(f)F[--add-dir]}}) w=(${(o)@}); [[ "${(pj:\n:)g}" == "${(pj:\n:)w}" ]]; }   # the set of --add-dir values (with repeats) is exactly the arguments
cp_order() {  # after cparse: every --add-dir sits before --available-tools, the driver's scripts dir is among them, and -p ends the list
  local i ai=0 av=0
  for (( i = 1; i <= $#CARGS; i++ )); do
    [[ $CARGS[i] == --add-dir || $CARGS[i] == --add-dir=* ]] && ai=$i
    [[ $CARGS[i] == --available-tools && $av == 0 ]] && av=$i
  done
  hasv --add-dir $AT && (( ai && av && ai < av )) && [[ $CARGS[-2] == -p ]]
}
ro_pin() {  # ro_pin <session-id> <model> <add-dir|->: P+= unless CARGS is exactly today's read-only list, up to its -p prompt
  local -a w=(--no-ask-user -s --session-id $1 --model $2); local s=$'\001'
  [[ $3 != - ]] && w+=(--add-dir $3)
  w+=(--available-tools bash view glob grep --deny-tool=write --allow-tool $READ_ALLOW -p)
  [[ ${(pj:$s:)CARGS[1,-2]} == "${(pj:$s:)w}" ]] || P+="read-only argv isn't today's list: got [${(j: :)CARGS[1,-2]}], want [${(j: :)w}]"
  return 0
}
ax_sub() { local x=$1; x=${x//@SC@/$SC}; x=${x//@D@/$D}; print -r -- ${x//@AT@/$AT}; }
# ax_case <label> <resume 0|1>: a writer launch (and, with 1, a resume) with team.env edited by AX_ENV (KEY=value or KEY to
# drop it), AX_PRE (shell, run first) and expecting the extra dirs AX_WANT (or, when set, AX_ALT). @SC@ @D@ @AT@ expand.
ax_case() {
  local label=$1 rs=$2 c n=1 lrc a wstr astr; local -a envl=() want=() alt=()
  cpmk cp-adddir-$label
  eval "$(ax_sub $AX_PRE)"
  for a in $AX_ENV; do envl+=("$(ax_sub $a)"); done
  for a in $AX_WANT; do want+=("$(ax_sub $a)"); done
  for a in $AX_ALT; do alt+=("$(ax_sub $a)"); done
  cpenv PREFLIGHT_SCRIPTS TEAM_SCRIPTS "${envl[@]}"
  (( $#alt )) && astr=" (or, with the whole value as one dir: ${(j:, :)alt})"
  txrun $AT/launch-teammate.sh --role implementer $D w1 $SC/wt; cpnote "launch w1"; lrc=$RC
  await 10 cp_settled 1
  if (( rs )); then txrun $AT/retask.sh $D w1 $SC/job.md; cpnote "retask w1"; await 10 cp_settled 2; n=2; fi
  cp_load
  P=()
  (( lrc == 0 )) || P+="the launch exited $lrc: a team.env value that adds nothing must never fail the launch"
  (( $#RUNS == n )) || P+="want $n copilot -p runs, got $#RUNS"
  for c in $RUNS; do cparse $c
    if cp_adds_is $D $AT "${want[@]}"; then :
    elif (( $#alt )) && cp_adds_is $D $AT "${alt[@]}"; then :
    else P+="${c:t}: --add-dir values are [$(cp_adds_str)], want [${(j:, :)${(o)${:-$D $AT $want}}}]${astr}"; fi
    cp_order || P+="${c:t}: the --add-dir pairs must precede --available-tools, include $AT, and -p must be the last flag (argv: ${(j: :)CARGS})"
    (( ${CARGS[(I)--allow-all-paths]} )) && P+="${c:t}: a team.env value became an --allow-all-paths argument"
  done
  cpverdict "CP add-dir: writer launch${${rs:#0}:+ and resume}, $label"
  reap_fakes
}

cpwant cp-adddir && {
  # launch and resume, writer and read-only, with real PREFLIGHT_SCRIPTS and TEAM_SCRIPTS dirs
  cpmk cp-adddir-main
  mkdir -p $SC/ps $SC/ts
  cpenv PREFLIGHT_SCRIPTS=$SC/ps TEAM_SCRIPTS=$SC/ts
  txrun $AT/launch-teammate.sh --read-only --role reviewer $D t1 $SC/wt; cpnote "launch t1"
  await 10 cp_settled 1
  txrun $AT/launch-teammate.sh --role implementer $D w1 $SC/wt; cpnote "launch w1"
  await 10 cp_settled 2
  txrun $AT/retask.sh $D t1 $SC/job.md; cpnote "retask t1"
  await 10 cp_settled 3
  txrun $AT/retask.sh $D w1 $SC/job.md; cpnote "retask w1"
  await 10 cp_settled 4
  reap_fakes; cp_load
  id1=$(cp_id t1); id2=$(cp_id w1)
  typeset -A by; by=(); for c in $RUNS; do cparse $c; by[${F[--session-id]}]+="$c "; done
  l1=(${=by[$id1]}); l2=(${=by[$id2]})

  P=()
  (( $#l2 == 2 )) || P+="w1 (session '$id2'): $#l2 copilot calls, want 2 (launch, resume)"
  for c in $l2; do cparse $c
    cp_adds_is $D $AT $SC/ps $SC/ts || P+="${c:t}: writer --add-dir values are [$(cp_adds_str)], want [${(j:, :)${(o)${:-$D $AT $SC/ps $SC/ts}}}]"
  done
  cpverdict "CP add-dir: a writer launch and resume carry the team dir, the driver's scripts dir, PREFLIGHT_SCRIPTS and TEAM_SCRIPTS"

  P=()
  for c in $l2; do cparse $c
    cp_order || P+="${c:t}: the --add-dir pairs must precede --available-tools, include $AT, and -p must be the last flag (argv: ${(j: :)CARGS})"
    hasf --allow-all-tools && hasv --available-tools edit && hasv --available-tools create || P+="${c:t}: not the writer flags"
  done
  cpverdict "CP add-dir: the new --add-dir pairs come before the variadic flags, and -p still ends the list"

  P=()
  (( $#l1 == 2 )) || P+="t1 (session '$id1'): $#l1 copilot calls, want 2 (launch, resume)"
  for c in $l1; do cparse $c; ro_pin $id1 claude-opus-5.5 $D; done
  cpverdict "CP add-dir: a read-only launch and resume keep today's argv element for element, with PREFLIGHT_SCRIPTS and TEAM_SCRIPTS set"
}

cpwant cp-adddir-values && {
  AX_PRE=; AX_ALT=()
  AX_ENV=(PREFLIGHT_SCRIPTS TEAM_SCRIPTS); AX_WANT=()
  ax_case unset 0
  AX_ENV=(PREFLIGHT_SCRIPTS= TEAM_SCRIPTS=); AX_WANT=()
  ax_case empty 0
  AX_PRE='mkdir -p @SC@/cwd/ps @SC@/cwd/ts @SC@/wt/ps @SC@/wt/ts @D@/ps @D@/ts'
  AX_ENV=(PREFLIGHT_SCRIPTS=ps TEAM_SCRIPTS=./ts); AX_WANT=()
  ax_case relative 0
  AX_PRE=
  AX_ENV=(PREFLIGHT_SCRIPTS=@SC@/missing-ps TEAM_SCRIPTS=@SC@/missing-ts); AX_WANT=()
  ax_case missing 0
  AX_PRE=': > @SC@/afile; mkdir -p @SC@/ts'
  AX_ENV=(PREFLIGHT_SCRIPTS=@SC@/afile TEAM_SCRIPTS=@SC@/ts); AX_WANT=(@SC@/ts)
  ax_case not-a-dir 0
  AX_PRE=
  AX_ENV=(PREFLIGHT_SCRIPTS=--allow-all-paths TEAM_SCRIPTS=-x); AX_WANT=()
  ax_case dash-led 0
  AX_PRE='mkdir -p "@SC@/sp --allow-all-paths"'
  AX_ENV=("PREFLIGHT_SCRIPTS='@SC@/sp --allow-all-paths'"); AX_WANT=(); AX_ALT=("@SC@/sp --allow-all-paths")
  ax_case spaces 0
  AX_ALT=()
  AX_PRE='mkdir -p @SC@/gad "@SC@/g*d"'
  AX_ENV=(PREFLIGHT_SCRIPTS 'TEAM_SCRIPTS=@SC@/g*d'); AX_WANT=('@SC@/g*d')
  ax_case glob 0
  AX_PRE='mkdir -p @SC@/ts @SC@/tm @SC@/cwd/ps'
  AX_ENV=(PREFLIGHT_SCRIPTS=ps TEAM_SCRIPTS=@SC@/ts TEAMMATES_SCRIPTS=@SC@/tm); AX_WANT=(@SC@/ts)
  ax_case mixed 1
  AX_PRE='mkdir -p @SC@/ps @SC@/ts'
  AX_ENV=(TEAMMATES_SCRIPTS=@SC@/nope PREFLIGHT_SCRIPTS=@SC@/ps TEAM_SCRIPTS=@SC@/ts); AX_WANT=(@SC@/ps @SC@/ts)
  ax_case scripts-dir-from-driver 0
}

cpwant cp-adddir-dups && {
  AX_PRE='mkdir -p @SC@/ps @SC@/ts'; AX_ALT=()
  AX_ENV=(PREFLIGHT_SCRIPTS=@SC@/ps TEAM_SCRIPTS=@SC@/ps); AX_WANT=(@SC@/ps)
  ax_case same-twice 1
  AX_ENV=(PREFLIGHT_SCRIPTS=@AT@ TEAM_SCRIPTS=@SC@/ts); AX_WANT=(@SC@/ts)
  ax_case is-the-scripts-dir 0
  AX_ENV=(PREFLIGHT_SCRIPTS=@SC@/ps TEAM_SCRIPTS=@D@); AX_WANT=(@SC@/ps)
  ax_case is-the-team-dir 0
  AX_ENV=(PREFLIGHT_SCRIPTS=@AT@ TEAM_SCRIPTS=@AT@); AX_WANT=()
  ax_case both-the-scripts-dir 0
}

cpwant cp-adddir-ro && {
  # a blank ro fails closed: no extra dirs and today's read-only list
  cpmk cp-adddir-ro-closed
  mkdir -p $SC/ps $SC/ts
  cpenv PREFLIGHT_SCRIPTS=$SC/ps TEAM_SCRIPTS=$SC/ts
  txrun $AT/launch-teammate.sh --role implementer $D w1 $SC/wt; cpnote "launch w1"
  await 10 cp_settled 1
  sed -i.bak 's/^ro=.*/ro=/' $D/copilot-$(cp_id w1)
  txrun $AT/retask.sh $D w1 $SC/job.md; cpnote "retask w1 (blank ro)"
  await 10 cp_settled 2
  cp_load
  P=()
  (( $#RUNS == 2 )) || P+="want 2 runs, got $#RUNS"
  if (( $#RUNS == 2 )); then cparse $RUNS[2]; ro_pin $(cp_id w1) claude-sonnet-5.5 $D; fi
  cpverdict "CP add-dir: a resume with a blank ro gets today's read-only argv, no extra dirs"
  reap_fakes
}

cpwant cp-adddir-data && {
  # cp_supervise reads team.env as data: it runs nothing from it, and nothing but the two keys can add a dir. The state
  # file can't add one either.
  cpmk cp-adddir-data
  mkdir -p $SC/ps $SC/ts
  cpenv PREFLIGHT_SCRIPTS=$SC/ps TEAM_SCRIPTS=$SC/ts
  { print -r -- "touch $SC/pwned1"; print -r -- "UNRELATED=\$(touch $SC/pwned2)"; print -r -- "OTHER_SCRIPTS=/etc"; print -r -- "TEAMMATES_SCRIPTS=/etc"; } >> $D/team.env
  id=11111111-2222-4333-8444-555555555555
  printf '%s\n' name=w1 workdir=$SC/wt model=- ro=0 add-dir=/etc adddir=/etc dirs=/etc extra=/etc > $D/copilot-$id
  xrun /bin/zsh -f -c 'source "$1" && shift && cp_supervise "$@"' zsh $AT/drivers/copilot/lib.zsh $D $id "do it"; cpnote "cp_supervise"
  cp_load
  P=()
  (( $#RUNS == 1 )) || P+="want 1 copilot run, got $#RUNS"
  [[ -e $SC/pwned1 || -e $SC/pwned2 ]] && P+="cp_supervise ran a command from team.env"
  if (( $#RUNS == 1 )); then cparse $RUNS[1]
    cp_adds_is $D $AT $SC/ps $SC/ts || P+="--add-dir values are [$(cp_adds_str)], want [${(j:, :)${(o)${:-$D $AT $SC/ps $SC/ts}}}]"
    cp_order || P+="the --add-dir pairs must precede --available-tools, include $AT, and -p must be the last flag"
  fi
  cpverdict "CP add-dir: cp_supervise reads PREFLIGHT_SCRIPTS and TEAM_SCRIPTS from team.env as data and adds nothing else"
}

# ---- the fake's evidence mode (FAKE_COPILOT_EVIDENCE): it must run the script only for an added dir --------------------
cpwant cp-fake-evidence && {
  fe() {  # fe <label> <expect log: yes|no> [VAR=val ...] -- <copilot add-dir args...>: one fake `-p` run asking for evidence.sh
    local label=$1 want=$2 T=$SC/team l; shift 2
    local -a ev=(); while [[ $1 != -- ]]; do ev+=$1; shift; done; shift
    rm -rf $T $SC/fake; mkdir -p $T/prompts $SC/fake; print -r -- "$label true" > $T/prompts/u1.proof; : > $SC/claude.log
    xrun $ev copilot --session-id fake-$label "$@" -p "Run \`$AT/evidence.sh $T u1 $label.\` and say OK"; cpnote "fake $label"
    l=$T/reports/u1-evidence/$label.log
    P=()
    if [[ $want == yes ]]; then
      [[ -f $l ]] || P+="no log at $l"
      [[ -f $l && $(tail -n 1 $l) == 'exit: 0' ]] || P+="the log doesn't end 'exit: 0'"
    else
      [[ -e $T/reports/u1-evidence ]] && P+="the fake ran evidence.sh anyway: $(ls $T/reports/u1-evidence | tr '\n' ' ')"
    fi
    cpverdict "CP fake copilot, FAKE_COPILOT_EVIDENCE: $label"
  }
  cpmk cp-fake-evidence
  fe added-dir yes FAKE_COPILOT_EVIDENCE=1 -- --add-dir $SC --add-dir $AT
  fe added-dir-equals yes FAKE_COPILOT_EVIDENCE=1 -- --add-dir=$AT
  fe dir-not-added no FAKE_COPILOT_EVIDENCE=1 -- --add-dir $SC
  fe parent-dir-only no FAKE_COPILOT_EVIDENCE=1 -- --add-dir ${AT:h}
  fe subdir-slash-only no FAKE_COPILOT_EVIDENCE=1 -- --add-dir $AT/
  fe not-opted-in no -- --add-dir $AT
  fe refused-dir no FAKE_COPILOT_EVIDENCE=1 FAKE_COPILOT_REFUSE=$AT -- --add-dir $AT
}

# ---- the driver's preflight writer turn ---------------------------------------------------------------------------------
pf_split() {  # PFR and PFW: the preflight's read-only call and its writer call (the one with --allow-all-tools)
  local c; PFR=; PFW=; cp_load
  for c in $RUNS; do cparse $c; hasf --allow-all-tools && PFW=$c || PFR=$c; done
}
pf_writer_checks() {  # the writer turn's argv: the scripts dir, the run dir's extras, one throwaway team dir, a throwaway cwd
  local c=$1 x; local -a rest
  cparse $c; PFT=
  cp_order || P+="writer turn: the --add-dir pairs must precede --available-tools, include $AT, and -p must be the last flag (argv: ${(j: :)CARGS})"
  hasv --available-tools edit && hasv --available-tools create || P+="writer turn: not the writer tool list"
  rest=(${(f)F[--add-dir]}); rest=(${rest:#$AT})
  for x in $@[2,-1]; do rest=(${rest:#$x}); done
  (( $#rest == 1 )) || P+="writer turn: want one throwaway team dir besides $AT and the run dir's extras, --add-dir values are [$(cp_adds_str)]"
  PFT=$rest[1]; PFC=$CCWD
  [[ $PFT == $D ]] && P+="writer turn: --add-dir is the real run dir, not a throwaway team dir"
  [[ $PFC == $D || $PFC == $SC/cwd ]] && P+="writer turn runs in $PFC, want a throwaway dir"
  return 0
}
cpwant cp-adddir-preflight && {
  cpmk cp-adddir-preflight-ok
  mkdir -p $SC/ps $SC/ts
  cpenv PREFLIGHT_SCRIPTS=$SC/ps TEAM_SCRIPTS=$SC/ts
  xrun FAKE_COPILOT_EVIDENCE=1 $AT/drivers/copilot/preflight $D; cpnote "preflight"
  pf_split
  P=()
  [[ $RC == 0 ]] || P+="driver preflight exit $RC, want 0 (the fake runs evidence.sh for an added scripts dir)"
  grep -q '^FAIL' $SC/out && P+="FAIL line: $(grep '^FAIL' $SC/out | head -2 | tr '\n' '|')"
  grep -qi '^OK.*\(evidence\|writer\)' $SC/out || P+="no OK line about the writer turn / evidence.sh; stdout: $(head -c 300 $SC/out | tr '\n' '|')"
  grep -q '^OK.*returned output' $SC/out || P+="the read-only turn's OK line is gone"
  (( $#RUNS == 2 )) || P+="want 2 copilot -p calls (read-only, writer), got $#RUNS"
  cpverdict "CP preflight: the writer turn runs evidence.sh through --add-dir and prints OK"

  P=()
  if [[ -n $PFW ]]; then
    pf_writer_checks $PFW $SC/ps $SC/ts
    cp_adds_is $AT $SC/ps $SC/ts $PFT || P+="writer turn --add-dir values are [$(cp_adds_str)], want the scripts dir, the run dir's PREFLIGHT_SCRIPTS and TEAM_SCRIPTS, and the throwaway team dir"
    ev=($SC/fake/copilot.evidence.*(N))
    (( $#ev == 1 )) || P+="want one evidence.sh run by the fake, got $#ev"
    (( $#ev == 1 )) && { grep -q '^exit: 0$' $ev[1] && grep -q '^rc: 0$' $ev[1] || P+="the fake's evidence.sh run didn't end exit: 0: $(tail -n 3 $ev[1] | tr '\n' '|')"; }
    [[ -e $PFT || -e $PFC ]] && P+="a throwaway dir is still there after the preflight: ${${PFT:+$PFT}:-} $PFC"
    ls $D/reports | grep -q -- '-evidence' && P+="the run's own reports dir got evidence: $(ls $D/reports | tr '\n' ' ')"
  else P+="no writer turn (a copilot -p call with --allow-all-tools)"; fi
  cpverdict "CP preflight: the writer turn's flags are the writer set, with the scripts dir, the run dir's extras and a throwaway team dir, all removed on exit"

  P=()
  if [[ -n $PFR ]]; then cparse $PFR; [[ ${F[--session-id]} =~ $UUID ]] || P+="read-only turn: no uuid --session-id"; ro_pin ${F[--session-id]} claude-opus-5.5 -; else P+="no read-only turn"; fi
  cpverdict "CP preflight: the read-only turn's argv is today's, element for element"

  cpmk cp-adddir-preflight-extras
  mkdir -p $SC/cwd/ps
  cpenv PREFLIGHT_SCRIPTS=ps TEAM_SCRIPTS=$SC/missing
  xrun FAKE_COPILOT_EVIDENCE=1 $AT/drivers/copilot/preflight $D; cpnote "preflight, relative and missing extras"
  pf_split
  P=()
  [[ $RC == 0 ]] || P+="driver preflight exit $RC, want 0"
  if [[ -n $PFW ]]; then pf_writer_checks $PFW; else P+="no writer turn"; fi
  cpverdict "CP preflight: a relative or missing PREFLIGHT_SCRIPTS/TEAM_SCRIPTS adds nothing to the writer turn and doesn't fail the preflight"

  cpmk cp-adddir-preflight-noguard
  xrun $AT/drivers/copilot/preflight $D; cpnote "preflight, fake guard on nothing"
  P=()
  cp_calls 2 || P+="want 2 copilot calls (read-only, writer)"
  [[ $RC == 0 ]] && P+="exit 0 although the writer's evidence.sh never ran"
  grep -qiE '^FAIL.*(path.guard|--add-dir)' $SC/out || P+="no FAIL line naming the path guard or --add-dir; stdout: $(head -c 300 $SC/out | tr '\n' '|')"
  grep -q '^OK.*returned output' $SC/out || P+="the read-only turn's OK line is gone"
  grep -qi '^OK.*\(evidence\|writer\)' $SC/out && P+="an OK line about the writer turn although it ran nothing"
  [[ $RC == 1 ]] || P+="exit $RC, want 1"
  cpverdict "CP preflight FAILs naming the path guard when the writer turn can't run evidence.sh (the fake runs no commands)"

  cpmk cp-adddir-preflight-refused
  xrun FAKE_COPILOT_EVIDENCE=1 FAKE_COPILOT_REFUSE=$AT $AT/drivers/copilot/preflight $D; cpnote "preflight, guard refuses the scripts dir"
  P=()
  [[ $RC == 1 ]] || P+="exit $RC, want 1"
  grep -qiE '^FAIL.*(path.guard|--add-dir)' $SC/out || P+="no FAIL line naming the path guard or --add-dir; stdout: $(head -c 300 $SC/out | tr '\n' '|')"
  [[ -z $(echo $SC/fake/copilot.evidence.*(N)) ]] || P+="the fake ran evidence.sh although its dir was refused"
  cpverdict "CP preflight FAILs naming the path guard when the guard refuses the scripts dir"
}

# ---- Fix round 1: preflight failures, resume activity, send waits, a launch that dies, stale reports ----------------
cpwant cp-round1 && {
  cpmk cp-preflight-stderr
  xrun FAKE_COPILOT_MODE=stderr $AT/drivers/copilot/preflight $D; cpnote "preflight, stderr-only copilot"
  P=()
  cp_calls 1 || P+="no copilot call logged: the preflight ran no headless turn"
  [[ $RC == 1 ]] || P+="exit $RC, want 1 (stdout was empty; the message went to stderr)"
  grep -qiE '^FAIL.*(no output|empty|nothing|overflow|context)' $SC/out || P+="no FAIL line about the headless turn printing nothing"
  cpverdict "CP preflight FAILs when the turn's only output is on stderr"

  cpmk cp-preflight-fail
  xrun FAKE_COPILOT_MODE=fail $AT/drivers/copilot/preflight $D; cpnote "preflight, failing copilot"
  P=()
  cp_calls 1 || P+="no copilot call logged: the preflight ran no headless turn"
  [[ $RC == 1 ]] || P+="exit $RC, want 1"
  grep -q '^FAIL.*exited 1.*fake copilot failed' $SC/out || P+="no FAIL line with the exit code and the first stderr line"
  grep -q '^OK.*returned output' $SC/out && P+="an OK line for a turn that exited 1"
  cpverdict "CP preflight FAILs, quoting stderr, when the headless turn exits non-zero"

  cpmk cp-launch-dies
  txrun FAKE_COPILOT_MODE=fail $AT/launch-teammate.sh --role implementer $D w1 $SC/wt; cpnote "launch w1 (fails at once)"
  P=()
  [[ $RC == 124 ]] && P+="launch hung"
  (( RC )) || P+="launch-teammate.sh exit 0 although copilot exited 1 at once"
  grep -q 'exited at once' $SC/out || P+="no 'exited at once' message; stdout: $(head -c 200 $SC/out)"
  [[ -z $(awk '$1=="w1"' $D/teammates.tsv) ]] || P+="a failed launch was registered"
  cpverdict "CP launch exits non-zero, registering nothing, when copilot dies at once"

  # a resume's fresh start is activity: stale events.jsonl must not read as a stall
  cpmk cp-resume-activity
  txrun $AT/launch-teammate.sh --role implementer $D w1 $SC/wt; cpnote "launch w1"
  await 10 cp_settled 1
  txrun FAKE_COPILOT_MODE=stay FAKE_COPILOT_TS=$((NOW - 1800)) $AT/retask.sh $D w1 $SC/job.md; cpnote "retask w1 (stay, stale events)"
  await 10 cp_lock w1
  xrun $AT/drivers/copilot/status $D; cpnote "status"
  P=()
  [[ $(cpact w1) == $NOW ]] || P+="last activity is '$(cpact w1)', want $NOW (the resume's start; events.jsonl is 30 min old)"
  xrun_watch 1 $AT/watch-teammates.sh $D
  cp_alive || P+="the resumed fake copilot isn't running"
  grep -q '^STALL' $SC/out && P+="STALL for a teammate that was just resumed: $(head -c 200 $SC/out)"
  reap_fakes
  cpverdict "CP a fresh resume counts as activity: status reports its start, no STALL"

  # send refuses, after waiting, while the previous turn runs
  cpmk cp-send-busy
  txrun FAKE_COPILOT_MODE=stay $AT/launch-teammate.sh --role implementer $D w1 $SC/wt; cpnote "launch w1 (stay)"
  await 10 cp_lock w1
  CPSTOP=0; txrun COPILOT_SEND_WAIT=1 $AT/retask.sh $D w1 $SC/job.md; cpnote "retask w1 (busy)"
  P=()
  (( RC )) || P+="retask.sh exit 0 while the previous turn is still running"
  grep -q 'still running' $SC/out || P+="no 'still running' message; stdout: $(head -c 200 $SC/out)"
  [[ $(awk '$1=="w1" {n++} END {print n}' $D/teammates.tsv) == 1 ]] || P+="a refused re-task was recorded"
  pp=(${(f)"$(cp_pids)"}); (( $#pp == 1 )) || P+="a second copilot run started: $pp"
  reap_fakes
  cpverdict "CP send refuses, recording nothing, while the previous turn is still running"

  cpmk cp-send-wait
  txrun FAKE_COPILOT_MODE=stay FAKE_COPILOT_STAY_MAX=2 $AT/launch-teammate.sh --role implementer $D w1 $SC/wt; cpnote "launch w1 (stays 2 s)"
  await 10 cp_lock w1
  CPSTOP=0; txrun COPILOT_SEND_WAIT=20 $AT/retask.sh $D w1 $SC/job.md; cpnote "retask w1 (waits)"
  await 10 cp_settled 2
  P=()
  [[ $RC == 0 ]] || P+="retask.sh exit $RC, want 0 after waiting for the previous turn to end"
  cp_runs 2 || P+="no resumed run"
  reap_fakes
  cpverdict "CP send waits for a turn that is ending, then resumes"

  # a read-only resume with no final message leaves the earlier report alone
  cpmk cp-report-stale
  txrun FAKE_COPILOT_SAY='first report' $AT/launch-teammate.sh --read-only --role reviewer $D t1 $SC/wt; cpnote "launch t1"
  await 10 cp_has $D/reports/t1.done; await 5 cp_settled 1
  : > $SC/oldref; settime 1500000001 $SC/oldref; settime 1500000000 $D/reports/t1.md $D/reports/t1.done
  txrun FAKE_COPILOT_MODE=silent $AT/retask.sh $D t1 $SC/job.md; cpnote "retask t1 (silent)"
  await 10 cp_settled 2
  /bin/sleep 1.5
  P=()
  cp_runs 2 || P+="no silent resume ran"
  [[ -f $D/reports/t1.md && $(<$D/reports/t1.md) == 'first report' ]] || P+="reports/t1.md holds '$(head -c 100 $D/reports/t1.md 2>/dev/null)', want the first report"
  [[ ! $D/reports/t1.md -nt $SC/oldref ]] || P+="reports/t1.md was rewritten by the silent resume"
  [[ ! $D/reports/t1.done -nt $SC/oldref ]] || P+="reports/t1.done was touched by the silent resume"
  reap_fakes
  cpverdict "CP a silent read-only resume doesn't rewrite the report from the earlier turn's message"
}

# ---- Fix round 2: state files are untrusted (a writer can write the team dir), and ro fails closed ---------------
cpwant cp-round2 && {
  cpmk cp-state-payload
  id=11111111-2222-4333-8444-555555555555
  printf '%s\n' "name=x" "workdir=$SC/wt" "model=m" "ro=0" "pid=1" "pgid=1" 'started=a[$(touch '$SC'/pwned1)]' 'resumed=a[$(touch '$SC'/pwned2)]' > $D/copilot-$id
  xrun $AT/drivers/copilot/status $D; cpnote "status"
  P=()
  [[ -e $SC/pwned1 || -e $SC/pwned2 ]] && P+="a command in a state file's started= or resumed= ran in status"
  grep -q "^$id - " $SC/out || P+="no row for the session; stdout: $(head -c 200 $SC/out)"
  [[ $(awk -v i=$id '$1==i {print $4}' $SC/out) == - ]] || P+="last activity is '$(awk -v i=$id '$1==i {print $4}' $SC/out)', want - (no usable number)"
  printf '%s\n' "name=x" "workdir=$SC/wt" "model=m" "ro=0" 'pid=a[$(touch '$SC'/pwned3)]' 'pgid=a[$(touch '$SC'/pwned3)]' > $D/copilot-$id
  xrun $AT/drivers/copilot/status $D; xrun $AT/drivers/copilot/stop $D $id
  [[ -e $SC/pwned3 ]] && P+="a command in a state file's pid= or pgid= ran"
  cpverdict "CP a state file's started/resumed/pid/pgid are never evaluated as arithmetic"

  # a blank ro in the state file fails closed to the read-only flags on resume
  cpmk cp-ro-closed
  txrun $AT/launch-teammate.sh --role implementer $D w1 $SC/wt; cpnote "launch w1"
  await 10 cp_settled 1
  sed -i.bak 's/^ro=.*/ro=/' $D/copilot-$(cp_id w1)
  txrun $AT/retask.sh $D w1 $SC/job.md; cpnote "retask w1 (blank ro)"
  await 10 cp_settled 2
  cp_load
  P=()
  (( $#RUNS == 2 )) || P+="want 2 runs, got $#RUNS"
  if (( $#RUNS == 2 )); then
    cparse $RUNS[2]
    hasv --deny-tool write || P+="the resume with a blank ro has no --deny-tool=write"
    hasf --allow-all-tools && P+="the resume with a blank ro passes --allow-all-tools"
  fi
  cpverdict "CP a blank ro in the state file gets the read-only flags (fails closed)"
  reap_fakes

  # a failed read-only run doesn't replace the report or touch the marker
  cpmk cp-report-failed
  txrun FAKE_COPILOT_MODE=fail FAKE_COPILOT_SAY=late $AT/launch-teammate.sh --read-only --role reviewer $D t1 $SC/wt; cpnote "launch t1 (fails)"
  /bin/sleep 1
  P=()
  [[ ! -e $D/reports/t1.md && ! -e $D/reports/t1.done ]] || P+="a failed run wrote a report or marker: $(ls $D/reports | tr '\n' ' ')"
  cpverdict "CP a read-only run that exits non-zero writes no report and no marker"
}

# ---- Reasoning effort (#63): TEAMMATE_EFFORT from EFFORT_<ROLE> is recorded at launch and passed as one --reasoning-effort
# argv element, in the fixed head before the variadic tool lists, on launch and on every resume; empty means no flag.
cp_eff_runs() {  # cp_eff_runs <name>: sets L (the launch call) and R (the resume call) for a teammate, by its session id
  local id=$(cp_id $1) c; L=; R=; cp_load
  for c in $RUNS; do cparse $c; [[ ${F[--session-id]} == $id ]] || continue; [[ -z $L ]] && L=$c || R=$c; done
}
cp_eff_of() { cparse $1; print -r -- "${F[--reasoning-effort]-<absent>}"; }
cpwant cp-effort && {
  cpmk cp-effort EFFORT_REVIEWER=high EFFORT_IMPLEMENTER=medium
  txrun $AT/launch-teammate.sh --read-only --role reviewer $D t1 $SC/wt; cpnote "launch t1"
  txrun $AT/launch-teammate.sh --role implementer $D w1 $SC/wt; cpnote "launch w1"
  await 10 cp_settled 2
  # A later team.env edit and a caller's TEAMMATE_EFFORT must not change a resume: send reuses what launch recorded.
  print -r -- "EFFORT_REVIEWER=low" >> $D/team.env
  txrun TEAMMATE_EFFORT=low $AT/retask.sh $D t1 $SC/job.md; cpnote "retask t1"
  await 10 cp_settled 3
  txrun $AT/retask.sh $D w1 $SC/job.md; cpnote "retask w1"
  await 10 cp_settled 4
  reap_fakes
  P=()
  cp_eff_runs t1; t1l=$L; t1r=$R
  cp_eff_runs w1; w1l=$L; w1r=$R
  [[ -n $t1l && -n $t1r && -n $w1l && -n $w1r ]] || P+="want a launch and a resume call for each of t1 and w1, matched by session id"
  [[ -n $t1l ]] && [[ $(cp_eff_of $t1l) == high ]] || P+="t1 launch: --reasoning-effort is '$([[ -n $t1l ]] && cp_eff_of $t1l)', want high (EFFORT_REVIEWER)"
  [[ -n $w1l ]] && [[ $(cp_eff_of $w1l) == medium ]] || P+="w1 launch: --reasoning-effort is '$([[ -n $w1l ]] && cp_eff_of $w1l)', want medium (EFFORT_IMPLEMENTER)"
  cpverdict "CP effort: a launch passes --reasoning-effort <effort> once, for a read-only and a writer teammate"

  P=()
  [[ -n $t1r ]] && [[ $(cp_eff_of $t1r) == high ]] || P+="t1 resume: --reasoning-effort is '$([[ -n $t1r ]] && cp_eff_of $t1r)', want high (recorded at launch, not the later EFFORT_REVIEWER=low or TEAMMATE_EFFORT=low)"
  [[ -n $w1r ]] && [[ $(cp_eff_of $w1r) == medium ]] || P+="w1 resume: --reasoning-effort is '$([[ -n $w1r ]] && cp_eff_of $w1r)', want medium (recorded at launch)"
  cpverdict "CP effort: send reuses the effort recorded at launch on a resume, read-only and writer"

  P=()
  for c in $t1l $t1r $w1l $w1r; do
    cparse $c; ai=${CARGS[(i)--reasoning-effort]}; av=${CARGS[(i)--available-tools]}
    if (( ai > $#CARGS )); then P+="${c:t}: no --reasoning-effort in argv"
    elif (( ai > av )); then P+="${c:t}: --reasoning-effort (argv index $ai) isn't in the fixed head before --available-tools (index $av)"; fi
  done
  [[ -n $t1l ]] || P+="no launch call to check"
  cpverdict "CP effort: --reasoning-effort sits in the fixed head, before the variadic tool lists"
}

cpwant cp-effort-empty && {
  cpmk cp-effort-empty EFFORT_REVIEWER= EFFORT_IMPLEMENTER=
  txrun $AT/launch-teammate.sh --read-only --role reviewer $D t1 $SC/wt; cpnote "launch t1"
  txrun $AT/launch-teammate.sh --role implementer $D w1 $SC/wt; cpnote "launch w1"
  await 10 cp_settled 2
  txrun $AT/retask.sh $D t1 $SC/job.md; cpnote "retask t1"
  await 10 cp_settled 3
  txrun $AT/retask.sh $D w1 $SC/job.md; cpnote "retask w1"
  await 10 cp_settled 4
  reap_fakes; cp_load
  P=()
  (( $#RUNS == 4 )) || P+="want 4 copilot -p calls (a launch and a resume each), got $#RUNS"
  for c in $RUNS; do cparse $c
    hasf --reasoning-effort && P+="${c:t}: passes --reasoning-effort (${F[--reasoning-effort]}) although the effort is empty"
    [[ ${(j: :)CARGS} == *reasoning* ]] && P+="${c:t}: argv mentions reasoning: ${(j: :)CARGS[1,12]}"
  done
  cpverdict "CP effort: an empty effort passes no --reasoning-effort on launch or resume"
}

cpwant cp-effort-hostile && {
  # A value with spaces and shell syntax fails the effort shape check (U4, U5), so it is refused, never launched.
  cpmk cp-effort-hostile "EFFORT_REVIEWER='a b \$(touch effort-pwned) \"q\"'"
  txrun $AT/launch-teammate.sh --read-only --role reviewer $D t1 $SC/wt; cpnote "launch t1"
  /bin/sleep 0.3
  reap_fakes
  P=()
  [[ $RC == 5 ]] || P+="exit $RC, want 5"
  st=($D/copilot-*(N)); (( $#st )) && P+="state file written: ${(j: :)st:t}"
  cl=($SC/fake/copilot.call.*(N)); (( $#cl )) && P+="copilot was called ${#cl} time(s)"
  # The payload's path is relative, so an evaluation would create it in whichever directory the script ran in.
  hit=$(find $SB $PWD -name effort-pwned 2>/dev/null)
  [[ -n $hit ]] && P+="the effort was evaluated: ${hit//$'\n'/ } exists"
  cpverdict "CP effort: an effort with spaces and shell syntax is refused with exit 5 and never evaluated"
}

# ---- AC7: ADVISOR n/a (copilot). A scratch tree whose detection says copilot (the real signal is COPILOT_CLI=1, checked by C3).
cpwant cp-ac7 && {
  cp -R $SKILLS $SB/src-cop; printf '#!/bin/sh\necho copilot\n' > $SB/src-cop/agent-teammates/scripts/detect-harness.sh
  TREE=$SB/src-cop; cpmk cp-ac7; TREE=$SKILLS; mk_repo
  xrun FAKE_COPILOT_EVIDENCE=1 $SB/src-cop/commodore/scripts/team-preflight.sh $D; cpnote "team-preflight"
  na=$(grep -c '^OK    ADVISOR n/a (copilot)$' $SC/out)
  P=()
  [[ $na == 1 ]] || P+="want one 'OK    ADVISOR n/a (copilot)' line, got $na; advisor lines: $(grep -i advisor $SC/out | head -3 | tr '\n' '|')"
  grep -qE '^(FAIL|WARN.*ADVISOR)' $SC/out && P+="FAIL or advisor WARN lines: $(grep -E '^(FAIL|WARN.*ADVISOR)' $SC/out | head -3 | tr '\n' '|')"
  [[ $RC == 0 ]] || P+="exit $RC, want 0"
  cpverdict "CP AC7 team-preflight.sh on a copilot run prints ADVISOR n/a (copilot)"
}

# ======================================================================================================================
# C1: nothing outside the drivers calls claude or copilot or reads their transcripts.
# ======================================================================================================================
shared=( $ROOT/skills/engineering/agent-teammates/scripts $ROOT/skills/engineering/commodore/scripts $ROOT/skills/engineering/setup-commodore/scripts )
shared_code() {  # shared_code <egrep-pattern>: matching non-comment lines in shared scripts, as file:line:text
  local f
  find $shared \( -path '*/drivers/claude' -o -path '*/drivers/codex' -o -path '*/drivers/copilot' \) -prune -o -type f -print | LC_ALL=C sort | while read -r f; do
    grep -nE -- "$1" $f | grep -vE '^[0-9]+:[[:space:]]*#' | sed -e 's#== \.claude ||#== DOTCLAUDE ||#' | grep -E -- "$1" | sed "s#^#${f#$ROOT/}:#"
  done
}
hits=$(shared_code '(^|[^-/a-z])claude ')
[[ -z $hits ]] && pass "C1 no shared script calls claude" || fail "C1 no shared script calls claude" "$(print -r -- $hits | wc -l | tr -d ' ') lines, first 6:
$(print -r -- $hits | head -6)"
hits=$(shared_code '\.jsonl|/projects|\.claude\.json')
[[ -z $hits ]] && pass "C1 no shared script reads Claude transcript or config paths" || fail "C1 no shared script reads Claude transcript or config paths" "$(print -r -- $hits | wc -l | tr -d ' ') lines, first 6:
$(print -r -- $hits | head -6)"
hits=$(shared_code '(^|[^-/a-z])codex ')
[[ -z $hits ]] && pass "C1 no shared script calls codex" || fail "C1 no shared script calls codex" "$(print -r -- $hits | wc -l | tr -d ' ') lines, first 6:
$(print -r -- $hits | head -6)"
hits=$(shared_code '\.codex/')
[[ -z $hits ]] && pass "C1 no shared script reads ~/.codex paths" || fail "C1 no shared script reads ~/.codex paths" "$(print -r -- $hits | wc -l | tr -d ' ') lines, first 6:
$(print -r -- $hits | head -6)"
hits=$(shared_code '(^|[^-/a-z])copilot ')
[[ -z $hits ]] && pass "C1 no shared script calls copilot" || fail "C1 no shared script calls copilot" "$(print -r -- $hits | wc -l | tr -d ' ') lines, first 6:
$(print -r -- $hits | head -6)"
hits=$(shared_code '\.copilot|session-state|events\.jsonl|inuse\.')
[[ -z $hits ]] && pass "C1 no shared script reads Copilot session state" || fail "C1 no shared script reads Copilot session state" "$(print -r -- $hits | wc -l | tr -d ' ') lines, first 6:
$(print -r -- $hits | head -6)"

# ======================================================================================================================
# C3: team-init detects the harness.
# ======================================================================================================================
want c3 && {
  sc c3-claude; xrun CLAUDECODE=1 $CM/team-init.sh run1 $SC/repo
  n=$(grep -c '^HARNESS=claude$' $SC/teams/run1/team.env 2>/dev/null)
  [[ $RC == 0 && $n == 1 ]] && pass "C3 CLAUDECODE=1 writes HARNESS=claude once" || fail "C3 CLAUDECODE=1 writes HARNESS=claude once" "exit $RC, ${n:-0} HARNESS=claude lines in team.env (want exit 0, 1 line)"

  sc c3-none; xrun $CM/team-init.sh run1 $SC/repo
  if [[ $RC == 7 && ! -e $SC/teams/run1 && $(cat $SC/out $SC/err) == *claude* ]]; then pass "C3 no harness detected: exit 7, no run, names claude"
  else fail "C3 no harness detected: exit 7, no run, names claude" "exit $RC (want 7); run dir exists: $([[ -e $SC/teams/run1 ]] && echo yes || echo no) (want no); output: $(cat $SC/out $SC/err | head -c 300 | tr '\n' ' ')"; fi

  sc c3-copilot; xrun HARNESS=copilot $CM/team-init.sh run1 $SC/repo
  n=$(grep -c '^HARNESS=copilot$' $SC/teams/run1/team.env 2>/dev/null)
  [[ $RC == 0 && $n == 1 ]] && pass "C3 HARNESS=copilot preset: exit 0, HARNESS=copilot once in team.env" || fail "C3 HARNESS=copilot preset: exit 0, HARNESS=copilot once in team.env" "exit $RC, ${n:-0} HARNESS=copilot lines in team.env (want exit 0, 1 line); output: $(cat $SC/out $SC/err | head -c 300 | tr '\n' ' ')"
  sc c3-codex-inside-claude; xrun HARNESS=codex CLAUDECODE=1 $CM/team-init.sh run1 $SC/repo
  n=$(grep -c '^HARNESS=codex$' $SC/teams/run1/team.env 2>/dev/null)
  [[ $RC == 0 && $n == 1 ]] && pass "C3 HARNESS=codex wins over CLAUDECODE=1" || fail "C3 HARNESS=codex wins over CLAUDECODE=1" "exit $RC, ${n:-0} HARNESS=codex lines in team.env (want exit 0, 1 line); output: $(cat $SC/out $SC/err | head -c 300 | tr '\n' ' ')"

  # The Codex team.env defaults.
  sc c3-codex; xrun CODEX_THREAD_ID=019e-test $CM/team-init.sh run1 $SC/repo
  E=$SC/teams/run1/team.env
  n=$(grep -c '^HARNESS=codex$' $E 2>/dev/null)
  [[ $RC == 0 && $n == 1 ]] && pass "C3 CODEX_THREAD_ID writes HARNESS=codex once" || fail "C3 CODEX_THREAD_ID writes HARNESS=codex once" "exit $RC, ${n:-0} HARNESS=codex lines in team.env (want exit 0, 1 line); output: $(cat $SC/out $SC/err | head -c 300 | tr '\n' ' ')"
  miss=()
  for r in IMPLEMENTER TEST_WRITER TARGET_STEWARD; do for kv in MODEL_$r=gpt-6.1-sol EFFORT_$r=medium; do grep -qx -- $kv $E 2>/dev/null || miss+=($kv); done; done
  for r in REVIEWER SECURITY_REVIEWER BRIEF_CHECKER TRIAGER; do for kv in MODEL_$r=gpt-6-astra EFFORT_$r=high; do grep -qx -- $kv $E 2>/dev/null || miss+=($kv); done; done
  for kv in MODEL_SCRIBE=gpt-6-luna EFFORT_SCRIBE=medium MODEL=gpt-6.1-sol VIEWER=none; do grep -qx -- $kv $E 2>/dev/null || miss+=($kv); done
  [[ -z $miss ]] && pass "C3 Codex team.env has every MODEL_/EFFORT_ default, MODEL and VIEWER=none" || fail "C3 Codex team.env has every MODEL_/EFFORT_ default, MODEL and VIEWER=none" "missing lines: ${miss[*]}"
  bad=$(grep -nE '^(ADVISOR|PERMISSION_MODE|CLAUDE_CONFIG_DIR)=' $E 2>/dev/null)
  [[ -f $E && -z $bad ]] && pass "C3 Codex team.env has no ADVISOR, PERMISSION_MODE or CLAUDE_CONFIG_DIR line" || fail "C3 Codex team.env has no ADVISOR, PERMISSION_MODE or CLAUDE_CONFIG_DIR line" "${bad:-no team.env written (exit $RC)}"
  [[ -f $E ]] && ! grep -qiE 'Claude Code|cmux' $E && pass "C3 Codex team.env doesn't mention Claude Code or cmux" || fail "C3 Codex team.env doesn't mention Claude Code or cmux" "${$(grep -niE 'Claude Code|cmux' $E 2>/dev/null | head -3):-no team.env written (exit $RC)}"
  sc c3-claude-noeffort; xrun CLAUDECODE=1 $CM/team-init.sh run1 $SC/repo
  ! grep -q '^EFFORT_' $SC/teams/run1/team.env && grep -q '^ADVISOR=opus$' $SC/teams/run1/team.env && pass "C3 Claude team.env has no EFFORT_ lines and keeps ADVISOR=opus" || fail "C3 Claude team.env has no EFFORT_ lines and keeps ADVISOR=opus" "$(grep -E '^(EFFORT_|ADVISOR)' $SC/teams/run1/team.env | head -3 | tr '\n' ' ')"

  sc c3-both; xrun CLAUDECODE=1 CODEX_THREAD_ID=019e-test $CM/team-init.sh run1 $SC/repo
  if [[ $RC == 7 && ! -e $SC/teams/run1 && $(cat $SC/out $SC/err) == *"more than one harness detected"* ]]; then pass "C3 CLAUDECODE=1 and CODEX_THREAD_ID: exit 7, more than one harness, no run"
  else fail "C3 CLAUDECODE=1 and CODEX_THREAD_ID: exit 7, more than one harness, no run" "exit $RC (want 7); run dir exists: $([[ -e $SC/teams/run1 ]] && echo yes || echo no) (want no); output: $(cat $SC/out $SC/err | head -c 300 | tr '\n' ' ')"; fi

  # Copilot detection (#63): COPILOT_CLI=1 is the signal. Copilot passes its parent's environment through, so a Copilot
  # started from a Claude Code shell sets both, and detection names both rather than picking one.
  sc c3-det-copilot; xrun COPILOT_CLI=1 $AT/detect-harness.sh
  [[ $RC == 0 && $(<$SC/out) == copilot ]] && pass "C3 detect-harness.sh with COPILOT_CLI=1 prints copilot and nothing else" || fail "C3 detect-harness.sh with COPILOT_CLI=1 prints copilot and nothing else" "exit $RC; stdout: $(head -c 200 $SC/out | tr '\n' '|') (want 'copilot')"
  sc c3-det-copilot-claude; xrun COPILOT_CLI=1 CLAUDECODE=1 $AT/detect-harness.sh
  [[ $RC == 0 && ${(j:,:)${(o)${(f)"$(<$SC/out)"}}} == claude,copilot ]] && pass "C3 detect-harness.sh with COPILOT_CLI=1 and CLAUDECODE=1 prints both claude and copilot" || fail "C3 detect-harness.sh with COPILOT_CLI=1 and CLAUDECODE=1 prints both claude and copilot" "exit $RC; stdout: $(head -c 200 $SC/out | tr '\n' '|') (want the two lines claude and copilot, either order)"
  sc c3-det-copilot-off; xrun COPILOT_CLI=0 $AT/detect-harness.sh
  [[ $RC == 0 && $(<$SC/out) != *copilot* ]] && pass "C3 detect-harness.sh with COPILOT_CLI=0 doesn't print copilot" || fail "C3 detect-harness.sh with COPILOT_CLI=0 doesn't print copilot" "stdout: $(head -c 200 $SC/out | tr '\n' '|')"

  sc c3-copilot-detected; xrun COPILOT_CLI=1 $CM/team-init.sh run1 $SC/repo
  n=$(grep -c '^HARNESS=copilot$' $SC/teams/run1/team.env 2>/dev/null)
  [[ $RC == 0 && $n == 1 ]] && pass "C3 COPILOT_CLI=1 writes HARNESS=copilot once" || fail "C3 COPILOT_CLI=1 writes HARNESS=copilot once" "exit $RC, ${n:-0} HARNESS=copilot lines in team.env (want exit 0, 1 line); output: $(cat $SC/out $SC/err | head -c 300 | tr '\n' ' ')"

  sc c3-copilot-claude; xrun COPILOT_CLI=1 CLAUDECODE=1 $CM/team-init.sh run1 $SC/repo
  if [[ $RC == 7 && ! -e $SC/teams/run1 && $(cat $SC/out $SC/err) == *"more than one harness detected"* ]]; then pass "C3 COPILOT_CLI=1 and CLAUDECODE=1: exit 7, more than one harness, no run"
  else fail "C3 COPILOT_CLI=1 and CLAUDECODE=1: exit 7, more than one harness, no run" "exit $RC (want 7); run dir exists: $([[ -e $SC/teams/run1 ]] && echo yes || echo no) (want no); output: $(cat $SC/out $SC/err | head -c 300 | tr '\n' ' ')"; fi

  # The Copilot team.env defaults. Driven from the HARNESS=copilot preset, which works today, so these fail on the missing
  # defaults and not on the missing detection (the COPILOT_CLI=1 checks above cover that).
  sc c3-copilot-defaults; xrun HARNESS=copilot $CM/team-init.sh run1 $SC/repo
  E=$SC/teams/run1/team.env
  miss=()
  for r in IMPLEMENTER TEST_WRITER TARGET_STEWARD; do grep -qx -- MODEL_$r=claude-sonnet-5.5 $E 2>/dev/null || miss+=(MODEL_$r=claude-sonnet-5.5); done
  for r in REVIEWER SECURITY_REVIEWER BRIEF_CHECKER TRIAGER; do grep -qx -- MODEL_$r=claude-opus-5.5 $E 2>/dev/null || miss+=(MODEL_$r=claude-opus-5.5); done
  grep -qx -- MODEL_SCRIBE=claude-haiku-5.5 $E 2>/dev/null || miss+=(MODEL_SCRIBE=claude-haiku-5.5)
  [[ -z $miss ]] && pass "C3 Copilot team.env has every MODEL_<ROLE> default" || fail "C3 Copilot team.env has every MODEL_<ROLE> default" "missing lines: ${miss[*]}"
  miss=()
  for r in IMPLEMENTER TEST_WRITER TARGET_STEWARD REVIEWER SECURITY_REVIEWER BRIEF_CHECKER TRIAGER SCRIBE; do grep -qx -- EFFORT_$r= $E 2>/dev/null || miss+=(EFFORT_$r=); done
  [[ -z $miss ]] && pass "C3 Copilot team.env has every EFFORT_<ROLE> present and empty" || fail "C3 Copilot team.env has every EFFORT_<ROLE> present and empty" "missing or non-empty: ${miss[*]}; lines: $(grep '^EFFORT_' $E 2>/dev/null | head -3 | tr '\n' ' ')"
  miss=()
  for kv in MODEL=claude-sonnet-5.5 REQUIRE_ROLE=1 VIEWER=none; do grep -qx -- $kv $E 2>/dev/null || miss+=($kv); done
  [[ -z $miss ]] && pass "C3 Copilot team.env pins MODEL=claude-sonnet-5.5, REQUIRE_ROLE=1 and VIEWER=none" || fail "C3 Copilot team.env pins MODEL=claude-sonnet-5.5, REQUIRE_ROLE=1 and VIEWER=none" "missing lines: ${miss[*]}; MODEL/REQUIRE_ROLE/VIEWER lines: $(grep -E '^(MODEL|REQUIRE_ROLE|VIEWER)=' $E 2>/dev/null | tr '\n' ' ')"
  bad=$(grep -nE '^(ADVISOR|PERMISSION_MODE|CLAUDE_CONFIG_DIR|CMUX|CMUX_WORKSPACE|CMUX_SURFACE)=' $E 2>/dev/null)
  [[ -f $E && -z $bad ]] && pass "C3 Copilot team.env has no ADVISOR, PERMISSION_MODE, CLAUDE_CONFIG_DIR or CMUX line" || fail "C3 Copilot team.env has no ADVISOR, PERMISSION_MODE, CLAUDE_CONFIG_DIR or CMUX line" "${bad:-no team.env written (exit $RC)}"
  [[ -f $E ]] && ! grep -qiE 'Claude Code|cmux' $E && pass "C3 Copilot team.env doesn't mention Claude Code or cmux" || fail "C3 Copilot team.env doesn't mention Claude Code or cmux" "${$(grep -niE 'Claude Code|cmux' $E 2>/dev/null | head -3):-no team.env written (exit $RC)}"

  sc c3-copilot-preflight; xrun COPILOT_CLI=1 $CM/team-init.sh run1 $SC/repo
  D=$SC/teams/run1
  xrun COPILOT_CLI=1 $CM/team-preflight.sh $D
  if grep -q '^OK    ADVISOR n/a (copilot)' $SC/out && [[ -f $D/team.env ]] && ! grep -q '^ADVISOR=' $D/team.env; then pass "C3 team-preflight on a Copilot team.env prints OK ADVISOR n/a (copilot), no ADVISOR= line"
  else fail "C3 team-preflight on a Copilot team.env prints OK ADVISOR n/a (copilot), no ADVISOR= line" "team-init exit before: see team.env at $D; ADVISOR lines in output: $(grep ADVISOR $SC/out | head -3 | tr '\n' '|'); ADVISOR= lines in team.env: $(grep -c '^ADVISOR=' $D/team.env 2>/dev/null)"; fi

  sc c3-cmux-codex; xrun CMUX_CODEX_HOOK=1 CMUX_CODEX_SESSION=x $CM/team-init.sh run1 $SC/repo
  if [[ $RC == 7 && ! -e $SC/teams/run1 && $(cat $SC/out $SC/err) == *"no supported harness detected"* ]]; then pass "C3 only CMUX_CODEX_* set detects nothing"
  else fail "C3 only CMUX_CODEX_* set detects nothing" "exit $RC (want 7); run dir exists: $([[ -e $SC/teams/run1 ]] && echo yes || echo no) (want no); output: $(cat $SC/out $SC/err | head -c 300 | tr '\n' ' ')"; fi

  sc c3-codex-empty; xrun CODEX_THREAD_ID= $CM/team-init.sh run1 $SC/repo
  if [[ $RC == 7 && ! -e $SC/teams/run1 && $(cat $SC/out $SC/err) == *"no supported harness detected"* ]]; then pass "C3 empty CODEX_THREAD_ID detects nothing"
  else fail "C3 empty CODEX_THREAD_ID detects nothing" "exit $RC (want 7); run dir exists: $([[ -e $SC/teams/run1 ]] && echo yes || echo no) (want no); output: $(cat $SC/out $SC/err | head -c 300 | tr '\n' ' ')"; fi

  sc c3-cmux-codex-claude; xrun CMUX_CODEX_HOOK=1 CLAUDECODE=1 $CM/team-init.sh run1 $SC/repo
  n=$(grep -c '^HARNESS=claude$' $SC/teams/run1/team.env 2>/dev/null)
  [[ $RC == 0 && $n == 1 ]] && pass "C3 CMUX_CODEX_* with CLAUDECODE=1 detects claude only" || fail "C3 CMUX_CODEX_* with CLAUDECODE=1 detects claude only" "exit $RC, ${n:-0} HARNESS=claude lines (want exit 0, 1 line); output: $(cat $SC/out $SC/err | head -c 300 | tr '\n' ' ')"
  sc c3-codex-empty-claude; xrun CODEX_THREAD_ID= CLAUDECODE=1 $CM/team-init.sh run1 $SC/repo
  n=$(grep -c '^HARNESS=claude$' $SC/teams/run1/team.env 2>/dev/null)
  [[ $RC == 0 && $n == 1 ]] && pass "C3 empty CODEX_THREAD_ID with CLAUDECODE=1 detects claude only" || fail "C3 empty CODEX_THREAD_ID with CLAUDECODE=1 detects claude only" "exit $RC, ${n:-0} HARNESS=claude lines (want exit 0, 1 line); output: $(cat $SC/out $SC/err | head -c 300 | tr '\n' ' ')"

  # team-preflight on a team.env that team-init wrote for Codex: the advisor check is n/a, and it isn't skipped.
  sc c3-codex-preflight; xrun CODEX_THREAD_ID=019e-test $CM/team-init.sh run1 $SC/repo
  D=$SC/teams/run1
  xrun CODEX_THREAD_ID=019e-test $CM/team-preflight.sh $D
  if grep -q '^OK    ADVISOR n/a (codex)' $SC/out && [[ -f $D/team.env ]] && ! grep -q '^ADVISOR=' $D/team.env; then pass "C3 team-preflight on a Codex team.env prints OK ADVISOR n/a (codex), no ADVISOR= line"
  else fail "C3 team-preflight on a Codex team.env prints OK ADVISOR n/a (codex), no ADVISOR= line" "ADVISOR lines in output: $(grep ADVISOR $SC/out | head -3 | tr '\n' '|'); ADVISOR= lines in team.env: $(grep -c '^ADVISOR=' $D/team.env 2>/dev/null)"; fi
}

# ======================================================================================================================
# C4: team-preflight checks HARNESS in team.env against the environment.
# ======================================================================================================================
pf_case() {  # pf_case <check name> <scenario> <HARNESS line|-> <env assignment|-> <want> <fail-line word>
  local nm=$1 s=$2 hl=$3 ev=$4 want=$5 word=$6 e=() line
  [[ $hl == - ]] && hl=; HL=$hl; pf_sc $s; HL=
  [[ $ev == - ]] || e=($ev)
  xrun $e $CM/team-preflight.sh $D
  line=$(grep '^FAIL' $SC/out | grep -i -- "$word" | head -1)
  if [[ $want == pass ]]; then
    [[ $RC == 0 ]] && ! grep -q '^FAIL' $SC/out && pass "$nm" || fail "$nm" "exit $RC, want 0 with no FAIL line; $(grep '^FAIL' $SC/out | head -3 | tr '\n' ' ')"
  else
    [[ $RC == 1 && -n $line ]] && pass "$nm" || fail "$nm" "exit $RC (want 1); FAIL line naming '$word': ${line:-none}; FAIL lines: $(grep '^FAIL' $SC/out | head -3 | tr '\n' ' ')"
  fi
}
want c4 && {
  pf_case "C4 baseline: no HARNESS line is treated as claude" c4-baseline - CLAUDECODE=1 pass -
  pf_case "C4 HARNESS=claude in claude passes" c4-match HARNESS=claude CLAUDECODE=1 pass -
  pf_case "C4 HARNESS=claude with no harness detected fails" c4-claude-none HARNESS=claude - fail claude
  pf_case "C4 HARNESS=codex inside claude fails the mismatch check" c4-codex-in-claude HARNESS=codex CLAUDECODE=1 fail "this environment is claude"
  # Other checks may still fail for Codex until the driver's own preflight exists: only the harness check is asserted.
  HL=HARNESS=codex; pf_sc c4-codex-match; HL=
  xrun CODEX_THREAD_ID=019e-test $CM/team-preflight.sh $D
  line=$(grep -E '^(FAIL|WARN)' $SC/out | grep -iE 'HARNESS|harness|this environment is|has no driver|not supported' | head -1)
  [[ -z $line ]] && grep -q '^OK    ' $SC/out && pass "C4 HARNESS=codex with CODEX_THREAD_ID passes the harness check" || fail "C4 HARNESS=codex with CODEX_THREAD_ID passes the harness check" "exit $RC; harness line: ${line:-none}; first lines: $(head -3 $SC/out | tr '\n' '|')"
  pf_case "C4 HARNESS=bogus (no driver) fails" c4-no-driver HARNESS=bogus CLAUDECODE=1 fail bogus
}

# C4 (real mismatch): a test-only driver directory, so the mismatch branch is reached and not only the no-driver one.
want c4 && {
  cp -R $SKILLS $SB/src-other; mkdir -p $SB/src-other/agent-teammates/scripts/drivers/other
  : > $SB/src-other/agent-teammates/scripts/drivers/other/driver.env
  TREE=$SB/src-other; HL=HARNESS=other; pf_sc c4-mismatch; HL=; TREE=$SKILLS
  xrun CLAUDECODE=1 $SB/src-other/commodore/scripts/team-preflight.sh $D
  line=$(grep '^FAIL' $SC/out | grep 'HARNESS=other' | grep 'this environment is claude' | head -1)
  if [[ $RC == 1 && -n $line ]] && ! grep -q 'ADVISOR' $SC/out; then pass "C4 HARNESS=other (a driver exists) inside claude fails the mismatch check, no advisor probe"
  else fail "C4 HARNESS=other (a driver exists) inside claude fails the mismatch check, no advisor probe" "exit $RC (want 1); mismatch FAIL line: ${line:-none}; advisor lines: $(grep ADVISOR $SC/out | head -2 | tr '\n' '|')"; fi
}

# ======================================================================================================================
# S1: HARNESS comes from team.env alone, and must be a plain name.
# ======================================================================================================================
want s1 && {
  # An environment HARNESS pointing outside drivers/ is ignored when team.env has none: nothing outside drivers/ runs.
  mk s1-env-traversal; mkdir -p $SC/evil; printf '#!/bin/sh\necho ran > "%s/evil-ran"\n' $SC > $SC/evil/stop; chmod +x $SC/evil/stop
  reg t1 c51dbe46 1789999000 - $SC/wt
  xrun HARNESS=../../../../../../../../../../..$SC/evil $AT/close-teammate.sh $D t1
  if [[ $RC == 0 && ! -e $SC/evil-ran && $(cat $SC/out) == "stopped t1 (c51dbe46)" ]]; then pass "S1 an environment HARNESS with ../ never runs a file outside drivers/"
  else fail "S1 an environment HARNESS with ../ never runs a file outside drivers/" "exit $RC; evil ran: $([[ -e $SC/evil-ran ]] && echo yes || echo no); out: $(cat $SC/out | head -c 200)"; fi
  # An invalid HARNESS in team.env is rejected by every script that resolves a driver.
  mk s1-invalid HARNESS=../x; reg t1 c51dbe46 1789999000 - $SC/wt; mk_repo
  xrun $AT/close-teammate.sh $D t1; rc1=$RC; o1=$(cat $SC/out)
  xrun $CM/advisor-probe.sh $D sonnet; rc2=$RC; o2=$(cat $SC/out)
  xrun CLAUDECODE=1 $CM/team-preflight.sh $D; rc3=$RC
  if [[ $rc1 == 5 && $o1 == *"invalid HARNESS"* && $rc2 == 5 && $o2 == *"invalid HARNESS"* && $rc3 == 1 ]] && grep -q '^FAIL  invalid HARNESS' $SC/out && ! grep -q 'ADVISOR' $SC/out; then
    pass "S1 an invalid HARNESS in team.env is rejected (exit 5, a FAIL line in preflight, no advisor probe)"
  else fail "S1 an invalid HARNESS in team.env is rejected (exit 5, a FAIL line in preflight, no advisor probe)" "close: $rc1 '$o1'; advisor-probe: $rc2 '$o2'; preflight: $rc3 $(grep -E 'FAIL|ADVISOR' $SC/out | head -3 | tr '\n' '|')"; fi
}

# N1/N6: a test-only driver whose launch prints one line; team-init's driver-less and re-run paths.
want n1 && {
  cp -R $SKILLS $SB/src-oneline; mkdir -p $SB/src-oneline/agent-teammates/scripts/drivers/other
  : > $SB/src-oneline/agent-teammates/scripts/drivers/other/driver.env
  printf '#!/bin/sh\necho "id9 -"\n' > $SB/src-oneline/agent-teammates/scripts/drivers/other/launch; chmod +x $SB/src-oneline/agent-teammates/scripts/drivers/other/launch
  TREE=$SB/src-oneline; mk n1-oneline HARNESS=other; TREE=$SKILLS
  xrun $SB/src-oneline/agent-teammates/scripts/launch-teammate.sh $D t1 $SC/wt
  if [[ $RC == 0 && $(cat $SC/out | wc -l | tr -d ' ') == 1 && $(cat $SC/out) == "launched t1 as background session id9 in "* && $(awk '{print $1, $2}' $D/teammates.tsv) == "t1 id9" ]]; then pass "N1 a driver whose launch prints one line: exit 0, registered, nothing after launched"
  else fail "N1 a driver whose launch prints one line: exit 0, registered, nothing after launched" "exit $RC; out: $(cat $SC/out | head -c 300 | tr '\n' '|'); registry: $(cat $D/teammates.tsv | head -c 200)"; fi

  mk n1-nolaunch HARNESS=other
  xrun $AT/launch-teammate.sh $D t1 $SC/wt
  # (the real tree has no `other` driver, so this exercises drv's missing-operation path)
  if [[ $RC == 5 && ! -s $SC/out && ! -s $D/teammates.tsv ]]; then pass "N3 a driver with no launch: exit 5, nothing on stdout, no registry row"
  else fail "N3 a driver with no launch: exit 5, nothing on stdout, no registry row" "exit $RC; out: $(head -c 200 $SC/out)"; fi

  cp -R $SKILLS $SB/src-detect; mkdir -p $SB/src-detect/agent-teammates/scripts/drivers/other
  printf '#!/bin/sh\necho other\n' > $SB/src-detect/agent-teammates/scripts/detect-harness.sh
  sc n6-nodriver; xrun $SB/src-detect/commodore/scripts/team-init.sh run1 $SC/repo
  if [[ $RC == 7 && ! -e $SC/teams/run1 && $(cat $SC/out) == *"other: has no driver yet"* ]]; then pass "N6 a detected harness without a driver: exit 7, no run"
  else fail "N6 a detected harness without a driver: exit 7, no run" "exit $RC; out: $(head -c 300 $SC/out)"; fi

  SCDIR=init-rerun sc n6-rerun; SCDIR=
  xrun CLAUDECODE=1 $CM/team-init.sh run1 $SC/repo; xrun $CM/team-init.sh run1 $SC/repo
  d4 n6-rerun init-rerun $SC/teams/run1
}

# ======================================================================================================================
# D1: the advisor operation, and ADVISOR n/a when the driver has none.
# ======================================================================================================================
want d1 && {
  cp -R $SKILLS $SB/src-nodrv; rm -f $SB/src-nodrv/agent-teammates/scripts/drivers/claude/advisor-probe
  TREE=$SB/src-nodrv; HL=HARNESS=claude; mk d1-na ADVISOR_PROBE_TIMEOUT=0; HL=; TREE=$SKILLS; mk_repo
  xrun CLAUDECODE=1 ADVISOR_PROBE_TIMEOUT=0 $SB/src-nodrv/commodore/scripts/team-preflight.sh $D
  na=$(grep -c '^OK    ADVISOR n/a (claude)$' $SC/out)
  if [[ $RC == 0 && $na == 1 ]] && ! grep -q 'ADVISOR OFF' $SC/out; then pass "D1 driver without advisor-probe: ADVISOR n/a (claude), exit 0"
  else fail "D1 driver without advisor-probe: ADVISOR n/a (claude), exit 0" "exit $RC (want 0); n/a lines: $na (want 1); output: $(grep -i advisor $SC/out | head -4 | tr '\n' '|')"; fi
}

# ======================================================================================================================
# D2: the Claude driver's shape.
# ======================================================================================================================
DRV=$ROOT/skills/engineering/agent-teammates/scripts/drivers/claude
want d2 && {
  missing=(); for op in launch status tail stop advisor-probe; do [[ -x $DRV/$op ]] || missing+=$op; done
  (( $#missing )) && fail "D2 driver executables" "missing or not executable in ${DRV#$ROOT/}: ${missing[*]}" || pass "D2 driver executables"
  [[ ! -e $DRV/send ]] && pass "D2 no send executable" || fail "D2 no send executable" "${DRV#$ROOT/}/send exists; send goes through the SendMessage tool"
  if [[ -f $DRV/driver.env ]] && grep -q '^LIVE_MESSAGING=1$' $DRV/driver.env && grep -q '^SEND=tool$' $DRV/driver.env; then pass "D2 driver.env declares LIVE_MESSAGING=1 and SEND=tool"
  else fail "D2 driver.env declares LIVE_MESSAGING=1 and SEND=tool" "${DRV#$ROOT/}/driver.env: $([[ -f $DRV/driver.env ]] && echo "lacks LIVE_MESSAGING=1 or SEND=tool" || echo missing)"; fi
  undoc=(); for op in launch status tail stop send advisor-probe has-skill list-skills preflight; do grep -E '^### ' ${DRV:h}/CONTRACT.md 2>/dev/null | grep -q -- "$op" || undoc+=$op; done
  (( $#undoc )) && fail "D2 CONTRACT.md documents every operation" "no section heading mentions: ${undoc[*]}" || pass "D2 CONTRACT.md documents every operation"
}

# ======================================================================================================================
# u2: guidance and release. Text checks on the two skills' Markdown. They pin patterns that survive rewording; whether
# any instruction was lost is the reviewer's check against dfb39c8, not a test's.
# ======================================================================================================================
ATD=$ROOT/skills/engineering/agent-teammates
CMD=$ROOT/skills/engineering/commodore
ATH=$ATD/references/harness-claude.md
CMH=$CMD/references/harness-claude.md
skill_md=( $ATD/SKILL.md $ATD/references/*.md(N) $CMD/SKILL.md $CMD/references/*.md(N) )
shared_md=( ${skill_md:#$ATH} ); shared_md=( ${shared_md:#$CMH} )
git -C $ROOT cat-file -e ${REF}^{commit} 2>/dev/null; HAVE_REF=$?
NOREF="reference commit $REF not in this clone (shallow checkout?)"

# C2: Claude-only words appear only in the two harness-claude.md files.
want c2 && {
  hits=$(grep -nE 'SendMessage|\bMonitor\b|notify_when_idle|claude (agents|attach|logs|--bg|stop|rm)\b' $shared_md /dev/null | sed "s#$ROOT/##")
  [[ -z $hits ]] && pass "C2 no Claude-only terms outside harness-claude.md" || fail "C2 no Claude-only terms outside harness-claude.md" "$(print -r -- $hits | wc -l | tr -d ' ') lines, first 6:
$(print -r -- $hits | head -6)"
  for f in $ATH $CMH; do
    [[ -s $f ]] && pass "C2 ${f#$ROOT/} exists" || fail "C2 ${f#$ROOT/} exists" "missing or empty"
  done
  for s in $ATD $CMD; do
    f=$s/SKILL.md
    grep -qE '\]\(references/harness-claude\.md\)' $f && pass "C2 ${s:t}/SKILL.md links references/harness-claude.md" || fail "C2 ${s:t}/SKILL.md links references/harness-claude.md" "no Markdown link to (references/harness-claude.md)"
    grep -qF 'references/harness-<HARNESS>.md' $f && grep -q 'team\.env' $f && pass "C2 ${s:t}/SKILL.md states the harness-<HARNESS>.md rule" || fail "C2 ${s:t}/SKILL.md states the harness-<HARNESS>.md rule" "no 'references/harness-<HARNESS>.md' text next to a team.env mention"
  done
}

# D2 wording: both LIVE_MESSAGING variants for the marker line and the new-instructions line.
want d2w && {
  sec=$(awk '/^## /{p=($0=="## The teammate contract")} p' $ATD/SKILL.md)
  n1=$(print -r -- $sec | grep -c 'LIVE_MESSAGING=1'); n0=$(print -r -- $sec | grep -c 'LIVE_MESSAGING=0')
  (( n1 >= 2 && n0 >= 2 )) && pass "D2 contract carries LIVE_MESSAGING=1 and =0 for the marker and new-instructions lines" || fail "D2 contract carries LIVE_MESSAGING=1 and =0 for the marker and new-instructions lines" "teammate-contract section has $n1 lines with LIVE_MESSAGING=1 and $n0 with LIVE_MESSAGING=0 (want at least 2 each)"
  print -r -- $sec | grep 'LIVE_MESSAGING=0' | grep -qi 'exit' && pass "D2 contract's =0 marker line says exit" || fail "D2 contract's =0 marker line says exit" "no LIVE_MESSAGING=0 line in the contract mentions exiting"
  print -r -- $sec | grep 'LIVE_MESSAGING=0' | grep -qiE 'resum' && pass "D2 contract's =0 new-instructions line says the job arrives by resuming" || fail "D2 contract's =0 new-instructions line says the job arrives by resuming" "no LIVE_MESSAGING=0 line in the contract mentions resuming the session"
  grep -q 'LIVE_MESSAGING' $CMD/references/brief-common.md && pass "D2 brief-common template tells the coordinator which LIVE_MESSAGING variant to paste" || fail "D2 brief-common template tells the coordinator which LIVE_MESSAGING variant to paste" "commodore/references/brief-common.md never mentions LIVE_MESSAGING"
  awk '/^## /{p=($0 ~ /dvisor/)} p' $CMD/references/brief-common.md | grep -qiE 'harness' && pass "D2 brief-common 'Asking the advisor' says to drop it where there's no advisor" || fail "D2 brief-common 'Asking the advisor' says to drop it where there's no advisor" "no harness-conditional wording in the Asking the advisor section of commodore/references/brief-common.md"
  grep -qF 'always keep the `## Advisor consults` line' $CMD/references/brief-common.md && pass "D2 brief-common placeholder keeps ## Advisor consults" || fail "D2 brief-common placeholder keeps ## Advisor consults" "the contract placeholder in commodore/references/brief-common.md doesn't say to always keep the ## Advisor consults line"
}

# D3: the Claude default table from roles.md at dfb39c8 lives in commodore's harness-claude.md.
want d3 && if (( HAVE_REF )); then fail "D3 harness-claude.md holds every role's default model" "$NOREF"; else
  rows=(); while IFS= read -r row; do rows+=$row; done < <(git -C $ROOT show ${REF}:skills/engineering/commodore/references/roles.md | grep -E '^[|] .(implementer|reviewer|scribe)')
  miss=()
  for row in $rows; do
    model=$(print -r -- $row | awk -F'|' '{split($3, a, " "); print a[1]}')
    for role in $(print -r -- $row | awk -F'|' '{print $2}' | tr -d '` ' | tr ',' ' '); do
      grep -F -- "\`$role\`" $CMH 2>/dev/null | grep -qF -- $model || miss+="$role=$model"
    done
  done
  (( $#rows == 3 )) || miss+="(parsed ${#rows} rows from $REF roles.md, want 3)"
  grep -qi haiku $CMH 2>/dev/null || miss+="scribe=haiku allowed"
  (( $#miss )) && fail "D3 harness-claude.md holds every role's default model" "missing from ${CMH#$ROOT/}: ${miss[*]}" || pass "D3 harness-claude.md holds every role's default model"
fi

# C6: the Markdown lint and the descriptions. There is no changeset test: the release consumes the pending changeset, so
# a test that requires one fails on every release PR. Whether a PR carries a changeset is a review check.
want c6 && {
  if command -v markdownlint-cli2 >/dev/null; then
    if [[ -s $ATH && -s $CMH ]]; then
      out=$(cd $ROOT && markdownlint-cli2 ${skill_md#$ROOT/} 2>&1) && pass "C6 markdownlint-cli2 on both skills' Markdown" || fail "C6 markdownlint-cli2 on both skills' Markdown" "$(print -r -- $out | tail -8)"
    else fail "C6 markdownlint-cli2 on both skills' Markdown" "not linted: the harness-claude.md files don't exist yet"; fi
  else echo "skip  C6 markdownlint-cli2 (not on PATH; CI's markdown job lints)"; fi

  for s in agent-teammates commodore; do
    d=$(sed -n 's/^description: //p' $ROOT/skills/engineering/$s/SKILL.md | head -1)
    (( ${#d} > 0 && ${#d} <= 1024 )) && pass "C6 $s description is 1-1024 characters" || fail "C6 $s description is 1-1024 characters" "${#d} characters"
  done
  d=$(sed -n 's/^description: //p' $ROOT/skills/engineering/commodore/SKILL.md | head -1)
  [[ $d != *[Hh]arness* && $d == *"Use when"* ]] && pass "C6 commodore description says when to use it and leaves the harness to the body" || fail "C6 commodore description says when to use it and leaves the harness to the body" "${d:0:160}"
  d=$(sed -n 's/^description: //p' $ATD/SKILL.md | head -1)
  [[ $d != *"Claude Code"* && $d != *Codex* && $d != *Copilot* && $d != *[Hh]arness* ]] && pass "C6 agent-teammates description leaves the harness list to the references" || fail "C6 agent-teammates description leaves the harness list to the references" "${d:0:160}"
  [[ $d == *unattended* ]] && pass "C6 agent-teammates description keeps its unattended trigger" || fail "C6 agent-teammates description keeps its unattended trigger" "no 'unattended' in the description"
}

# ======================================================================================================================
# CODEX: the Codex driver (issue #39, ADR 0003). Turn-based: `launch` and `send` start `codex exec` / `codex exec resume`
# in the background and return; the fake codex in tests/bin stays running (mode hold) or finishes its turn at once.
# Black-box: every scenario goes through the shared scripts, never through the driver's own state files, and waits for
# "the process has exited" by polling the driver's `status` until it reports done. A run that has no Codex driver yet
# stops at the failed launch, so the red output names what is missing. Run just these with `tests/run.sh codex`.
# ======================================================================================================================
THR=019e1111-2222-7333-8444-555566667777      # the fake codex's default thread id
THR2=019e2222-3333-7444-8555-666677778888
CXD=$AT/drivers/codex
cx_sc() {  # cx_sc <scenario> [team.env line...]: a Codex run with the reviewer and implementer defaults team-init writes
  HL=HARNESS=codex; mk $1 MODEL=gpt-6.1-sol MODEL_REVIEWER=gpt-6-astra EFFORT_REVIEWER=high MODEL_IMPLEMENTER=gpt-6.1-sol EFFORT_IMPLEMENTER=medium "${@[2,-1]}"; HL=
  mkdir -p $SC/codex-home
  BASE+=( CODEX_HOME=$SC/codex-home )
}
# xrunb <seconds> [VAR=val ...] cmd args...: xrun, but a command that hasn't returned after <seconds> is killed (HUNG=1, RC=124).
xrunb() {
  local lim=$1 i=0 pid; shift
  ( cd $SC/cwd && exec env -i $BASE "$@" ) < /dev/null > $SC/out 2> $SC/err &
  pid=$!
  while kill -0 $pid 2>/dev/null && (( i++ < lim * 10 )); do /bin/sleep 0.1; done
  HUNG=
  if kill -0 $pid 2>/dev/null; then HUNG=1; kill $pid 2>/dev/null; RC=124; else wait $pid; RC=$?; fi
  wait $pid 2>/dev/null
  return 0
}
cx_wait() {  # cx_wait <seconds> <expression>: poll until the expression is true; 1 when it never is
  local i=0
  while ! eval "$2"; do (( i++ >= $1 * 10 )) && return 1; /bin/sleep 0.1; done
  return 0
}
cx_state() { env -i $BASE $CXD/status $D 2>/dev/null | awk -v t=$1 '$1==t {print $3}'; }
cx_over() { [[ $(cx_state $1) == (done|blocked) ]]; }       # the turn's process has exited
cx_reap() { : > $SC/fake/codex.release; }
cx_ok() {  # cx_ok <what>: the command xrunb ran returned 0 in time; else add why (with its output) to P and return 1
  if [[ -n $HUNG ]]; then P+="$1 didn't return while the turn was running (killed after the limit); out: $(head -c 200 $SC/out | tr '\n' '|') err: $(head -c 300 $SC/err | tr '\n' '|')"; return 1; fi
  [[ $RC == 0 ]] || { P+="$1: exit $RC (want 0); out: $(head -c 300 $SC/out | tr '\n' '|') err: $(head -c 300 $SC/err | tr '\n' '|')"; return 1; }
  return 0
}
# Assertions on one logged codex call, in $L: tokens are matched whole ("[x]" in the log).
A_has()  { [[ $L == *" [$1]"* ]] || P+="argv lacks [$1]"; }
A_no()   { [[ $L != *" [$1]"* ]] || P+="argv has [$1]"; }
A_pair() { [[ $L == *" [$1] [$2]"* ]] || P+="argv lacks [$1] [$2]"; }
A_cfg()  { local v; for v in "$@"; do [[ $L == *" [-c] [$v]"* ]] && return 0; done; P+="argv lacks -c ${(j: or :)@}"; }
A_safe() { [[ $L != *dangerously-bypass* && $L != *danger-full-access* ]] || P+="argv has --dangerously-bypass-approvals-and-sandbox or danger-full-access"; }
cx_first() { L=$(grep -a '^codex cwd=.*\[exec\]' $SC/claude.log | grep -av '\[resume\]' | head -1); [[ -n $L ]] || { P+="no 'codex exec' call was logged"; return 1; }; }
cx_resumed() { cx_wait 10 'grep -aq "^codex cwd=.*\[resume\]" $SC/claude.log'; }   # send returns once the turn has started, not once codex has run
cx_resume() { cx_resumed; L=$(grep -a '^codex cwd=.*\[resume\]' $SC/claude.log | tail -1); [[ -n $L ]] || { P+="no 'codex exec resume' call was logged"; return 1; }; }
A_ro() {  # A_ro launch|resume: the read-only flags
  if [[ $1 == launch ]]; then A_pair -s read-only; else A_cfg 'sandbox_mode=read-only' 'sandbox_mode="read-only"'; A_no -s; A_no -C; fi
  [[ $L == *" [--ignore-rules]"* ]] || P+="argv lacks --ignore-rules"
  [[ $L == *" [-o] [$D/codex-"*".out]"* ]] || P+="argv lacks -o <team>/codex-<name>.<n>.out (a path no sandbox can write)"; A_no $D/reports/t1.md; A_no --add-dir; [[ $L != *network_access* ]] || P+="argv has network_access"; A_safe
}
A_rw() {  # A_rw launch|resume: the writer flags
  if [[ $1 == launch ]]; then A_pair -s workspace-write; A_pair --add-dir $D/reports
  else A_cfg 'sandbox_mode=workspace-write' 'sandbox_mode="workspace-write"'; A_cfg "sandbox_workspace_write.writable_roots=[\"$D/reports\"]" "sandbox_workspace_write.writable_roots=['$D/reports']"; A_no -s; A_no -C; A_no --add-dir; fi
  A_cfg sandbox_workspace_write.network_access=true; A_no -o; A_no --ignore-rules; A_safe
}
cx_streams() {  # the background codex never holds the caller's stdout or stderr: its events and its stderr went to files under the team dir
  local f ev errs
  ev=(${(f)"$(grep -rla thread.started $D 2>/dev/null)"}); errs=(${(f)"$(grep -rla 'ERROR rmcp' $D 2>/dev/null)"})
  (( $#ev )) || P+="no file under $D holds the --json event log (thread.started)"
  (( $#errs )) || P+="codex's stderr isn't kept anywhere under $D"
  for f in $ev; do grep -qa 'ERROR rmcp' $f && P+="stderr lines leaked into the event log ${f#$D/}"; done
  grep -qaE 'thread.started|ERROR rmcp' $SC/out $SC/err 2>/dev/null && P+="codex's output reached the caller's stdout or stderr: $(head -c 200 $SC/out $SC/err | tr '\n' '|')"
  return 0
}
cx_row() { [[ $(tail -1 $D/teammates.tsv 2>/dev/null) == "t1 ${2:-$THR} $1 - $SC/wt" ]] || P+="registry's last row: '$(tail -1 $D/teammates.tsv 2>/dev/null)' (want t1 ${2:-$THR} $1 - $SC/wt)"; }
cx_launch() {  # cx_launch <mode> <launch-teammate args...>: run it with a bounded wait under the fake's <mode>
  local m=$1; shift
  xrunb 20 FAKE_CODEX_MODE=$m $AT/launch-teammate.sh "$@"
}
rollout() { print -r -- "$(<$SC/fake/codex.rollout)"; }

# ---- AC3: launch --------------------------------------------------------------------------------------------------
want codex-launch && {
  cx_sc codex-launch-reviewer
  cx_launch hold --read-only --role reviewer $D t1 $SC/wt
  cx_ok "launch-teammate.sh --read-only --role reviewer" && {
    [[ $(<$SC/out) == "launched t1 as background session $THR in $SC/wt (read-only)" ]] || P+="stdout: $(head -c 200 $SC/out | tr '\n' '|')"
    cx_row $NOW
    cx_first && {
      A_has exec; A_has --json; A_has --skip-git-repo-check; A_pair -C $SC/wt; A_pair -m gpt-6-astra
      A_cfg model_reasoning_effort=high 'model_reasoning_effort="high"'; A_ro launch
      [[ $L == *"t1"* && $L == *"$D/prompts/t1.md"* ]] || P+="the prompt names neither t1 nor $D/prompts/t1.md"
      [[ $L == *"[You are teammate t1. Read $D/prompts/t1.md and do exactly what it says. "*"can't write files"*"your final message is your report."* ]] || P+="the read-only prompt doesn't say the sandbox is read-only and the final message is the report"
      (( $#P )) && P+="argv: ${L#codex }"
    }
    [[ $(cx_state $THR) == working ]] || P+="status says '$(cx_state $THR)' while the turn runs (want working)"
    cx_streams
  }
  cx_reap
  verdict "CODEX AC3 --read-only --role reviewer: codex exec -s read-only, gpt-6-astra, high effort, -o <team>/reports/t1.md, returns while the turn runs"

  cx_sc codex-launch-implementer
  cx_launch hold --role implementer $D t1 $SC/wt
  cx_ok "launch-teammate.sh --role implementer" && {
    [[ $(<$SC/out) == "launched t1 as background session $THR in $SC/wt" ]] || P+="stdout: $(head -c 200 $SC/out | tr '\n' '|')"
    cx_row $NOW
    cx_first && {
      [[ $L == *"[You are teammate t1. Read $D/prompts/t1.md and do exactly what it says.]"* ]] || P+="the writer's prompt isn't the plain one"
      A_has exec; A_has --json; A_pair -C $SC/wt; A_pair -m gpt-6.1-sol; A_cfg model_reasoning_effort=medium 'model_reasoning_effort="medium"'; A_rw launch
      (( $#P )) && P+="argv: ${L#codex }"
    }
    [[ $(cx_state $THR) == working ]] || P+="status says '$(cx_state $THR)' while the turn runs (want working)"
    pg=$(<$SC/fake/codex.pgid); pid=$(<$SC/fake/codex.pid); me=$(ps -o pgid= -p $$ | tr -d ' ')
    [[ $pg == $pid ]] || P+="the writer's codex (pid $pid) isn't its own process-group leader (pgid $pg)"
    [[ $pg != $me ]] || P+="codex runs in the caller's process group"
    cx_streams
  }
  cx_reap
  verdict "CODEX AC3 --role implementer: workspace-write, network access, --add-dir <team>/reports, no -o, own process group, returns while the turn runs"

  cx_sc codex-launch-noeffort EFFORT_REVIEWER=
  cx_launch ok --read-only --role reviewer $D t1 $SC/wt
  cx_ok "launch with an empty EFFORT_REVIEWER" && { cx_first && { A_pair -m gpt-6-astra; [[ $L != *model_reasoning_effort* ]] || P+="an empty effort was passed: ${L#codex }"; }; }
  verdict "CODEX effort: an empty EFFORT_<ROLE> passes no model_reasoning_effort"
  cx_sc codex-launch-leak
  xrunb 20 FAKE_CODEX_MODE=ok TEAMMATE_EFFORT=xhigh $AT/launch-teammate.sh --model gpt-9 $D t1 $SC/wt
  cx_ok "launch --model with TEAMMATE_EFFORT=xhigh in the caller's environment" && { cx_first && { A_pair -m gpt-9; [[ $L != *model_reasoning_effort* && $L != *xhigh* ]] || P+="the caller's effort leaked into argv: ${L#codex }"; }; }
  verdict "CODEX effort: a launch without --role passes no effort, whatever the caller's environment holds"

  Q=$SB/w/codex-launch-quoting
  cx_sc codex-launch-quoting "PERMISSION_MODE=bypassPermissions" "MODEL_REVIEWER='a b;c \$(touch $Q/pwned) \"q\"'" "EFFORT_REVIEWER='very high'"
  cx_launch ok --read-only --role reviewer $D t1 $SC/wt
  cx_ok "launch with quoted MODEL_REVIEWER and EFFORT_REVIEWER" && { cx_first && {
    A_pair -m "a b;c \$(touch $Q/pwned) \"q\""; A_cfg 'model_reasoning_effort=very high' 'model_reasoning_effort="very high"'
    [[ $L != *bypass* && $L != *approval* && $L != *PERMISSION* ]] || P+="PERMISSION_MODE reached codex: ${L#codex }"; A_safe
    (( $#P )) && P+="argv: ${L#codex }"
  }; }
  cx_wait 3 '[[ -e $Q/pwned ]]' && P+="a MODEL_ value was executed (the file $Q/pwned exists)"
  verdict "CODEX quoting: MODEL_/EFFORT_ values reach codex as single arguments, are never executed, and PERMISSION_MODE maps to nothing"

  cx_sc codex-launch-live
  cx_launch hold --role implementer $D t1 $SC/wt
  cx_ok "first launch" && {
    xrunb 20 FAKE_CODEX_MODE=hold FAKE_CODEX_THREAD=$THR2 $AT/launch-teammate.sh --role implementer $D t1 $SC/wt
    [[ $RC == 5 ]] || P+="second launch of a live name: exit $RC (want 5); out: $(head -c 200 $SC/out | tr '\n' '|')"
    n=$(grep -ac '^codex cwd=' $SC/claude.log); (( n == 1 )) || P+="$n codex calls (want 1: the refused launch starts nothing)"
    [[ $(wc -l < $D/teammates.tsv | tr -d ' ') == 1 ]] || P+="registry rows: $(wc -l < $D/teammates.tsv | tr -d ' ') (want 1)"
  }
  cx_reap
  verdict "CODEX launch of a name that is already live: exit 5, nothing started, no new row"

  cx_sc codex-launch-nothread
  xrunb 90 FAKE_CODEX_MODE=silent $AT/launch-teammate.sh --role implementer $D t1 $SC/wt
  [[ -z $HUNG ]] || P+="launch never gave up on a codex that prints no thread.started"
  [[ $RC == 1 ]] || P+="exit $RC (want 1); out: $(head -c 200 $SC/out | tr '\n' '|')"
  [[ ! -s $D/teammates.tsv ]] || P+="a row was registered: $(<$D/teammates.tsv)"
  [[ -f $SC/fake/codex.pid ]] && { cx_wait 10 '! kill -0 $(<$SC/fake/codex.pid) 2>/dev/null' || P+="the codex it started (pid $(<$SC/fake/codex.pid)) is still running"; }
  cx_reap
  verdict "CODEX launch with no thread.started: kills what it started, exit 1, no row"
  errf=$(print -r -- $D/codex-t1.*.err(N))
  [[ -n $errf && -f $errf && $(<$SC/out) == *"$errf"* ]] || P+="the failed launch kept no stderr file, or didn't print its path: '$errf'; out: $(head -c 300 $SC/out | tr '\n' '|')"
  verdict "CODEX launch with no thread.started: keeps codex's stderr file and prints its path"
}

# ---- AC4: retask -> send -----------------------------------------------------------------------------------------
want codex-retask && {
  cx_sc codex-retask-reviewer
  cx_launch ok --read-only --role reviewer $D t1 $SC/wt
  cx_ok "launch" && {
    cx_wait 10 'cx_over $THR' || P+="the launch turn's process never reported done (status: '$(cx_state $THR)')"
    cx_wait 10 '[[ -e $D/reports/t1.done ]]'; rm -f $D/reports/t1.done
    print -r -- "next job" > $SC/msg.md
    xrunb 20 FAKE_NOW=$((NOW + 500)) $AT/retask.sh $D t1 $SC/msg.md
    cx_ok "retask.sh" && {
      [[ $(<$SC/out) == "t1 re-tasked (session $THR)" ]] || P+="stdout: $(head -c 200 $SC/out | tr '\n' '|')"
      cx_resume && {
        [[ $L == "codex cwd=$SC/wt "* ]] || P+="resume ran in '${${L#codex cwd=}%% *}' (want the workdir $SC/wt)"
        A_pair exec resume; A_has $THR; A_pair -m gpt-6-astra; A_cfg model_reasoning_effort=high 'model_reasoning_effort="high"'; A_ro resume; A_has --json
        (( $#P )) && P+="argv: ${L#codex }"
      }
      cx_wait 5 'grep -aqx "codex stdin: next job" $SC/claude.log'
      grep -aqx 'codex stdin: next job' $SC/claude.log || P+="the message wasn't passed on stdin (no 'codex stdin: next job' in the log)"
      [[ $(wc -l < $D/teammates.tsv | tr -d ' ') == 2 ]] || P+="registry rows: $(wc -l < $D/teammates.tsv | tr -d ' ') (want 2)"
      cx_row $((NOW + 500))
      grep -qaE 'thread.started|ERROR rmcp' $SC/out $SC/err && P+="the resumed codex's output reached the caller: $(head -c 200 $SC/out $SC/err | tr '\n' '|')"
      cx_wait 10 '[[ -e $D/reports/t1.done ]]' || P+="the resumed turn completed but the driver wrote no reports/t1.done"
    }
  }
  verdict "CODEX AC4 retask.sh on a read-only teammate: codex exec resume <thread> in its workdir, same flags as -c config, message on stdin, watchdog row, marker after the turn"

  cx_sc codex-retask-implementer
  cx_launch ok --role implementer $D t1 $SC/wt
  cx_ok "launch" && {
    cx_wait 10 'cx_over $THR' || P+="the launch turn's process never reported done (status: '$(cx_state $THR)')"
    print -r -- "next job" > $SC/msg.md
    xrunb 20 FAKE_NOW=$((NOW + 500)) $AT/retask.sh $D t1 $SC/msg.md
    cx_ok "retask.sh" && {
      cx_resume && {
        [[ $L == "codex cwd=$SC/wt "* ]] || P+="resume ran in '${${L#codex cwd=}%% *}' (want the workdir $SC/wt)"
        A_pair exec resume; A_has $THR; A_pair -m gpt-6.1-sol; A_cfg model_reasoning_effort=medium 'model_reasoning_effort="medium"'; A_rw resume
        (( $#P )) && P+="argv: ${L#codex }"
      }
      cx_row $((NOW + 500))
    }
  }
  verdict "CODEX AC4 retask.sh on a writer: resume repeats workspace-write, network access and the reports/ writable root as -c config; no -o"

  cx_sc codex-retask-running
  cx_launch hold --role implementer $D t1 $SC/wt
  cx_ok "launch" && {
    print -r -- "next job" > $SC/msg.md; cp $D/teammates.tsv $SC/tsv.before
    xrunb 20 FAKE_NOW=$((NOW + 500)) $AT/retask.sh $D t1 $SC/msg.md
    [[ -z $HUNG && $RC != 0 ]] || P+="retask.sh on a teammate whose turn is still running: exit $RC${HUNG:+ (hung)} (want non-zero)"
    cx_wait 2 'grep -aq "^codex cwd=.*\[resume\]" $SC/claude.log' && P+="a second codex was started while the first still runs"
    cmp -s $D/teammates.tsv $SC/tsv.before || P+="the registry changed: $(tr '\n' '|' < $D/teammates.tsv)"
  }
  cx_reap
  verdict "CODEX AC4 retask.sh while the previous turn still runs: non-zero, no second process, registry untouched"
}

# ---- AC5: the watchdog -----------------------------------------------------------------------------------------------
want codex-watch && {
  cx_sc codex-watch-done
  cx_launch ok --role implementer $D t1 $SC/wt
  cx_ok "launch" && {
    cx_wait 10 'cx_over $THR' || P+="the turn's process never reported done (status: '$(cx_state $THR)')"
    : > $D/reports/t1.done; settime $NOW $D/reports/t1.done
    xrun_watch 1 $AT/watch-teammates.sh $D
    [[ -n $REACHED ]] || P+="the watcher never reached its poll limit"
    grep -qx 'DONE t1' $SC/out || P+="no 'DONE t1'; stdout: $(tr '\n' '|' < $SC/out)"
    grep -q '^GONE' $SC/out && P+="GONE after DONE: $(tr '\n' '|' < $SC/out)"
  }
  verdict "CODEX AC5 a writer that wrote its marker and exited: DONE, no GONE"

  cx_sc codex-watch-exited
  cx_launch ok --role implementer $D t1 $SC/wt
  cx_ok "launch" && {
    cx_wait 10 'cx_over $THR' || P+="the turn's process never reported done (status: '$(cx_state $THR)')"
    xrun_watch 3 $AT/watch-teammates.sh $D
    [[ -n $REACHED ]] || P+="the watcher never reached its poll limit"
    grep -q '^GONE' $SC/out && P+="GONE for a teammate whose process exited after its turn: $(tr '\n' '|' < $SC/out)"
    grep -qx "BLOCKED t1 $THR" $SC/out || P+="no 'BLOCKED t1 $THR' after two polls of an exited teammate without a marker; stdout: $(tr '\n' '|' < $SC/out)"
  }
  verdict "CODEX AC5 an exited teammate without a fresh marker: BLOCKED after two polls, never GONE"

  cx_sc codex-watch-readonly
  cx_launch ok --read-only --role reviewer $D t1 $SC/wt
  cx_ok "launch" && {
    cx_wait 10 '[[ -e $D/reports/t1.done ]]' || P+="the read-only teammate's marker never appeared"
    xrun_watch 1 $AT/watch-teammates.sh $D
    grep -qx 'DONE t1' $SC/out || P+="no 'DONE t1'; stdout: $(tr '\n' '|' < $SC/out)"
    grep -q '^GONE' $SC/out && P+="GONE after DONE: $(tr '\n' '|' < $SC/out)"
  }
  verdict "CODEX AC5 a read-only teammate whose driver wrote the marker: DONE, no GONE"

  cx_sc codex-watch-stall
  cx_launch hold --role implementer $D t1 $SC/wt
  cx_ok "launch" && {
    cx_wait 5 '[[ -e $SC/fake/codex.ready ]]' || P+="the fake codex never became ready"
    settime $((NOW - 60)) $(rollout)
    xrun_watch 1 $AT/watch-teammates.sh $D
    grep -q '^STALL' $SC/out && P+="STALL with a rollout written 1 min ago: $(tr '\n' '|' < $SC/out)"
    rm -f $SC/fake/sleep.reached $SC/fake/sleep.release $SC/fake/sleep.count
    settime $((NOW - 900)) $(rollout)
    xrun_watch 1 $AT/watch-teammates.sh $D
    grep -qx "STALL t1 $THR 15" $SC/out || P+="no 'STALL t1 $THR 15' for a rollout untouched for 15 min; stdout: $(tr '\n' '|' < $SC/out)"
  }
  cx_reap
  verdict "CODEX AC5 a running teammate whose rollout is 15 min old: STALL t1 <id> 15 (and none when it is fresh)"
}

# ---- watch-teammates.sh --until-event: one bounded call, for a coordinator with no Monitor tool ---------------------------------
want codex-watch-bounded && {
  polls() { grep -ac '\[agents\]' $SC/claude.log; }
  mk watch-bound-event; mkdir -p $D/reports; reg t1 d0e1f2a3 $((NOW - 600)) - $SC/wt
  : > $D/reports/t1.done; settime $((NOW - 100)) $D/reports/t1.done
  agents_all 1 d0e1f2a3 t1 idle done
  xrun $AT/watch-teammates.sh --until-event 5 $D
  [[ $RC == 0 && $(<$SC/out) == "DONE t1" ]] || P+="first run: exit $RC, stdout '$(tr '\n' '|' < $SC/out)' (want exit 0, 'DONE t1')"
  (( $(polls) == 1 )) || P+="the run polled $(polls) times (want 1: it ends right after the poll that printed an event)"
  xrun $AT/watch-teammates.sh --until-event 2 $D
  [[ $RC == 0 && $(<$SC/out) == "WATCH timeout 2" ]] || P+="rerun: exit $RC, stdout '$(tr '\n' '|' < $SC/out)' (want only 'WATCH timeout 2': DONE isn't repeated)"
  verdict "CODEX watch --until-event: an event ends the run after its poll; a rerun doesn't repeat DONE; the timeout prints WATCH timeout"

  mk watch-bound-timeout; reg t1 d0e1f2a3 $((NOW - 60)) - $SC/wt
  agents_all 1 d0e1f2a3 t1 working working
  xrun $AT/watch-teammates.sh --until-event 3 $D
  [[ $RC == 0 && $(<$SC/out) == "WATCH timeout 3" ]] || P+="exit $RC, stdout '$(tr '\n' '|' < $SC/out)' (want exit 0, 'WATCH timeout 3')"
  (( $(polls) == 3 )) || P+="polled $(polls) times (want 3)"
  verdict "CODEX watch --until-event: with no event it ends after <max-min> polls"

  mk watch-bound-blocked; reg t1 d0e1f2a3 $((NOW - 600)) - $SC/wt
  agents_all 1 d0e1f2a3 t1 idle blocked
  xrun $AT/watch-teammates.sh --until-event 1 $D
  [[ $(<$SC/out) == "WATCH timeout 1" ]] || P+="run 1: '$(tr '\n' '|' < $SC/out)' (want only the timeout: one blocked poll isn't BLOCKED)"
  xrun $AT/watch-teammates.sh --until-event 1 $D
  [[ $(<$SC/out) == "BLOCKED t1 d0e1f2a3" ]] || P+="run 2: '$(tr '\n' '|' < $SC/out)' (want 'BLOCKED t1 d0e1f2a3': the blocked count persists)"
  xrun $AT/watch-teammates.sh --until-event 1 $D
  [[ $(<$SC/out) == "WATCH timeout 1" ]] || P+="run 3: '$(tr '\n' '|' < $SC/out)' (want no second BLOCKED within 10 minutes)"
  verdict "CODEX watch --until-event: BLOCKED fires across two bounded runs and doesn't repeat within 10 minutes"

  mk watch-bound-failed; mkdir -p $D/reports; reg t1 d0e1f2a3 $((NOW - 600)) - $SC/wt
  : > $D/reports/t1.done; settime $((NOW - 100)) $D/reports/t1.done
  xrun FAKE_AGENTS_FAIL=1 $AT/watch-teammates.sh --until-event 5 $D
  [[ $RC == 0 && $(<$SC/out) == "DONE t1" ]] || P+="exit $RC, stdout '$(tr '\n' '|' < $SC/out)' (want exit 0, 'DONE t1' right after the poll whose status failed)"
  (( $(polls) == 1 )) || P+="polled $(polls) times (want 1)"
  verdict "CODEX watch --until-event: an event printed in a poll whose status failed ends the run"

  mk watch-bound-usage
  xrun $AT/watch-teammates.sh --until-event $D
  [[ $RC == 5 ]] || P+="--until-event without a number: exit $RC (want 5)"
  verdict "CODEX watch --until-event: a missing or non-numeric bound is a usage error"
}

# ---- status, tail ----------------------------------------------------------------------------------------------------
want codex-status && {
  cx_sc codex-status
  cx_launch hold --role implementer $D t1 $SC/wt
  cx_ok "launch" && {
    settime $((NOW - 123)) $(rollout)
    xrun $CXD/status $D
    [[ $RC == 0 ]] || P+="status exit $RC (want 0); err: $(head -c 200 $SC/err)"
    [[ $(<$SC/out) == "$THR - working $((NOW - 123))" ]] || P+="status: '$(<$SC/out)' (want '$THR - working $((NOW - 123))')"
    cx_reap
    cx_wait 10 'cx_over $THR' || P+="after its turn the process never reported done or blocked (status: '$(cx_state $THR)')"
    xrun $CXD/status $D
    [[ $(<$SC/out) == "$THR - "(done|blocked)" "* ]] || P+="after the turn: '$(<$SC/out)' (want '$THR - done <epoch|->')"
  }
  verdict "CODEX status: working with the rollout's mtime, then done once the turn's process has exited"
}
want codex-tail && {
  cx_sc codex-tail
  cx_launch ok --role implementer $D t1 $SC/wt
  cx_ok "launch" && {
    cx_wait 10 'cx_over $THR' || P+="the turn's process never reported done (status: '$(cx_state $THR)')"
    settime $((NOW - 420)) $(rollout)
    xrun $AT/teammate-tail.sh $D t1
    [[ $RC == 0 ]] || P+="tail exit $RC (want 0); out: $(head -c 200 $SC/out | tr '\n' '|') err: $(head -c 200 $SC/err | tr '\n' '|')"
    [[ $(head -1 $SC/out) == "transcript: "?*"  (last write 7 min ago)" ]] || P+="first line: '$(head -1 $SC/out)' (want 'transcript: <path>  (last write 7 min ago)')"
    [[ $(grep -c '^TOOL  .*ls -la' $SC/out) == 1 && $(grep -c '^TOOL  .*git status' $SC/out) == 1 ]] || P+="want one TOOL line each for 'ls -la' and 'git status' (a tool call is logged as started and completed): $(tr '\n' '|' < $SC/out | head -c 400)"
    grep -q '^SAID  All done here' $SC/out || P+="no 'SAID  All done here' line: $(tr '\n' '|' < $SC/out | head -c 300)"
    xrun $AT/teammate-tail.sh $D t1 1
    grep -q '^TOOL  .*git status' $SC/out && ! grep -q 'ls -la' $SC/out && grep -q '^SAID  All done here' $SC/out || P+="tail n=1 should show the last tool call and the latest message: $(tr '\n' '|' < $SC/out | head -c 300)"
    print -r -- "second job" > $SC/msg.md
    xrunb 20 FAKE_CODEX_REPLY="Second turn here" FAKE_CODEX_TOOLS=0 $AT/retask.sh $D t1 $SC/msg.md
    cx_ok "retask.sh" && {
      cx_wait 10 'grep -rqa "Second turn here" $D'; cx_wait 10 'cx_over $THR'
      xrun $AT/teammate-tail.sh $D t1
      grep -q '^SAID  Second turn here' $SC/out || P+="after the second turn no 'SAID  Second turn here': $(tr '\n' '|' < $SC/out | head -c 300)"
      grep -q '^TOOL  .*ls -la' $SC/out || P+="the first turn's tool calls are gone after the second turn: $(tr '\n' '|' < $SC/out | head -c 300)"
    }
  }
  verdict "CODEX tail: transcript line, TOOL and SAID lines, -n, and every turn (not just the latest)"

  cx_sc codex-tail-missing; reg t1 019eaaaa-0000-7000-8000-000000000000 1789999000 - $SC/wt
  xrun $AT/teammate-tail.sh $D t1
  [[ $RC == 3 && -n $(cat $SC/out $SC/err) ]] || P+="exit $RC (want 3 with a message); out: $(head -c 200 $SC/out | tr '\n' '|')"
  verdict "CODEX tail of an unknown session: exit 3 with a message"
}

# ---- AC6: close ------------------------------------------------------------------------------------------------------
want codex-close && {
  cx_sc codex-close
  cx_launch hold --read-only --role reviewer $D t1 $SC/wt
  cx_ok "launch" && {
    pid=$(<$SC/fake/codex.pid); pg=$(<$SC/fake/codex.pgid); ro=$(rollout)
    [[ $pg != $(ps -o pgid= -p $$ | tr -d ' ') ]] || P+="codex runs in the caller's process group"
    xrunb 20 $AT/close-teammate.sh $D t1
    cx_ok "close-teammate.sh" && {
      [[ $(<$SC/out) == "stopped t1 ($THR)" ]] || P+="stdout: $(head -c 200 $SC/out | tr '\n' '|')"
      cx_wait 10 '! kill -0 $pid 2>/dev/null' || P+="codex (pid $pid) is still running after close-teammate.sh"
      cx_wait 10 '! kill -0 -- -$pg 2>/dev/null' || P+="process group $pg still has members after close-teammate.sh"
      [[ -f $ro ]] || P+="the rollout $ro was removed"
      [[ $(cx_state $THR) == stopped ]] || P+="status says '$(cx_state $THR)' after the stop (want stopped)"
      [[ $(tail -1 $D/teammates.tsv | awk '{print $3}') == closed ]] || P+="registry's last row isn't closed: $(tail -1 $D/teammates.tsv)"
      grep -a '^codex cwd=' $SC/claude.log | grep -qav '\[exec\]' && P+="a codex call other than exec: $(grep -a '^codex cwd=' $SC/claude.log | grep -av '\[exec\]' | head -2 | tr '\n' '|')"
    }
  }
  cx_reap
  verdict "CODEX AC6 close-teammate.sh: kills the whole process group, keeps the rollout, status stopped, no codex delete"

  cx_sc codex-close-child
  xrunb 20 FAKE_CODEX_MODE=hold FAKE_CODEX_CHILD=1 $AT/launch-teammate.sh --role implementer $D t1 $SC/wt
  cx_ok "launch" && {
    cx_wait 5 '[[ -s $SC/fake/codex.child ]]' || P+="the fake never started its tool command"
    kid=$(<$SC/fake/codex.child)
    cx_wait 5 '[[ $(ps -o pgid= -p $kid | tr -d " ") == $kid ]]' || P+="the tool command isn't in a group of its own"
    pg=$(<$SC/fake/codex.pgid)
    [[ $(ps -o pgid= -p $kid | tr -d " ") != $pg ]] || P+="the tool command shares codex's group, so the test can't tell"
    xrunb 20 $AT/close-teammate.sh $D t1
    cx_wait 10 '! kill -0 $kid 2>/dev/null' || P+="the tool command (pid $kid, own process group) survived close-teammate.sh"
  }
  kill $(<$SC/fake/codex.child) 2>/dev/null
  cx_reap
  verdict "CODEX AC6 close-teammate.sh also ends a tool command that runs in a process group of its own"

  # The one white-box check: stop signals a recorded process group only after `ps -o args=` shows it is this session's
  # codex. The state is pointed at a decoy group (a sleep in its own session) as if the pid had been reused.
  cx_sc codex-close-decoy
  cx_launch hold --role implementer $D t1 $SC/wt
  cx_ok "launch" && {
    ( cd $SC/cwd && exec env -i $BASE python3 -c 'import os; os.setsid(); os.execvp("/bin/sleep", ["/bin/sleep", "60"])' ) < /dev/null > /dev/null 2>&1 &
    decoy=$!
    cx_wait 5 '[[ $(ps -o pgid= -p $decoy | tr -d " ") == $decoy ]]' || P+="the decoy never became a group leader"
    print -r -- "PID=$decoy" >> $D/codex-$THR.state; print -r -- "PGID=$decoy" >> $D/codex-$THR.state
    xrunb 20 $AT/close-teammate.sh $D t1
    [[ $(<$SC/out) == "t1 ($THR) was not running" ]] || P+="stdout: $(head -c 200 $SC/out | tr '\n' '|')"
    kill -0 $decoy 2>/dev/null || P+="close-teammate.sh signalled a process group that isn't the session's codex"
    kill $decoy 2>/dev/null
  }
  cx_reap
  verdict "CODEX AC6 stop checks that the recorded process group still is this session's codex before it signals"

  cx_sc codex-close-exited
  cx_launch ok --role implementer $D t1 $SC/wt
  cx_ok "launch" && {
    cx_wait 10 'cx_over $THR' || P+="the turn's process never reported done (status: '$(cx_state $THR)')"
    xrunb 20 $AT/close-teammate.sh $D t1
    cx_ok "close-teammate.sh" && { [[ $(<$SC/out) == "t1 ($THR) was not running" ]] || P+="stdout: $(head -c 200 $SC/out | tr '\n' '|')"; }
  }
  verdict "CODEX AC6 closing a teammate whose process already exited: 'was not running'"
}

# ---- D7: where teammates write; the driver's marker for read-only roles ---------------------------------------------------
want codex-marker && {
  cx_sc codex-marker-ok
  cx_launch hold --read-only --role reviewer $D t1 $SC/wt
  cx_ok "launch" && {
    [[ ! -e $D/reports/t1.done ]] || P+="the marker exists while the turn is still running"
    cx_reap
    cx_wait 10 '[[ -e $D/reports/t1.done ]]' || P+="no reports/t1.done after the turn completed with a report"
    [[ -s $D/reports/t1.md ]] || P+="reports/t1.md is missing or empty after the turn"
  }
  verdict "CODEX D7 read-only: the driver touches the marker after a completed turn with a report, not before"

  cx_sc codex-marker-symlink
  : > $SC/victim-md; : > $SC/victim-done; print -r -- keep > $SC/victim-md; print -r -- keep > $SC/victim-done
  cx_launch hold --read-only --role reviewer $D t1 $SC/wt
  cx_ok "launch" && {
    ln -s $SC/victim-md $D/reports/t1.md; ln -s $SC/victim-done $D/reports/t1.done
    cx_reap
    cx_wait 10 '[[ -f $D/reports/t1.done && ! -L $D/reports/t1.done ]]' || P+="reports/t1.done didn't become a regular file"
    [[ -f $D/reports/t1.md && ! -L $D/reports/t1.md && -s $D/reports/t1.md ]] || P+="reports/t1.md isn't a non-empty regular file"
    [[ $(<$SC/victim-md) == keep && $(<$SC/victim-done) == keep ]] || P+="a planted symlink was followed: md='$(<$SC/victim-md)' done='$(<$SC/victim-done)'"
  }
  verdict "CODEX D7 read-only: symlinks planted at reports/<name>.md and .done are replaced, never followed"

  marker_none() {  # marker_none <check name> <FAKE_CODEX_* assignment...>: a read-only turn that must not get a marker
    local nm=$1; shift
    cx_sc codex-marker-${nm// /-}
    xrunb 20 FAKE_CODEX_MODE=ok "$@" $AT/launch-teammate.sh --read-only --role reviewer $D t1 $SC/wt
    cx_ok "launch" && {
      cx_wait 10 'cx_over $THR' || P+="the turn's process never reported done (status: '$(cx_state $THR)')"
      /bin/sleep 1
      [[ ! -e $D/reports/t1.done ]] || P+="reports/t1.done exists after $nm"
    }
    verdict "CODEX D7 read-only: no marker after $nm"
  }
  marker_none "a failed turn" FAKE_CODEX_MODE=fail
  marker_none "an empty report" FAKE_CODEX_REPORT=empty
  marker_none "a turn that wrote no report" FAKE_CODEX_REPORT=none

  cx_sc codex-marker-writer
  cx_launch ok --role implementer $D t1 $SC/wt
  cx_ok "launch" && {
    cx_wait 10 'cx_over $THR' || P+="the turn's process never reported done (status: '$(cx_state $THR)')"
    /bin/sleep 1
    [[ ! -e $D/reports/t1.done ]] || P+="the driver wrote reports/t1.done for a writer (the teammate writes its own)"
    [[ ! -e $D/reports/t1.md ]] || P+="the driver wrote reports/t1.md for a writer"
  }
  verdict "CODEX D7 writer: the driver writes neither marker nor report"
}

# ---- AC2: team-preflight on a Codex run ---------------------------------------------------------------------------------
RULES_ALL=( 'prefix_rule(pattern=["git", "add"], decision="allow")' 'prefix_rule(pattern=["git", "commit"], decision="allow")' )
cxp() {  # cxp <scenario> [VAR=val ...]: team-preflight on a Codex run (no ADVISOR_PROBE); rules come from $SC/codex-home/rules
  cx_sc $1; mk_repo; mkdir -p $SC/codex-home/rules; shift
}
cxp_run() { xrun CODEX_THREAD_ID=019e-test "$@" $CM/team-preflight.sh $D; }
cxp_bad() { grep -E '^(FAIL|WARN)' $SC/out | grep -E 'prefix_rule|codex'; }   # the codex lines that aren't OK
want codex-preflight && {
  cxp codex-pf-ok; print -rl -- $RULES_ALL > $SC/codex-home/rules/default.rules; cxp_run
  grep -qx 'OK    ADVISOR n/a (codex)' $SC/out || P+="no 'OK    ADVISOR n/a (codex)': $(grep ADVISOR $SC/out | head -2 | tr '\n' '|')"
  [[ -z $(cxp_bad) ]] || P+="codex FAIL/WARN lines with every rule present: $(cxp_bad | tr '\n' '|')"
  grep -qE '^OK +codex' $SC/out || P+="no OK line about codex besides the advisor one (one starting 'OK    codex', e.g. 'OK    codex found'): $(grep '^OK' $SC/out | head -4 | tr '\n' '|')"
  grep -q Traceback $SC/out $SC/err && P+="a traceback: $(grep -h -A3 Traceback $SC/out $SC/err | head -4 | tr '\n' '|')"
  verdict "CODEX AC2 preflight with every rule present: ADVISOR n/a (codex), an OK line for codex, nothing to FAIL or WARN"

  cxp codex-pf-missing; print -rl -- ${RULES_ALL:#*commit*} > $SC/codex-home/rules/default.rules; cxp_run
  want_line='prefix_rule(pattern=["git", "commit"], decision="allow")'
  [[ $RC == 1 ]] || P+="exit $RC (want 1)"
  [[ -n $(grep '^FAIL' $SC/out | grep -F -- $want_line) ]] || P+="no FAIL line with $want_line; FAIL lines: $(grep '^FAIL' $SC/out | head -3 | tr '\n' '|')"
  [[ $(cxp_bad | grep -c prefix_rule) == 1 ]] || P+="want exactly one rule line named; got: $(cxp_bad | tr '\n' '|')"
  verdict "CODEX AC2 preflight with git commit missing: FAIL naming that exact prefix_rule line, exit 1"

  cxp codex-pf-norules; cxp_run
  for r in $RULES_ALL; do [[ -n $(grep '^FAIL' $SC/out | grep -F -- $r) ]] || P+="no FAIL naming $r"; done
  grep -qi 'push' $SC/out && P+="the output mentions push: $(grep -i push $SC/out | head -2 | tr '\n' '|')"
  verdict "CODEX AC2 preflight without a rules file: a FAIL for each of the two writer rules, never suggests git push"

  cxp codex-pf-broad; print -rl -- 'prefix_rule(pattern=["git"], decision="allow")' > $SC/codex-home/rules/default.rules; cxp_run
  grep '^WARN' $SC/out | grep -qi 'broader' || P+="no WARN saying the git rule is broader than needed: $(cxp_bad | tr '\n' '|')"
  [[ -z $(grep '^FAIL' $SC/out | grep -E 'prefix_rule|codex') ]] || P+="FAIL lines although a broad git rule covers them: $(grep '^FAIL' $SC/out | grep -E 'prefix_rule|codex' | tr '\n' '|')"
  verdict "CODEX AC2 preflight with a blanket git rule: counts as present, WARN that it's broader than needed"

  cxp codex-pf-longer; print -rl -- 'prefix_rule(pattern=["git", "add", "-A"], decision="allow")' $RULES_ALL[2] > $SC/codex-home/rules/default.rules; cxp_run
  [[ -n $(grep '^FAIL' $SC/out | grep -F -- 'prefix_rule(pattern=["git", "add"], decision="allow")') ]] || P+="a longer git add -A rule was taken to cover git add; FAIL lines: $(grep '^FAIL' $SC/out | head -3 | tr '\n' '|')"
  verdict "CODEX AC2 preflight: a longer rule (git add -A) doesn't cover git add"

  cxp codex-pf-alternatives; print -rl -- 'prefix_rule(pattern=["git", ["add", "commit"]], decision="allow")' > $SC/codex-home/rules/default.rules; cxp_run
  [[ -z $(cxp_bad) ]] || P+="FAIL/WARN with alternatives covering add and commit: $(cxp_bad | tr '\n' '|')"
  grep -q Traceback $SC/out $SC/err && P+="a traceback on an alternatives list"
  grep -qE '^OK +codex' $SC/out || P+="no OK line about codex besides the advisor one"
  verdict "CODEX AC2 preflight: a pattern element that lists alternatives covers each one, no crash"

  cxp codex-pf-two-files; print -rl -- $RULES_ALL[1] > $SC/codex-home/rules/default.rules; print -rl -- $RULES_ALL[2] > $SC/codex-home/rules/team.rules; cxp_run
  [[ -z $(cxp_bad) ]] || P+="FAIL/WARN although the rules are split over two files: $(cxp_bad | tr '\n' '|')"
  grep -qE '^OK +codex' $SC/out || P+="no OK line about codex besides the advisor one"
  verdict "CODEX AC2 preflight reads every *.rules file in the rules directory"

  cxp codex-pf-home; mkdir -p $SC/home/.codex/rules; print -rl -- $RULES_ALL > $SC/home/.codex/rules/default.rules
  BASE=( ${BASE:#CODEX_HOME=*} ); cxp_run
  [[ -z $(cxp_bad) ]] || P+="FAIL/WARN with the rules in \$HOME/.codex and no CODEX_HOME: $(cxp_bad | tr '\n' '|')"
  grep -qE '^OK +codex' $SC/out || P+="no OK line about codex besides the advisor one"
  verdict "CODEX AC2 preflight uses ~/.codex/rules when CODEX_HOME is unset"

  cxp codex-pf-comments; print -rl -- ${RULES_ALL/#/# } > $SC/codex-home/rules/default.rules; cxp_run
  [[ $RC == 1 ]] || P+="exit $RC (want 1)"
  for r in $RULES_ALL; do [[ -n $(grep '^FAIL' $SC/out | grep -F -- $r) ]] || P+="a commented-out rule counted: no FAIL naming $r"; done
  verdict "CODEX AC2 preflight: commented-out rules don't count"

  cxp codex-pf-decision-first; print -rl -- 'prefix_rule(decision="forbidden", pattern=["git", "add"])' $RULES_ALL[2] > $SC/codex-home/rules/default.rules; cxp_run
  [[ $RC == 1 && -n $(grep '^FAIL' $SC/out | grep -i forbid | grep 'git add') ]] || P+="a forbidden rule written decision-first counted as allow: exit $RC; $(grep -E '^(FAIL|WARN)' $SC/out | head -3 | tr '\n' '|')"
  verdict "CODEX AC2 preflight: a forbidden rule with decision= before pattern= is a FAIL"

  cxp codex-pf-forbid-broad; print -rl -- $RULES_ALL 'prefix_rule(pattern=["git"], decision="forbidden")' > $SC/codex-home/rules/default.rules; cxp_run
  [[ $RC == 1 && -n $(grep '^FAIL' $SC/out | grep -i forbid | grep 'git add') && -n $(grep '^FAIL' $SC/out | grep -i forbid | grep 'git commit') ]] || P+="a broader forbidden rule didn't beat the exact allow rules: exit $RC; $(grep -E '^(FAIL|WARN)' $SC/out | head -3 | tr '\n' '|')"
  verdict "CODEX AC2 preflight: a broader forbidden rule wins over an exact allow rule"

  cxp codex-pf-prompt; print -rl -- 'prefix_rule(pattern=["git", "add"], decision="prompt")' $RULES_ALL[2] > $SC/codex-home/rules/default.rules; cxp_run
  [[ $RC == 1 && -n $(grep '^FAIL' $SC/out | grep 'git add') ]] || P+="a prompt rule counted as present: exit $RC"
  verdict "CODEX AC2 preflight: a rule that prompts isn't an allow"

  cxp codex-pf-justification; print -rl -- 'prefix_rule(pattern=["git", "add"], decision="allow", justification="never prompt, a # here is no comment")' $RULES_ALL[2] > $SC/codex-home/rules/default.rules; cxp_run
  [[ -z $(cxp_bad) && $RC == 0 ]] || P+="an allow rule whose justification says 'prompt' was dropped: exit $RC; $(cxp_bad | tr '\n' '|')"
  verdict "CODEX AC2 preflight: an allow rule with 'prompt' in its justification still counts"

  hk_repo() { git -C $SC/repo config core.hooksPath $1; }
  cxp codex-pf-hooks-rel; print -rl -- $RULES_ALL > $SC/codex-home/rules/default.rules; hk_repo .githooks; cxp_run
  [[ $RC == 1 && -n $(grep '^FAIL' $SC/out | grep 'core.hooksPath' | grep 'relative' | grep 'unset' | grep '#66') ]] || P+="a relative core.hooksPath wasn't a FAIL naming the problem, the fix and #66: exit $RC; $(grep -E '^FAIL' $SC/out | head -3 | tr '\n' '|')"
  verdict "CODEX AC2 preflight: a relative core.hooksPath in the run's repo is a FAIL"

  cxp codex-pf-hooks-abs; print -rl -- $RULES_ALL > $SC/codex-home/rules/default.rules; hk_repo /opt/hooks; cxp_run
  [[ -z $(cxp_bad) && -z $(grep core.hooksPath $SC/out) ]] || P+="an absolute core.hooksPath was reported: $(grep -E '^(FAIL|WARN)' $SC/out | head -3 | tr '\n' '|')"
  verdict "CODEX AC2 preflight: an absolute core.hooksPath outside the worktrees is fine"

  cxp codex-pf-hooks-tilde; print -rl -- $RULES_ALL > $SC/codex-home/rules/default.rules; hk_repo '~/hooks'; cxp_run
  [[ -z $(cxp_bad) && -z $(grep core.hooksPath $SC/out) ]] || P+="~/hooks (absolute once git expands it) was reported: $(grep -E '^(FAIL|WARN)' $SC/out | head -3 | tr '\n' '|')"
  verdict "CODEX AC2 preflight: a ~/ core.hooksPath is absolute and passes"

  cxp codex-pf-hooks-inside; print -rl -- $RULES_ALL > $SC/codex-home/rules/default.rules; hk_repo $SC/worktrees/u1/.githooks; cxp_run
  [[ $RC == 1 && -n $(grep '^FAIL' $SC/out | grep 'core.hooksPath' | grep 'inside') ]] || P+="an absolute core.hooksPath inside the worktrees dir wasn't a FAIL: exit $RC; $(grep -E '^FAIL' $SC/out | head -3 | tr '\n' '|')"
  cxp codex-pf-hooks-main; print -rl -- $RULES_ALL > $SC/codex-home/rules/default.rules; hk_repo $SC/repo/.githooks; cxp_run
  [[ -z $(cxp_bad) && -z $(grep core.hooksPath $SC/out) ]] || P+="an absolute core.hooksPath in the main checkout (REPO) was reported: $(grep -E '^(FAIL|WARN)' $SC/out | head -3 | tr '\n' '|')"
  cxp codex-pf-hooks-wtsv; print -rl -- $RULES_ALL > $SC/codex-home/rules/default.rules; hk_repo $SC/elsewhere/u1/hooks; print -r -- "u1 - $SC/elsewhere/u1" > $D/worktrees.tsv; cxp_run
  [[ $RC == 1 && -n $(grep '^FAIL' $SC/out | grep 'core.hooksPath' | grep 'inside') ]] || P+="a hooksPath inside a worktree in worktrees.tsv wasn't a FAIL: exit $RC"
  verdict "CODEX AC2 preflight: an absolute core.hooksPath inside a worktree is a FAIL; one in the main checkout passes"

  cxp codex-pf-hooks-global; print -rl -- $RULES_ALL > $SC/codex-home/rules/default.rules; print -r -- $'[core]\n\thooksPath = rel-hooks' > $SC/gitconfig
  BASE=( ${BASE:#GIT_CONFIG_GLOBAL=*} GIT_CONFIG_GLOBAL=$SC/gitconfig ); cxp_run
  [[ $RC == 1 && -n $(grep '^FAIL' $SC/out | grep 'core.hooksPath' | grep "$SC/gitconfig") && -z $(grep '^FAIL' $SC/out | grep -- '--unset') ]] || P+="a global relative hooksPath: want a FAIL naming the origin and no --unset: exit $RC; $(grep -E '^FAIL' $SC/out | head -3 | tr '\n' '|')"
  verdict "CODEX AC2 preflight: a global core.hooksPath gets its origin in the fix, not --unset"

  cxp codex-pf-hooks-norepo; print -rl -- $RULES_ALL > $SC/codex-home/rules/default.rules; sed -i.bak -e '/^REPO=/d' -e '/^WORKTREE=/d' $D/team.env; cxp_run
  grep '^WARN' $SC/out | grep -q 'neither REPO nor WORKTREE' || P+="no WARN when team.env sets neither REPO nor WORKTREE: $(grep -E '^(FAIL|WARN)' $SC/out | head -3 | tr '\n' '|')"
  verdict "CODEX AC2 preflight: no REPO or WORKTREE gives a WARN, not a silent pass"

  cxp codex-pf-hooks-giterr; print -rl -- $RULES_ALL > $SC/codex-home/rules/default.rules; print -r -- $'[core' > $SC/repo/.git/config; cxp_run
  grep '^WARN' $SC/out | grep -q 'core.hooksPath wasn.t checked' || P+="no WARN when git config fails: $(grep -E '^(FAIL|WARN)' $SC/out | head -3 | tr '\n' '|')"
  verdict "CODEX AC2 preflight: a git config error gives a WARN, not a silent pass"

  cxp codex-pf-nocodex; print -rl -- $RULES_ALL > $SC/codex-home/rules/default.rules; cxp_run PATH=/usr/bin:/bin:/usr/sbin:/sbin
  [[ $RC == 1 ]] || P+="exit $RC (want 1)"
  grep '^FAIL' $SC/out | grep -qi codex || P+="no FAIL line naming codex: $(grep '^FAIL' $SC/out | head -3 | tr '\n' '|')"
  verdict "CODEX AC2 preflight with codex not on PATH: FAIL"
}

# ---- effort plumbing in the shared launch-teammate.sh ---------------------------------------------------------------------
# A scratch driver `other` logs what launch is called with. The variable's name, TEAMMATE_EFFORT, is pinned here.
want codex-effort && {
  cp -R $SKILLS $SB/src-effort; mkdir -p $SB/src-effort/agent-teammates/scripts/drivers/other
  : > $SB/src-effort/agent-teammates/scripts/drivers/other/driver.env
  printf '#!/bin/sh\nprintf "argc=%%s effort=[%%s]\\n" "$#" "${TEAMMATE_EFFORT-UNSET}" >> "$EFFORT_LOG"\necho "id9 -"\n' > $SB/src-effort/agent-teammates/scripts/drivers/other/launch
  chmod +x $SB/src-effort/agent-teammates/scripts/drivers/other/launch
  EFFN=0
  eff() {  # eff <check name> <want effort> <xrun env...> -- <team.env line...> -- <launch-teammate args...>
    local nm=$1 want=$2; shift 2
    local ev=() tl=() la=()
    while [[ $1 != -- ]]; do ev+=$1; shift; done; shift
    while [[ $1 != -- ]]; do tl+=$1; shift; done; shift
    la=("$@")
    TREE=$SB/src-effort; mk codex-effort-$((++EFFN)) HARNESS=other MODEL_REVIEWER=m1 MODEL_TEST_WRITER=m2 "${tl[@]}"; TREE=$SKILLS
    la=( ${la//@D@/$D} ); la=( ${la//@WT@/$SC/wt} )
    : > $SC/effort.log
    xrun EFFORT_LOG=$SC/effort.log "${ev[@]}" $SB/src-effort/agent-teammates/scripts/launch-teammate.sh "${la[@]}"
    [[ $RC == 0 ]] || P+="launch-teammate.sh exit $RC: $(head -c 200 $SC/out | tr '\n' '|')"
    [[ $(<$SC/effort.log) == "argc=6 effort=[$want]" ]] || P+="the driver's launch got '$(<$SC/effort.log)' (want 'argc=6 effort=[$want]')"
    verdict "CODEX effort: $nm"
  }
  eff "--role reviewer with EFFORT_REVIEWER=high hands TEAMMATE_EFFORT=high to launch" high -- EFFORT_REVIEWER=high -- --role reviewer @D@ t1 @WT@
  eff "the role name maps like MODEL_<ROLE> (test-writer -> EFFORT_TEST_WRITER)" medium -- EFFORT_TEST_WRITER=medium -- --role test-writer @D@ t1 @WT@
  eff "a role with no EFFORT_<ROLE> sets TEAMMATE_EFFORT empty, not unset" '' -- -- --role reviewer @D@ t1 @WT@
  eff "a launch without --role sets it empty whatever the caller's environment holds" '' TEAMMATE_EFFORT=leak -- -- @D@ t1 @WT@
  eff "a role with no EFFORT_<ROLE> doesn't pick up the caller's value" '' TEAMMATE_EFFORT=leak -- -- --role reviewer @D@ t1 @WT@
  eff "a value with a space reaches launch intact" 'very high' -- "EFFORT_REVIEWER='very high'" -- --role reviewer @D@ t1 @WT@
}

# ---- the shape of the Codex driver ------------------------------------------------------------------------------------------
CDRV=$ROOT/skills/engineering/agent-teammates/scripts/drivers/codex
want codex-shape && {
  missing=(); for op in launch send status tail stop preflight; do [[ -x $CDRV/$op ]] || missing+=$op; done
  (( $#missing )) && fail "CODEX D2 driver executables" "missing or not executable in ${CDRV#$ROOT/}: ${missing[*]}" || pass "CODEX D2 driver executables"
  [[ ! -e $CDRV/advisor-probe ]] && pass "CODEX D2 no advisor-probe" || fail "CODEX D2 no advisor-probe" "${CDRV#$ROOT/}/advisor-probe exists; Codex has no advisor"
  if [[ -f $CDRV/driver.env ]] && grep -q '^LIVE_MESSAGING=0$' $CDRV/driver.env && grep -q '^SEND=script$' $CDRV/driver.env; then pass "CODEX D2 driver.env declares LIVE_MESSAGING=0 and SEND=script"
  else fail "CODEX D2 driver.env declares LIVE_MESSAGING=0 and SEND=script" "${CDRV#$ROOT/}/driver.env: $([[ -f $CDRV/driver.env ]] && echo "lacks LIVE_MESSAGING=0 or SEND=script" || echo missing)"; fi
  bad=(); for op in launch send status tail stop preflight; do [[ -f $CDRV/$op ]] && [[ $(sed -n 2p $CDRV/$op) == "# usage: $op "* ]] || bad+=$op; done
  (( $#bad )) && fail "CODEX D2 operations have a 'usage:' line 2" "line 2 isn't '# usage: <op> ...' in: ${bad[*]}" || pass "CODEX D2 operations have a 'usage:' line 2"
  bad=()
  sc codex-shape-arity
  for op in launch send status tail stop preflight; do
    [[ -x $CDRV/$op ]] || { bad+="$op (missing)"; continue; }
    xrun $CDRV/$op; [[ $RC == 5 && $(cat $SC/out $SC/err) == *usage:* ]] || bad+="$op with no arguments: exit $RC"
    xrun $CDRV/$op a b c d e f g; [[ $RC == 5 ]] || bad+="$op with seven arguments: exit $RC"
  done
  (( $#bad )) && fail "CODEX D2 wrong arity exits 5 with the usage line" "${(j:; :)bad}" || pass "CODEX D2 wrong arity exits 5 with the usage line"
  grep -rEn 'dangerously-bypass|danger-full-access' $CDRV >/dev/null 2>&1 && fail "CODEX D2 the driver never names a bypass or danger-full-access" "$(grep -rEn 'dangerously-bypass|danger-full-access' $CDRV | head -3)" || pass "CODEX D2 the driver never names a bypass or danger-full-access"
  grep -qE '^Optional input:.*TEAMMATE_EFFORT' ${DRV:h}/CONTRACT.md && pass "CODEX D2 CONTRACT.md documents TEAMMATE_EFFORT as an optional input" || fail "CODEX D2 CONTRACT.md documents TEAMMATE_EFFORT as an optional input" "no 'Optional input:' paragraph in ${DRV:h}/CONTRACT.md mentions TEAMMATE_EFFORT"
}

# ======================================================================================================================
# U4: the driver and script cleanup (#63). Tail output per the driver contract (the last n TOOL lines, then the latest
# SAID), a malformed events line, codex's missing CLI, copilot's effort validation, a codex .state without PERM, and
# REPO as the one name for the checkout (WORKTREE only as a fallback). Checks marked "guard" pass before the change
# and pin behaviour that must survive it. The claude tail goldens (tail-*) and init goldens (init-*) were edited by
# hand to the new output; `--record` would revert them.
# ======================================================================================================================
# Copilot tail: no fake copilot run, only the events.jsonl a session leaves. cptail_fix <scenario> [bad]: w1 registered,
# the file written (with a malformed line between the second and third tool calls when [bad] is given), mtime 7 min old.
CPTID=5c1f0a2e-0000-4000-8000-000000000001
cptail_fix() {
  cpmk $1; reg w1 $CPTID 1789999000 - $SC/wt
  local sd=$SC/home/.copilot/session-state/$CPTID; mkdir -p $sd
  {
    echo '{"type":"session.start","data":{"sessionId":"x"},"id":"1","parentId":null,"timestamp":"t"}'
    echo '{"type":"assistant.message","data":{"content":"Early note","toolRequests":[]},"id":"2","parentId":null,"timestamp":"t"}'
    echo '{"type":"tool.execution_start","data":{"toolCallId":"a","toolName":"bash","arguments":{"command":"ls","description":"Run ls"}},"id":"3","parentId":null,"timestamp":"t"}'
    echo '{"type":"tool.execution_complete","data":{"toolCallId":"a","success":true},"id":"4","parentId":null,"timestamp":"t"}'
    echo '{"type":"tool.execution_start","data":{"toolCallId":"b","toolName":"bash","arguments":{"command":"git diff"}},"id":"5","parentId":null,"timestamp":"t"}'
    [[ -n $2 ]] && echo '{"type":"tool.execution_start","data":{"toolCallId":"x","toolName":"bash","argum'
    echo '{"type":"tool.execution_start","data":{"toolCallId":"c","toolName":"view","arguments":{"path":"/x/c.md"}},"id":"6","parentId":null,"timestamp":"t"}'
    echo '{"type":"assistant.message","data":{"content":"","toolRequests":[{"toolCallId":"d","name":"bash"}]},"id":"7","parentId":null,"timestamp":"t"}'
    echo '{"type":"tool.execution_start","data":{"toolCallId":"d","toolName":"bash","arguments":{"command":"git status"}},"id":"8","parentId":null,"timestamp":"t"}'
    echo '{"type":"assistant.message","data":{"content":"Final word","toolRequests":[]},"id":"9","parentId":null,"timestamp":"t"}'
  } > $sd/events.jsonl
  settime $((NOW - 420)) $sd/events.jsonl
}
cptail_is() {  # cptail_is <line>...: stdout is the transcript line, then exactly these lines
  [[ $RC == 0 ]] || P+="exit $RC, want 0 (stderr: $(head -c 200 $SC/err | tr '\n' '|'))"
  [[ $(head -1 $SC/out) == "transcript: "* ]] || P+="first line isn't 'transcript: ...': $(head -1 $SC/out)"
  [[ "$(tail -n +2 $SC/out)" == "${(F)@}" ]] || P+="lines after the transcript line: $(tail -n +2 $SC/out | tr '\n' '|'); want ${(j:|:)@}"
}
cpwant cp-u4-tail && {
  cptail_fix cp-u4-tail
  xrun $AT/teammate-tail.sh $D w1
  cptail_is "TOOL  bash: Run ls" "TOOL  bash: git diff" "TOOL  view: /x/c.md" "TOOL  bash: git status" "SAID  Final word"
  verdict "U4 copilot tail: every TOOL line, then the latest SAID only (not an earlier message)"
  xrun $AT/teammate-tail.sh $D w1 2
  cptail_is "TOOL  view: /x/c.md" "TOOL  bash: git status" "SAID  Final word"
  verdict "U4 copilot tail n=2: the last 2 TOOL lines, then the latest SAID"
}
cpwant cp-u4-tail-bad && {
  cptail_fix cp-u4-tail-bad bad
  xrun $AT/teammate-tail.sh $D w1
  cptail_is "TOOL  bash: Run ls" "TOOL  bash: git diff" "TOOL  view: /x/c.md" "TOOL  bash: git status" "SAID  Final word"
  verdict "U4 copilot tail: a malformed JSON line mid-file is skipped, the lines after it still show"
}

# Codex without the CLI: PATH holds the fakes except codex.
mk_nocx() {
  local f; mkdir -p $SC/nocx
  for f in $SB/bin/*(N); do [[ ${f:t} == codex ]] || ln -sf $f $SC/nocx/${f:t}; done
  NOCX=$SC/nocx:/usr/bin:/bin:/usr/sbin:/sbin
  [[ -z $(env -i PATH=$NOCX /bin/sh -c 'command -v codex') ]] || P+="sanity: codex still resolves on the no-codex PATH"
}
want codex-u4-nocodex && {
  cx_sc codex-u4-launch-nocodex; mk_nocx
  xrunb 20 PATH=$NOCX $AT/launch-teammate.sh --role implementer $D t1 $SC/wt
  [[ $RC == 1 ]] || P+="launch exit $RC (want 1)"
  out_has "codex is not on PATH"
  left=($D/codex-*(N)); (( $#left )) && P+="launch left files behind: ${(j: :)left:t}"
  [[ -s $D/teammates.tsv ]] && P+="registry has a row: $(tr '\n' '|' < $D/teammates.tsv)"
  verdict "U4 codex launch without codex on PATH: exit 1, 'codex is not on PATH', no files, no registry row"

  cx_sc codex-u4-send-nocodex; mk_nocx
  cx_launch ok --role implementer $D t1 $SC/wt
  cx_ok "launch" && {
    cx_wait 10 'cx_over $THR' || P+="the turn never reported done (status: '$(cx_state $THR)')"
    print -r -- "second job" > $SC/msg.md; cp $D/teammates.tsv $SC/tsv.before
    xrunb 20 PATH=$NOCX $AT/retask.sh $D t1 $SC/msg.md
    [[ $RC == 1 ]] || P+="retask exit $RC (want 1)"
    out_has "codex is not on PATH"; tsv_same
  }
  verdict "U4 codex send without codex on PATH: exit 1, 'codex is not on PATH', registry untouched"
}

# Claude without the CLI: PATH holds the fakes except claude. Launch says so before it lists live sessions.
mk_nocl() {
  local f; mkdir -p $SC/nocl
  for f in $SB/bin/*(N); do [[ ${f:t} == claude ]] || ln -sf $f $SC/nocl/${f:t}; done
  NOCL=$SC/nocl:/usr/bin:/bin:/usr/sbin:/sbin
  [[ -z $(env -i PATH=$NOCL /bin/sh -c 'command -v claude') ]] || P+="sanity: claude still resolves on the no-claude PATH"
}
want u5-claude-noclaude && {
  mk u5-claude-noclaude; mk_nocl
  xrun PATH=$NOCL $AT/launch-teammate.sh $D t1 $SC/wt
  [[ $RC == 1 ]] || P+="launch exit $RC (want 1)"
  out_has "claude is not on PATH"
  [[ "$(cat $SC/out $SC/err)" == *"couldn't list live sessions"* ]] && P+="launch blames the session list, not the missing CLI"
  [[ -s $D/teammates.tsv ]] && P+="registry has a row: $(tr '\n' '|' < $D/teammates.tsv)"
  verdict "U5 claude launch without claude on PATH: exit 1, 'claude is not on PATH', no session-list message, no registry row"
}

# Codex state: no PERM. The first check reads the driver's own state file (white-box; the CODEX section is otherwise
# black-box). The second is a guard: an old state file that still has a PERM= line loads in status, send and tail.
want codex-u4-state && {
  cx_sc codex-u4-state
  cx_launch ok --role implementer $D t1 $SC/wt
  cx_ok "launch" && {
    cx_wait 10 'cx_over $THR' || P+="the turn never reported done (status: '$(cx_state $THR)')"
    st=$D/codex-$THR.state
    [[ -f $st ]] || P+="no state file $st"
    grep -q '^PERM=' $st 2>/dev/null && P+="the state file has a PERM= line: $(grep '^PERM=' $st)"
  }
  verdict "U4 codex launch writes no PERM line to its .state (white-box)"

  print -r -- "PERM=auto" >> $D/codex-$THR.state
  [[ $(cx_state $THR) == done ]] || P+="status with a stale PERM= line says '$(cx_state $THR)' (want done)"
  xrun $AT/teammate-tail.sh $D t1
  [[ $RC == 0 ]] || P+="tail exit $RC"
  print -r -- "next" > $SC/msg.md
  xrunb 20 FAKE_CODEX_MODE=ok $AT/retask.sh $D t1 $SC/msg.md
  cx_ok "retask with a stale PERM= line" && { cx_resumed || P+="no resume call after retask"; }
  verdict "U4 guard: a codex .state with a stale PERM= line still loads (status, tail, send)"
}

# Copilot effort shape: an effort with a character outside [A-Za-z0-9._-], or one that starts with a dash, exits 5 from
# launch before any state file, registry row or copilot call exists. The message points at `copilot --help` for the
# values (the brief's wording). A well-formed effort is passed through whatever it says (cp-u5-effort-pass).
want_nl() { (source $D/team.env >/dev/null 2>&1; [[ $EFFORT_IMPLEMENTER == *$'\n'* ]]); }
typeset -a BADEFF; BADEFF=(
  "newline-between|EFFORT_IMPLEMENTER=\$'high\nlow'|nl" "newline-trailing|EFFORT_IMPLEMENTER=\$'high\n'|nl"
  "space|EFFORT_IMPLEMENTER='very high'|" "dash-x|EFFORT_IMPLEMENTER=-x|" "dash-version|EFFORT_IMPLEMENTER=--version|"
  "dollar|EFFORT_IMPLEMENTER='\$(touch effort-pwned-ns)'|" )
cpwant cp-u4-effort-invalid && {
  for spec in $BADEFF; do
    parts=("${(@s:|:)spec}")
    cpmk cp-u4-effort-$parts[1] "$parts[2]"
    P=()
    [[ $parts[3] == nl ]] && { want_nl || P+="sanity: team.env's effort has no newline"; }
    txrun $AT/launch-teammate.sh --role implementer $D w1 $SC/wt; cpnote "launch w1"
    /bin/sleep 0.3
    [[ $RC == 5 ]] || P+="exit $RC, want 5"
    msg=$(cat $SC/out $SC/err); [[ ${msg//$SB/} == *[Ee]ffort* ]] || P+="no message naming the effort: $(print -r -- $msg | head -c 200 | tr '\n' '|')"
    st=($D/copilot-*(N)); (( $#st )) && P+="state file written: ${(j: :)st:t}"
    cl=($SC/fake/copilot.call.*(N)); (( $#cl )) && P+="copilot was called ${#cl} time(s)"
    [[ -s $D/teammates.tsv ]] && P+="registry has a row"
    out_has "copilot --help"
    hit=$(find $SB $PWD -name effort-pwned-ns 2>/dev/null)
    [[ -n $hit ]] && P+="the effort was evaluated: ${hit//$'\n'/ } exists"
    reap_fakes
    cpverdict "U4 copilot launch refuses effort '$parts[1]' with exit 5, before any state file or run, and points at copilot --help"
  done
}
cpwant cp-u4-effort-valid && {
  P=()
  for v in none minimal low medium high xhigh max ''; do
    cpmk cp-u4-effort-ok-${v:-empty} "EFFORT_IMPLEMENTER=$v"
    txrun $AT/launch-teammate.sh --role implementer $D w1 $SC/wt; cpnote "launch ${v:-empty}"
    await 10 cp_settled 1
    [[ $RC == 0 ]] || P+="'$v': exit $RC, want 0"
    cp_load; got=absent; (( $#RUNS )) && { cparse $RUNS[1]; got=${F[--reasoning-effort]-absent}; }
    [[ $got == ${v:-absent} ]] || P+="'$v': --reasoning-effort is '$got', want '${v:-absent}'"
    reap_fakes
  done
  cpverdict "U4 guard: the efforts copilot 1.0.95 lists (none to max), and the empty effort, still launch with that effort"
}
# A well-formed effort goes to copilot as one --reasoning-effort argument whatever it says; the CLI validates it. The
# last value uses every allowed punctuation character away from the front.
cpwant cp-u5-effort-pass && {
  P=()
  for v in HIGH ultra bogus x-high.2_b; do
    cpmk cp-u5-effort-pass-$v "EFFORT_IMPLEMENTER=$v"
    txrun $AT/launch-teammate.sh --role implementer $D w1 $SC/wt; cpnote "launch $v"
    await 10 cp_settled 1
    [[ $RC == 0 ]] || P+="'$v': exit $RC, want 0"
    cp_load; got=absent; (( $#RUNS )) && { cparse $RUNS[1]; got=${F[--reasoning-effort]-absent}; }
    [[ $got == $v ]] || P+="'$v': --reasoning-effort is '$got', want '$v'"
    reap_fakes
  done
  cpverdict "U5 copilot launch passes a well-formed effort (HIGH, ultra, bogus, x-high.2_b) to copilot as --reasoning-effort <value>"
}
# When copilot itself rejects the value it exits at once; launch reports that as exit 1, not as a shape refusal.
cpwant cp-u5-effort-copilot-rejects && {
  cpmk cp-u5-effort-copilot-rejects EFFORT_IMPLEMENTER=ultra
  txrun FAKE_COPILOT_MODE=fail $AT/launch-teammate.sh --role implementer $D w1 $SC/wt; cpnote "launch ultra"
  P=()
  [[ $RC == 1 ]] || P+="exit $RC, want 1"
  out_has "copilot exited at once with 1"
  reap_fakes
  cpverdict "U5 copilot launch: a well-formed effort that copilot exits on at once gives exit 1 'copilot exited at once with 1'"
  P=()   # cpverdict keeps P, and the next scenario's verdict would report it
}

# REPO, with WORKTREE only a fallback. team-init writes REPO alone; watch-ci.sh reads either.
want u4-init && {
  sc u4-init; xrun CLAUDECODE=1 $CM/team-init.sh run1 $SC/repo
  grep -q '^REPO=' $SC/teams/run1/team.env 2>/dev/null || P+="team.env has no REPO= line (exit $RC)"
  grep -q '^WORKTREE=' $SC/teams/run1/team.env 2>/dev/null && P+="team.env still has a WORKTREE= line"
  verdict "U4 team-init writes REPO and no WORKTREE= line"
}
u4_ci() {  # u4_ci <scenario> <sed-expression|->: a repo with a commit on branch feat, a stub gh, and the team.env edited by the expression
  mk $1; mk_repo
  local g=(env -i PATH=/usr/bin:/bin HOME=$SC/home GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 git -C $SC/repo -c user.name=t -c user.email=t@example.com)
  $g commit -q --allow-empty -m one; $g branch -M feat
  SHA=$($g rev-parse feat)
  mkdir -p $SC/ghbin
  printf '%s\n' '#!/bin/sh' 'echo "$*" >> "$FAKE_DIR/gh.log"' 'case "$1 $2" in' '  "run list") echo 4242 ;;' '  "run watch") exit 0 ;;' \
    '  "run view") echo "success | build: success" ;;' 'esac' > $SC/ghbin/gh
  chmod +x $SC/ghbin/gh
  sed -i.bak $2 $D/team.env; rm -f $D/team.env.bak
}
u4_ci_check() {
  [[ $RC == 0 ]] || P+="exit $RC, want 0; out: $(head -c 200 $SC/out | tr '\n' '|')"
  [[ $(<$SC/out) == "success | build: success" ]] || P+="stdout: $(head -c 200 $SC/out | tr '\n' '|')"
  grep -qF ".headSha==\"$SHA\"" $SC/fake/gh.log 2>/dev/null || P+="gh was not asked for the head sha $SHA of feat: $(head -c 200 $SC/fake/gh.log 2>/dev/null | tr '\n' '|')"
}
want u4-watch-ci && {
  u4_ci u4-watch-ci-repo '/^WORKTREE=/d'
  grep -q '^REPO=' $D/team.env && ! grep -q '^WORKTREE=' $D/team.env || P+="fixture: want a team.env with REPO only"
  xrun PATH=$SC/ghbin:$SANDBOX_PATH $CM/watch-ci.sh $D feat ci.yml; u4_ci_check
  verdict "U4 watch-ci.sh works from a team.env that has REPO and no WORKTREE"
  u4_ci u4-watch-ci-worktree '/^REPO=/d'
  grep -q '^WORKTREE=' $D/team.env && ! grep -q '^REPO=' $D/team.env || P+="fixture: want a team.env with WORKTREE only"
  xrun PATH=$SC/ghbin:$SANDBOX_PATH $CM/watch-ci.sh $D feat ci.yml; u4_ci_check
  verdict "U4 guard: watch-ci.sh still works from an old team.env that has WORKTREE and no REPO"
}

# ======================================================================================================================
# ROLES: role-skills.sh resolves a run's role skills from the override layers (issue #71, ADR 0004): built-in (empty),
# user-global $XDG_CONFIG_HOME/commodore/roles.json, repo .commodore/roles.json, then the run's own roles.json.
# Assertion style: each check compares whole table rows with literals. `tests/run.sh roles` runs just these.
# ======================================================================================================================
rk_sc() {  # rk_sc <scenario> [harness]: a run with its own XDG config, harness homes and repo, and no override files
  HL=HARNESS=${2:-claude}; mk $1; HL=
  mkdir -p $SC/xdg $SC/codex-home $SC/copilot-home
  BASE+=( XDG_CONFIG_HOME=$SC/xdg CODEX_HOME=$SC/codex-home COPILOT_HOME=$SC/copilot-home )
}
rk_user() { mkdir -p $SC/xdg/commodore; print -r -- "$1" > $SC/xdg/commodore/roles.json; }
rk_repo() { mkdir -p $SC/repo/.commodore; print -r -- "$1" > $SC/repo/.commodore/roles.json; }
rk_run()  { print -r -- "$1" > $D/roles.json; }
rk_skill() { mkdir -p $1/$2; print -r -- "---\nname: $2\ndescription: test skill\n---" > $1/$2/SKILL.md; }  # rk_skill <skills-dir> <name>
rk() { xrun $CM/role-skills.sh $D; }
row_is() {  # row_is <role> <expected row>: the table has exactly this row for the role
  local got; got=$(grep -E "^[|] $1 [|]" $SC/out)
  [[ $got == "$2" ]] || P+="row for $1: got '${got:-(none)}', want '$2'"
}
rc_is() { [[ $RC == $1 ]] || P+="exit $RC, want $1; stderr: $(head -c 300 $SC/err | tr '\n' '|')"; }
err_has() { grep -qF -- "$1" $SC/err || P+="stderr lacks '$1': $(head -c 300 $SC/err | tr '\n' '|')"; }
want roles && {
  rk_sc roles-none; rk
  rc_is 0
  [[ $(sed -n 1,2p $SC/out) == $'| Role | Skills | Instructions | Source |\n| --- | --- | --- | --- |' ]] || P+="header: $(sed -n 1,2p $SC/out | tr '\n' '|')"
  row_is implementer '| implementer | none (fallback procedure) | - | built-in |'
  row_is scribe '| scribe | none (fallback procedure) | - | built-in |'
  row_is security-reviewer '| security-reviewer | none: not launched | - | built-in |'
  (( $(grep -c '^| [a-z]' $SC/out) == 8 )) || P+="want 8 role rows, got $(grep -c '^| [a-z]' $SC/out) lines"
  err_has 'WARN  security-reviewer has no role skill: no security review this run'
  verdict "ROLES no override files: every role has no skills, and the security reviewer isn't launched"

  rk_sc roles-order; for n in tdd repo-tdd pr unslop code-review; do rk_skill $SC/cfg/skills $n; done
  rk_user '{"implementer": {"skills": ["tdd"], "instructions": "user note"}, "scribe": {"skills": ["pr", "unslop"], "instructions": "Draft with pr, then run unslop."}, "reviewer": {"skills": ["code-review"]}}'
  rk; rc_is 0
  row_is scribe '| scribe | `/pr`, `/unslop` | Draft with pr, then run unslop. | user |'
  row_is reviewer '| reviewer | `/code-review` | - | user |'
  verdict "ROLES user-global layer: skills keep their order, with instructions and source"

  rk_repo '{"implementer": {"skills": ["repo-tdd"]}, "reviewer": {"skills": []}}'
  rk_run '{"scribe": {"skills": ["pr"]}}'
  rk; rc_is 0
  row_is implementer '| implementer | `/repo-tdd` | - | repo |'
  row_is reviewer '| reviewer | none (fallback procedure) | - | repo |'
  row_is scribe '| scribe | `/pr` | - | run |'
  row_is test-writer '| test-writer | none (fallback procedure) | - | built-in |'
  verdict "ROLES repo beats user and run beats repo, each replacing the whole role entry; [] clears"

  rk_sc roles-tolerant; for n in tdd pr unslop; do rk_skill $SC/cfg/skills $n; done
  rk_repo '{"implementer": {"skills": "/tdd"}, "scribe": {"skills": ["/pr", "$unslop"], "instructions": "a | b\nc"}}'
  rk; rc_is 0
  row_is implementer '| implementer | `/tdd` | - | repo |'
  row_is scribe '| scribe | `/pr`, `/unslop` | a \| b<br>c | repo |'
  [[ -s $SC/err ]] && grep -v 'security-reviewer has no role skill' $SC/err | grep -q . && P+="unexpected warnings: $(head -c 300 $SC/err | tr '\n' '|')"
  verdict "ROLES a string counts as one skill, a leading / or \$ is stripped quietly, and instructions fit a table cell"

  rk_sc roles-unknown; rk_skill $SC/cfg/skills tdd
  rk_repo '{"writer": {"skills": ["pr"]}, "implementer": {"skills": ["tdd", 42, "bad name"], "agent": "x"}, "reviewer": "code-review"}'
  rk; rc_is 0
  row_is implementer '| implementer | `/tdd` | - | repo |'
  row_is reviewer '| reviewer | none (fallback procedure) | - | built-in |'
  grep -q '^| writer ' $SC/out && P+="the unknown role reached the table"
  err_has "$SC/repo/.commodore/roles.json: unknown role \"writer\" skipped"
  err_has 'implementer: unknown field "agent" skipped'
  err_has 'implementer: skill 42 is not a skill name; dropped'
  err_has 'implementer: skill "bad name" is not a skill name; dropped'
  err_has 'reviewer: its entry is not an object; skipped'
  verdict "ROLES unknown roles, fields and bad names are warned about and skipped, and the rest resolves"

  rk_sc roles-badjson; rk_user '{"implementer": {"skills": ["tdd"]}}'; rk_repo '{"implementer": '
  rk; rc_is 1
  out_has "$SC/repo/.commodore/roles.json"
  grep -q '^| ' $SC/out && P+="printed a table despite the invalid file"
  verdict "ROLES invalid JSON stops resolution, naming the file"

  rk_sc roles-notobject; rk_run '["implementer"]'
  rk; rc_is 1
  out_has "$D/roles.json"
  verdict "ROLES a layer that isn't a JSON object stops resolution, naming the file"

  rk_sc roles-empty; print -r -- "  " > $SC/xdg/roles.tmp; mkdir -p $SC/xdg/commodore; mv $SC/xdg/roles.tmp $SC/xdg/commodore/roles.json
  rk; rc_is 1
  err_has "$SC/xdg/commodore/roles.json isn't a valid override file"
  verdict "ROLES an empty override file stops resolution, naming the file"

  # Availability: each harness's driver answers `has-skill`; a skill it can't find is dropped with a warning.
  rk_sc roles-claude-avail
  rk_skill $SC/cfg/skills tdd; rk_skill $SC/repo/.claude/skills repo-review; rk_skill $SC/cfg/plugins/cache/mkt/mp/1.0/skills/eng pr
  rk_skill $SC/cfg/plugins/cache/mkt/mp/0.9/skills/eng gone   # a stale cached version installed_plugins.json doesn't list
  print -r -- '{"version": 2, "plugins": {"mp@mkt": [{"scope": "user", "installPath": "'$SC'/cfg/plugins/cache/mkt/mp/1.0"}]}}' > $SC/cfg/plugins/installed_plugins.json
  rk_repo '{"implementer": {"skills": ["tdd", "nope"]}, "reviewer": {"skills": ["repo-review"]}, "security-reviewer": {"skills": ["security-review"]}, "scribe": {"skills": ["mp:pr", "mp:gone"]}, "triager": {"skills": ["missing"]}}'
  rk; rc_is 0
  row_is implementer '| implementer | `/tdd` | - | repo |'
  row_is reviewer '| reviewer | `/repo-review` | - | repo |'
  row_is security-reviewer '| security-reviewer | `/security-review` | - | repo |'
  row_is scribe '| scribe | `/mp:pr` | - | repo |'
  row_is triager '| triager | none (fallback procedure) | - | repo |'
  err_has 'implementer: skill /nope is not available on claude; dropped'
  err_has 'scribe: skill /mp:gone is not available on claude; dropped'
  err_has 'triager: skill /missing is not available on claude; dropped'
  grep -q 'no security review' $SC/err && P+="warned about the security reviewer, which has a built-in skill"
  verdict "ROLES claude: user, repo, plugin and built-in skills are available; others are dropped, keeping the rest"

  rk_sc roles-codex-avail codex
  rk_skill $SC/codex-home/skills/.system review-agent; rk_skill $SC/home/.agents/skills tdd; rk_skill $SC/repo/.agents/skills pr
  rk_user '{"implementer": {"skills": ["/tdd"]}, "reviewer": {"skills": ["review-agent"]}, "scribe": {"skills": ["pr"]}, "security-reviewer": {"skills": ["security-review"]}}'
  rk; rc_is 0
  row_is implementer '| implementer | `$tdd` | - | user |'
  row_is reviewer '| reviewer | `$review-agent` | - | user |'
  row_is scribe '| scribe | `$pr` | - | user |'
  row_is security-reviewer '| security-reviewer | none: not launched | - | user |'
  err_has 'security-reviewer: skill $security-review is not available on codex; dropped'
  err_has 'security-reviewer has no role skill: no security review this run'
  verdict "ROLES codex: \$ prefix, CODEX_HOME, ~/.agents and repo skills; a security reviewer whose skills all drop isn't launched"

  rk_sc roles-copilot-avail copilot
  rk_skill $SC/copilot-home/skills tdd; rk_skill $SC/repo/.github/skills pr
  mkdir -p $SC/copilot-home/pkg/darwin-arm64/{1.0.96,1.0.9}/definitions; : > $SC/copilot-home/pkg/darwin-arm64/1.0.96/definitions/security-review.agent.yaml
  : > $SC/copilot-home/pkg/darwin-arm64/1.0.9/definitions/code-review.agent.yaml   # only in an older CLI version
  rk_run '{"implementer": {"skills": ["tdd"]}, "scribe": {"skills": ["pr"]}, "security-reviewer": {"skills": ["security-review"]}, "reviewer": {"skills": ["code-review"]}}'
  rk; rc_is 0
  row_is implementer '| implementer | `/tdd` | - | run |'
  row_is scribe '| scribe | `/pr` | - | run |'
  row_is security-reviewer '| security-reviewer | `/security-review` | - | run |'
  row_is reviewer '| reviewer | none (fallback procedure) | - | run |'
  err_has 'reviewer: skill /code-review is not available on copilot; dropped'
  verdict "ROLES copilot: COPILOT_HOME, repo and built-in agent skills are available; others are dropped"

  rk_sc roles-nocheck; [[ -d $RT ]] || cp -R $SKILLS $RT; rdrv ok 'LIVE_MESSAGING=0' 'SEND=script'
  print -r -- "HARNESS=other" >> $D/team.env
  rk_repo '{"implementer": {"skills": ["tdd"]}}'
  xrun $RT/commodore/scripts/role-skills.sh $D; rc_is 0
  row_is implementer '| implementer | `/tdd` | - | repo |'
  err_has "can't check which skills are installed on other"
  verdict "ROLES a driver without has-skill keeps every named skill and says it couldn't check"

  # Preflight passes the resolver's warnings through, and fails on an override file it can't read.
  pf_sc roles-preflight; rk_repo '{"implementer": {"skills": ["nope"]}}'
  xrun CLAUDECODE=1 $CM/team-preflight.sh $D; rc_is 0
  out_has 'WARN  implementer: skill /nope is not available on claude; dropped'
  out_has 'WARN  security-reviewer has no role skill: no security review this run'
  [[ -e $D/teammates.tsv || -d $D/reports ]] && P+="checking skills wrote to the run directory"
  verdict "ROLES team-preflight warns about each dropped skill and a security reviewer without one"

  pf_sc roles-preflight-bad; rk_repo '{"implementer": '
  xrun CLAUDECODE=1 $CM/team-preflight.sh $D; rc_is 1
  grep -q "^FAIL  role skills: .*$SC/repo/.commodore/roles.json" $SC/out || P+="no FAIL line naming the file: $(grep role $SC/out | head -3 | tr '\n' '|')"
  verdict "ROLES team-preflight fails on an override file that isn't valid JSON"
}

# ======================================================================================================================
# SETUP: each driver's list-skills names the skills its has-skill accepts (issue #83), and setup-commodore's
# roles-draft.sh drafts, checks and saves a role-override file. Assertion style. `tests/run.sh setup` runs just these.
# ======================================================================================================================
DRVS=$SKILLS/agent-teammates/scripts/drivers
ls_is() {  # ls_is <harness> <expected output>: list-skills prints exactly this, and has-skill accepts every name in it
  xrun $DRVS/$1/list-skills $D; rc_is 0
  local got n; got=$(norm < $SC/out)
  [[ $got == "$2" ]] || P+="list-skills printed:"$'\n'"$got"$'\n'"want:"$'\n'"$2"
  for n in ${(f)"$(cut -f1 $SC/out)"}; do env -i $BASE $DRVS/$1/has-skill $D $n || P+="has-skill rejects listed $n"; done
}
want setup && {
  rk_sc setup-claude-list
  rk_skill $SC/cfg/skills tdd; rk_skill $SC/repo/.claude/skills repo-review; rk_skill $SC/cfg/plugins/cache/mkt/mp/1.0/skills/eng pr
  rk_skill $SC/cfg/plugins/cache/mkt/mp/0.9/skills/eng gone   # a stale cached version installed_plugins.json doesn't list
  rk_skill $SC/cfg/plugins/cache/mkt/other/1.0/skills notmine   # project-scoped to another repo
  rk_skill $SC/repo/.claude/skills tdd                          # the same name twice: the user's is listed
  print -r -- '{"version": 2, "plugins": {"other@mkt": [{"scope": "project", "projectPath": "'$SC'/elsewhere", "installPath": "'$SC'/cfg/plugins/cache/mkt/other/1.0"}], "mp@mkt": [{"scope": "user", "installPath": "'$SC'/cfg/plugins/cache/mkt/mp/1.0"}]}}' > $SC/cfg/plugins/installed_plugins.json   # project-scoped first: it must not stop the search
  ls_is claude "$(print -rl -- claude-api code-review fewer-permission-prompts init keybindings-help loop \
    $'pr\t@SB@/w/setup-claude-list/cfg/plugins/cache/mkt/mp/1.0/skills/eng/pr/SKILL.md' \
    $'repo-review\t@SB@/w/setup-claude-list/repo/.claude/skills/repo-review/SKILL.md' \
    run schedule security-review simplify \
    $'tdd\t@SB@/w/setup-claude-list/cfg/skills/tdd/SKILL.md' update-config | sed $'/\t/!s/$/\t-/')"
  verdict "SETUP claude list-skills: plugin, user, repo and built-in skills, sorted, each one has-skill accepts"

  rk_sc setup-codex-list codex
  rk_skill $SC/codex-home/skills/.system review-agent; rk_skill $SC/home/.agents/skills tdd; rk_skill $SC/repo/.agents/skills pr
  rk_skill $SC/codex-home/plugins/cache/mkt/mp/1.0/skills/eng unslop
  ls_is codex "$(print -rl -- \
    $'pr\t@SB@/w/setup-codex-list/repo/.agents/skills/pr/SKILL.md' \
    $'review-agent\t@SB@/w/setup-codex-list/codex-home/skills/.system/review-agent/SKILL.md' \
    $'tdd\t@SB@/w/setup-codex-list/home/.agents/skills/tdd/SKILL.md' \
    $'unslop\t@SB@/w/setup-codex-list/codex-home/plugins/cache/mkt/mp/1.0/skills/eng/unslop/SKILL.md')"
  verdict "SETUP codex list-skills: ~/.agents, CODEX_HOME (.system too), plugin and repo skills, each one has-skill accepts"

  rk_sc setup-copilot-list copilot
  rk_skill $SC/copilot-home/skills tdd; rk_skill $SC/repo/.github/skills pr; rk_skill $SC/repo/.claude/skills unslop
  mkdir -p $SC/copilot-home/pkg/darwin-arm64/{1.0.96,1.0.9}/definitions $SC/copilot-home/pkg/darwin-arm64/1.0.96/builtin-skills/pr-media
  : > $SC/copilot-home/pkg/darwin-arm64/1.0.96/definitions/security-review.agent.yaml
  : > $SC/copilot-home/pkg/darwin-arm64/1.0.9/definitions/code-review.agent.yaml   # only in an older CLI version
  ls_is copilot "$(print -rl -- \
    $'pr\t@SB@/w/setup-copilot-list/repo/.github/skills/pr/SKILL.md' 'pr-media	-' $'security-review\t@SB@/w/setup-copilot-list/copilot-home/pkg/darwin-arm64/1.0.96/definitions/security-review.agent.yaml' \
    $'tdd\t@SB@/w/setup-copilot-list/copilot-home/skills/tdd/SKILL.md' \
    $'unslop\t@SB@/w/setup-copilot-list/repo/.claude/skills/unslop/SKILL.md')"
  verdict "SETUP copilot list-skills: COPILOT_HOME, repo, built-in skills and the newest CLI's agents, each one has-skill accepts"

  # roles-draft.sh runs next to commodore and agent-teammates, as when installed.
  RDS=$SKILLS/setup-commodore/scripts/roles-draft.sh
  rd_sc() {  # rd_sc <scenario>: rk_sc plus a git repo with one commit, and a clean place outside any repo
    rk_sc $1; rm -rf $SC/repo
    local g=(env -i PATH=/usr/bin:/bin HOME=$SC/home GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1)
    $g git init -q $SC/repo; $g git -C $SC/repo -c user.email=t@example.com -c user.name=t commit -q --allow-empty -m init
    mkdir -p $SC/outside
  }
  rd() {  # rd [VAR=val ...] <args...>: roles-draft.sh run from the repo (RDCWD overrides), CLAUDECODE=1 unless given
    local v=(); while [[ $1 == *=* ]]; do v+=$1; shift; done
    ( cd ${RDCWD:-$SC/repo} && exec env -i $BASE CLAUDECODE=1 $v $RDS "$@" ) > $SC/out 2> $SC/err
    RC=$?
  }
  rd_run() { RUN=$(sed -n 1p $SC/out); [[ -d $RUN && -f $RUN/team.env ]] || P+="init's first line isn't a run dir: $(head -c 200 $SC/out | tr '\n' '|')"; }
  out_line() { grep -qxF -- "$1" $SC/out || P+="no line '$1' in: $(head -c 400 $SC/out | tr '\n' '|')"; }
  repo_clean() { [[ -z $(git -C $SC/repo status --porcelain 2>&1) ]] || P+="the repo changed: $(git -C $SC/repo status --porcelain | tr '\n' '|')"; }

  rd_sc setup-init-new; rd init user; rc_is 0; rd_run
  out_line "NEW $SC/xdg/commodore/roles.json"
  out_line "ROLES $SB/src/skills/engineering/commodore/references/roles.md"
  [[ $(<$RUN/draft.json) == '{}' ]] || P+="draft isn't {}: $(<$RUN/draft.json)"
  grep -qx 'HARNESS=claude' $RUN/team.env || P+="team.env lacks HARNESS=claude"
  grep -qx "REPO=$SC/repo" $RUN/team.env || P+="team.env lacks REPO=$SC/repo"
  repo_clean
  verdict "SETUP init: a scratch run dir with HARNESS and REPO, and an empty draft when the target file doesn't exist"

  rd_sc setup-init-existing; rk_repo '{"scribe": {"skills": ["pr"], "instructions": "keep"}}'
  rd init repo; rc_is 0; rd_run
  out_line "FROM $SC/repo/.commodore/roles.json"
  [[ $(jq -c . $RUN/draft.json) == '{"scribe":{"skills":["pr"],"instructions":"keep"}}' ]] || P+="draft isn't the repo file: $(<$RUN/draft.json)"
  verdict "SETUP init: the draft starts from the target file's entries"

  rd_sc setup-init-harness; rd CLAUDECODE= init user; rc_is 5; err_has 'harness'
  rd CLAUDECODE= init user codex; rc_is 0; rd_run
  grep -qx 'HARNESS=codex' $RUN/team.env || P+="team.env lacks HARNESS=codex"
  RDCWD=$SC/outside rd init repo; rc_is 5; err_has 'git'
  rd init team; rc_is 5
  rd; rc_is 5; grep -q shift $SC/err && P+="no-argument call printed a shift error"
  rd init user; RUN=$(sed -n 1p $SC/out)
  grep -qx 'TARGET=user' $RUN/team.env || P+="team.env lacks TARGET=user"
  verdict "SETUP init: refuses without one harness (unless named), a repo target outside a repo, and an unknown target"

  rd_sc setup-skills
  mkdir -p $SC/cfg/skills/tdd; print -rl -- '---' 'name: tdd' 'description: test skill' '---' > $SC/cfg/skills/tdd/SKILL.md
  mkdir -p $SC/cfg/skills/pr; print -rl -- '---' 'name: pr' 'description: >-' '  Write a PR body.' '  Use when opening a PR.' 'other: x' '---' > $SC/cfg/skills/pr/SKILL.md
  mkdir -p $SC/cfg/skills/quoted; print -rl -- '---' 'name: quoted' 'description: "Says: hi"' '---' > $SC/cfg/skills/quoted/SKILL.md
  mkdir -p $SC/cfg/skills/nodesc; print -rl -- '---' 'name: nodesc' '---' 'description: body text' > $SC/cfg/skills/nodesc/SKILL.md
  rd init user; RUN=$(sed -n 1p $SC/out); rd skills $RUN; rc_is 0
  out_line "tdd"$'\t'"$SC/cfg/skills/tdd/SKILL.md"$'\t'"test skill"
  out_line "pr"$'\t'"$SC/cfg/skills/pr/SKILL.md"$'\t'"Write a PR body. Use when opening a PR."
  out_line "quoted"$'\t'"$SC/cfg/skills/quoted/SKILL.md"$'\t'"Says: hi"
  out_line $'code-review\t-\t-'
  out_line "nodesc"$'\t'"$SC/cfg/skills/nodesc/SKILL.md"$'\t'"-"
  verdict "SETUP skills: each available skill with its description (folded and quoted ones too), - for a built-in"

  rd_sc setup-check-user; for n in tdd pr; do rk_skill $SC/cfg/skills $n; done
  rk_repo '{"implementer": {"skills": ["missing-in-repo"]}, "triager": {"skills": ["gone-from-repo"]}}'
  rd init user; RUN=$(sed -n 1p $SC/out)
  print -r -- '{"implementer": {"skills": ["pr"]}, "scribe": {"skills": ["pr", "missing"]}, "reviewer": {"skills": ["x"], "agent": "y"}}' > $RUN/draft.json
  rd check $RUN; rc_is 0
  row_is implementer '| implementer | `/pr` | - | draft |'
  row_is scribe '| scribe | `/pr` | - | draft |'
  grep -q '^| triager ' $SC/out && P+="showed a row the draft doesn't decide"
  out_line 'WARN  scribe: skill /missing is not available on claude; dropped'
  out_line 'WARN  reviewer: skill /x is not available on claude; dropped'
  out_line 'WARN  draft: reviewer: unknown field "agent" skipped'
  out_line "SHADOWED implementer: $SC/repo/.commodore/roles.json sets it, so this entry does nothing in this repo"
  out_line "UNSET triager: the repo's file decides, else the fallback"
  grep -qE 'gone-from-repo|missing-in-repo|security-reviewer has no' $SC/out && P+="showed a warning the draft doesn't cause"
  out_line 'NOT CLEAN: 3 warnings'
  [[ $(git -C $SC/repo status --porcelain --untracked-files=all) == '?? .commodore/roles.json' ]] || P+="check wrote to the repo"
  verdict "SETUP check user: the draft's own rows and warnings, shadowing by the repo, UNSET roles, NOT CLEAN"

  rd_sc setup-check-repo; rk_skill $SC/cfg/skills pr; rk_user '{"scribe": {"skills": ["missing-in-user"]}}'
  rk_repo '{"reviewer": {"skills": ["nonexistent-x"], "instructions": "old"}, "scribe": {"skills": ["pr"]}}'
  rd init repo; RUN=$(sed -n 1p $SC/out)
  print -r -- '{"scribe": {"skills": ["/pr"]}, "security-reviewer": {"skills": []}}' > $RUN/draft.json
  rd check $RUN; rc_is 0
  row_is scribe '| scribe | `/pr` | - | draft |'
  row_is security-reviewer '| security-reviewer | none: not launched | - | draft |'
  grep -qE '^\| reviewer |nonexistent-x|old' $SC/out && P+="showed the entry the draft removed from the repo file"
  out_line "UNSET reviewer: each engineer's user-global file decides, else the fallback"
  out_line 'WARN  security-reviewer has no role skill: no security review this run'
  out_line 'CLEAN'
  grep -q SHADOWED $SC/out && P+="a repo entry can't be shadowed"
  print -r -- '{"scribe": ' > $RUN/draft.json; rd check $RUN; rc_is 1; err_has 'draft'
  verdict "SETUP check repo: rows only for the draft's roles, a removed entry shows as UNSET, CLEAN; invalid JSON exits 1"

  rd_sc setup-save-user; rd init user; RUN=$(sed -n 1p $SC/out)
  print -r -- '{"scribe": {"skills": "/pr", "instructions": "Draft with pr."}, "reviewer": {"skills": ["$code-review", "unslop"]}}' > $RUN/draft.json
  rd save $RUN; rc_is 0
  out_line "SAVED $SC/xdg/commodore/roles.json"
  [[ $(jq -c . $SC/xdg/commodore/roles.json 2>&1) == '{"scribe":{"skills":["pr"],"instructions":"Draft with pr."},"reviewer":{"skills":["code-review","unslop"]}}' ]] || P+="saved: $(<$SC/xdg/commodore/roles.json)"
  repo_clean
  print -r -- '{"scribe": ' > $RUN/draft.json; rd save $RUN; rc_is 1
  [[ $(jq -c .reviewer.skills $SC/xdg/commodore/roles.json) == '["code-review","unslop"]' ]] || P+="an invalid draft overwrote the saved file"
  rd save $RUN repo; rc_is 5
  rd init repo; RUN=$(sed -n 1p $SC/out); print -r -- '{"scribe": {"skills": ["pr"]}}' > $RUN/draft.json
  rd save $RUN; rc_is 0
  [[ $(git -C $SC/repo status --porcelain --untracked-files=all) == '?? .commodore/roles.json' ]] || P+="repo save wrote more than .commodore/roles.json"
  verdict "SETUP save: writes only the init target's file, as ordered arrays of bare names; refuses an invalid draft or another target"
}

# ======================================================================================================================
# ADMIRAL: admiral-io.sh publishes Commodore's Admiral report and inbox items, and reads answers (issue #116, parent
# jbuffin/admiral#112 "Interfaces between Admiral and the skills"). schema-check.py validates a JSON file against a draft
# 2020-12 schema; the two schemas in references/ encode the parent's report and inbox item. Fixtures are concrete
# instances built from the contract's templates. `tests/run.sh admiral` runs just these.
#   schema-check.py <schema> <instance>   exit 0 valid; 1 invalid (reasons on stderr); 2 can't check (unsupported keyword)
#   admiral-io.sh item|report <draft>     exit 0 published or no-op; 2 invalid or item exists; 5 usage
#   admiral-io.sh answer <dir> <id>       exit 0 printed; 3 not answered yet; 2 bad id; 5 usage
# ======================================================================================================================
AD_SCH=$SB/src/skills/engineering/commodore/references
AD_ITEM_SCH=$AD_SCH/admiral-inbox-item.schema.json
AD_REP_SCH=$AD_SCH/admiral-report.schema.json
AD_IO=$CM/admiral-io.sh
AD_SC=$CM/schema-check.py

AD_Q='{"version": 1, "id": "q-1", "kind": "question", "created": "2026-09-21T13:33:20Z", "title": "Two calls need you",
 "question": {"questions": [
   {"id": "1", "text": "Push the fix to the PR branch?", "options": [{"label": "Push", "description": "Force-push with lease."},
    {"label": "Hold", "description": "Leave the branch alone."}], "recommended": "Hold", "multi": false},
   {"id": "2", "text": "Which checks to run?", "options": [{"label": "unit", "description": "Fast."}, {"label": "e2e", "description": "Slow."}],
    "recommended": "unit", "multi": true}]}}'
AD_R='{"version": 1, "id": "rv-7", "kind": "review", "created": "2026-09-21T13:33:20+02:00", "title": "Review of PR 12",
 "order_url": "https://example.com/orders/9",
 "review": {"pr_url": "https://github.com/o/r/pull/12", "review_id": 123, "summary": "Two nits, one real bug."}}'
AD_F='{"version": 1, "id": "f-3", "kind": "findings", "created": "2026-09-21T13:33:20.5Z", "title": "Feedback on PR 12",
 "findings": {"pr_url": "https://github.com/o/r/pull/12", "cards": [
   {"id": "r1", "source": "octocat", "quote": "This leaks a handle.", "verdict": "agree", "reason": "The handle is never closed.",
    "proposal": {"kind": "diff", "content": "--- a/x\n+++ b/x\n"}, "evidence": ["x.sh:12", "tests/run.sh x: FAIL"]},
   {"id": "r2", "source": "lint", "quote": "Rename it.", "verdict": "unclear", "reason": "Both names are in use.",
    "proposal": {"kind": "reply", "content": "Keeping the name."}, "evidence": []}]}}'
AD_DONE='{"version": 1, "result": "done", "why": "Reviewed PR 12 and left it PENDING.", "prs": ["https://github.com/o/r/pull/12"],
 "assumptions": ["took the recommended default on the allow rules"], "inbox": ["rv-7"]}'
AD_PART='{"version": 1, "result": "partial", "why": "Two questions need the engineer.", "prs": [],
 "assumptions": [], "inbox": ["q-1"], "resume": "/commodore resume run-9"}'
AD_FAIL='{"version": 1, "result": "failed", "why": "The build never went green."}'

jqm() { print -r -- "$1" | jq -c "$2"; }   # jqm <json> <filter>: the mutated instance
# sck <schema> <want-rc> <json>: validate through schema-check.py; failures land in P
sck() {
  print -r -- "$3" > $SC/inst.json
  xrun $AD_SC $1 $SC/inst.json
  [[ $RC == $2 ]] || P+="schema-check exit $RC, want $2 for $(print -r -- $3 | head -c 90 | tr '\n' ' '); stderr: $(head -c 200 $SC/err | tr '\n' '|')"
  [[ $2 == 1 && ! -s $SC/err ]] && P+="no reason on stderr for $(print -r -- $3 | head -c 90 | tr '\n' ' ')"
  [[ -s $SC/out ]] && P+="schema-check wrote to stdout"
  return 0
}
nfiles() { [[ -d $1 ]] && find $1 -type f 2>/dev/null | wc -l | tr -d ' ' || echo 0; }
# aio <env VAR=val...> -- args: run admiral-io.sh with only BASE plus the variables
aio() {
  local -a e=(); while [[ $1 != -- ]]; do e+=$1; shift; done; shift
  xrun $e $AD_IO "$@"
}
same_json() { [[ -f $1 && $(jq -S . $1 2>/dev/null) == $(print -r -- "$2" | jq -S .) ]] || P+="$1 doesn't hold the draft: $(head -c 150 $1 2>&1 | tr '\n' ' ')"; }

want admiral-static && {
  sc admiral-static
  [[ -x $AD_IO ]] || P+="admiral-io.sh missing or not executable"
  [[ $(head -1 $AD_IO 2>/dev/null) == '#!/bin/zsh' ]] || P+="admiral-io.sh shebang: '$(head -1 $AD_IO 2>&1)'"
  grep -q $'\r' $AD_IO 2>/dev/null && P+="admiral-io.sh has CRLF"
  [[ -f $AD_IO ]] && { zsh -n $AD_IO 2>/dev/null || P+="zsh -n admiral-io.sh fails" ; }
  [[ $(sed -n 2p $AD_IO 2>/dev/null) == '# usage: admiral-io.sh item <draft.json>'* ]] || P+="line 2 isn't the usage block"
  for s in admiral-report admiral-inbox-item; do
    grep -q "^#.*$s.schema.json" $AD_IO 2>/dev/null || P+="no pointer comment to $s.schema.json"
  done
  verdict "ADMIRAL admiral-io.sh: executable zsh, LF, zsh -n, a usage block at the top, then pointers to both schemas"

  [[ -x $AD_SC ]] || P+="schema-check.py missing or not executable"
  [[ $(head -1 $AD_SC 2>/dev/null) == '#!'*python3* ]] || P+="schema-check.py shebang: '$(head -1 $AD_SC 2>&1)'"
  grep -q $'\r' $AD_SC 2>/dev/null && P+="schema-check.py has CRLF"
  grep -qE '^\s*(import|from) (jsonschema|referencing|fastjsonschema)' $AD_SC 2>/dev/null && P+="schema-check.py imports a third-party validator"
  if command -v ruff >/dev/null; then
    ruff check --config $ROOT/ruff.toml --no-cache $ROOT/skills/engineering/commodore/scripts/schema-check.py >$SC/ruff.out 2>&1 || P+="ruff check: $(head -c 200 $SC/ruff.out | tr '\n' '|')"
    ruff format --config $ROOT/ruff.toml --no-cache --check $ROOT/skills/engineering/commodore/scripts/schema-check.py >$SC/ruff.out 2>&1 || P+="ruff format: $(head -c 200 $SC/ruff.out | tr '\n' '|')"
  else echo "skip  ADMIRAL ruff (not installed)"; fi
  verdict "ADMIRAL schema-check.py: executable stdlib-only python3, LF, ruff-clean"
}

want admiral-schema && {
  sc admiral-schema
  for f in $AD_ITEM_SCH $AD_REP_SCH; do
    jq -e '."$schema" == "https://json-schema.org/draft/2020-12/schema"' $f >/dev/null 2>&1 || P+="${f:t}: missing or not a 2020-12 JSON file"
  done
  jq -e '[.. | objects | select(.pattern? == "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$") | .description? // ""] | any(test("Commodore"))' $AD_ITEM_SCH >/dev/null 2>&1 \
    || P+="item schema: no id pattern ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}\$ with a description saying it's Commodore's addition"
  jq -e '[.. | objects | .description? // empty | strings] | any(test("skills#118"))' $AD_ITEM_SCH >/dev/null 2>&1 \
    || P+="item schema: no description pointing at jbuffin/skills#118"
  verdict "ADMIRAL schema files: 2020-12, the id rule documented as Commodore's addition, the findings note on #118"

  for p in "question $AD_Q" "review $AD_R" "findings $AD_F"; do
    sck $AD_ITEM_SCH 0 "${p#* }"; [[ $RC == 0 ]] || P+="${p%% *} item rejected"
  done
  sck $AD_ITEM_SCH 0 "$(jqm $AD_Q 'del(.order_url)')"
  sck $AD_ITEM_SCH 0 "$(jqm $AD_Q '.order_url="https://x"')"
  sck $AD_ITEM_SCH 0 "$(jqm $AD_Q '.future_field={"a":1}')"
  sck $AD_ITEM_SCH 0 "$(jqm $AD_Q '.question.questions[0].id="a.b"')"
  sck $AD_ITEM_SCH 0 "$(jqm $AD_F '.findings.cards[0].id="r.1"')"
  sck $AD_ITEM_SCH 0 "$(jqm $AD_Q '.created="2026-09-21T13:33:20.123456+05:30"')"
  sck $AD_ITEM_SCH 0 "$(jqm $AD_Q ".id=\"${(l:64::a:)}\"")"
  sck $AD_ITEM_SCH 0 "$(jqm $AD_Q '.id="Q_1-a"')"
  verdict "ADMIRAL item schema accepts one concrete item per kind, an omitted order_url, extra top-level fields, dotted card and question ids, offsets"

  for d f in \
    'version missing' 'del(.version)' 'version 2' '.version=2' 'version true' '.version=true' 'version "1"' '.version="1"' \
    'id missing' 'del(.id)' 'kind missing' 'del(.kind)' 'created missing' 'del(.created)' 'title missing' 'del(.title)' \
    'kind bogus' '.kind="note"' 'title a number' '.title=3' \
    'question object missing' 'del(.question)' \
    'review object beside question' '.review={"pr_url":"u","review_id":1,"summary":"s"}' \
    'findings object beside question' '.findings={"pr_url":"u","cards":[]}' \
    'object for another kind only' '.kind="review"' \
    'question without questions' '.question={}' \
    'question text missing' 'del(.question.questions[0].text)' \
    'question id missing' 'del(.question.questions[0].id)' \
    'options missing' 'del(.question.questions[0].options)' \
    'option label missing' 'del(.question.questions[0].options[0].label)' \
    'option description missing' 'del(.question.questions[0].options[1].description)' \
    'recommended missing' 'del(.question.questions[1].recommended)' \
    'multi missing' 'del(.question.questions[0].multi)' \
    'multi a string' '.question.questions[0].multi="false"' \
    'created a date only' '.created="2026-09-21"' 'created without a zone' '.created="2026-09-21T13:33:20"' \
    'created in words' '.created="yesterday"' 'created with a space' '.created="2026-09-21 13:33:20Z"' \
    'created a number' '.created=1790000000' 'created empty' '.created=""' \
    'id empty' '.id=""' 'id leading dot' '.id=".q-1"' 'id with a dot' '.id="q-1.answer"' 'id parent dir' '.id="../q-1"' \
    'id with a slash' '.id="a/b"' 'id leading dash' '.id="-q"' 'id with a space' '.id="q 1"' 'id a number' '.id=1' \
    "id 65 long" ".id=\"${(l:65::a:)}\"" 'id with a newline' '.id="q-1\n"'; do
    sck $AD_ITEM_SCH 1 "$(jqm $AD_Q "$f")"
    [[ $RC == 1 ]] || P+="^ for '$d'"
  done
  for d f in \
    'review object missing' 'del(.review)' 'pr_url missing' 'del(.review.pr_url)' 'review_id missing' 'del(.review.review_id)' \
    'summary missing' 'del(.review.summary)' 'review_id a string' '.review.review_id="123"' 'review_id a boolean' '.review.review_id=true' \
    'review_id fractional' '.review.review_id=1.5' 'question beside review' '.question={"questions":[]}' \
    'findings beside review' '.findings={"pr_url":"u","cards":[]}' 'summary a number' '.review.summary=3'; do
    sck $AD_ITEM_SCH 1 "$(jqm $AD_R "$f")"
    [[ $RC == 1 ]] || P+="^ for review: '$d'"
  done
  for d f in \
    'findings object missing' 'del(.findings)' 'pr_url missing' 'del(.findings.pr_url)' 'cards missing' 'del(.findings.cards)' \
    'cards not an array' '.findings.cards={}' 'card id missing' 'del(.findings.cards[0].id)' 'source missing' 'del(.findings.cards[0].source)' \
    'quote missing' 'del(.findings.cards[0].quote)' 'verdict missing' 'del(.findings.cards[0].verdict)' \
    'verdict maybe' '.findings.cards[1].verdict="maybe"' 'reason missing' 'del(.findings.cards[0].reason)' \
    'proposal missing' 'del(.findings.cards[0].proposal)' 'proposal kind patch' '.findings.cards[0].proposal.kind="patch"' \
    'proposal kind missing' 'del(.findings.cards[0].proposal.kind)' 'proposal content missing' 'del(.findings.cards[1].proposal.content)' \
    'evidence missing' 'del(.findings.cards[0].evidence)' 'evidence not strings' '.findings.cards[0].evidence=[1]' \
    'evidence a string' '.findings.cards[0].evidence="x.sh:1"' 'review beside findings' '.review={"pr_url":"u","review_id":1,"summary":"s"}'; do
    sck $AD_ITEM_SCH 1 "$(jqm $AD_F "$f")"
    [[ $RC == 1 ]] || P+="^ for findings: '$d'"
  done
  verdict "ADMIRAL item schema rejects each missing field, wrong type, wrong enum, two kind objects, bad created and bad id (exit 1, reason on stderr)"

  sck $AD_REP_SCH 0 "$AD_DONE"; sck $AD_REP_SCH 0 "$AD_PART"; sck $AD_REP_SCH 0 "$AD_FAIL"
  sck $AD_REP_SCH 0 "$(jqm $AD_DONE '.future={"x":[1]}')"
  sck $AD_REP_SCH 0 "$(jqm $AD_FAIL '.resume="/commodore resume r"')"
  sck $AD_REP_SCH 0 "$(jqm $AD_DONE '.resume="/commodore resume r"')"
  sck $AD_REP_SCH 0 '{"version": 1, "result": "done", "why": "ok"}'
  verdict "ADMIRAL report schema accepts a done, a partial and a failed report, a minimal one, extra fields, and a resume on any result"

  for d f in \
    'version missing' 'del(.version)' 'version 2' '.version=2' 'version true' '.version=true' 'result missing' 'del(.result)' \
    'result ok' '.result="ok"' 'result capitalised' '.result="Done"' 'why missing' 'del(.why)' 'why a number' '.why=1' \
    'prs a string' '.prs="u"' 'prs holds a number' '.prs=[1]' 'prs an object' '.prs={}' \
    'assumptions a string' '.assumptions="x"' 'assumptions holds an object' '.assumptions=[{}]' \
    'inbox a string' '.inbox="q-1"' 'inbox holds a number' '.inbox=[1]' 'resume a number' '.resume=1'; do
    sck $AD_REP_SCH 1 "$(jqm $AD_PART "$f")"
    [[ $RC == 1 ]] || P+="^ for report: '$d'"
  done
  sck $AD_REP_SCH 1 "$(jqm $AD_PART 'del(.resume)')"
  sck $AD_REP_SCH 1 "$(jqm $AD_PART '.resume=null')"
  sck $AD_REP_SCH 1 '[]'
  sck $AD_REP_SCH 1 '"done"'
  verdict "ADMIRAL report schema rejects each missing field, wrong type and enum, and a partial without a resume (exit 1, reason on stderr)"

  sck $AD_ITEM_SCH 1 "$AD_DONE"; sck $AD_REP_SCH 1 "$AD_Q"
  verdict "ADMIRAL a report isn't an item and an item isn't a report"
}

want admiral-check && {
  sc admiral-check
  S='{"type": "object", "required": ["a"], "properties": {"a": {"const": 1}, "b": {"enum": [true, "x"]}, "n": {"type": "integer"}, "s": {"type": "string", "pattern": "^x"}}, "additionalProperties": false}'
  print -r -- $S > $SC/s.json
  sck $SC/s.json 0 '{"a": 1, "b": "x", "n": 3, "s": "xy"}'
  sck $SC/s.json 1 '{"a": true}'
  sck $SC/s.json 1 '{"a": 1.0, "b": 1}'
  sck $SC/s.json 1 '{"a": 1, "n": true}'
  sck $SC/s.json 1 '{"a": 1, "n": 1.5}'
  sck $SC/s.json 1 '{"a": 1, "extra": 0}'
  sck $SC/s.json 1 '{"a": 1, "s": "yx"}'
  verdict "ADMIRAL schema-check: const, enum, type and pattern don't mistake a boolean for a number; additionalProperties:false; pattern isn't anchored for you"

  print -r -- '{"type": "array", "items": {"type": "object", "required": ["k"]}}' > $SC/i.json
  sck $SC/i.json 0 '[{"k": 1}, {"k": 2}]'; sck $SC/i.json 0 '[]'; sck $SC/i.json 1 '[{"k": 1}, {}]'; sck $SC/i.json 1 '{"k": 1}'
  print -r -- '{"allOf": [{"if": {"properties": {"r": {"const": "p"}}, "required": ["r"]}, "then": {"required": ["z"]}}, {"not": {"required": ["x", "y"]}}]}' > $SC/c.json
  sck $SC/c.json 0 '{"r": "d"}'; sck $SC/c.json 0 '{"r": "p", "z": 1}'; sck $SC/c.json 1 '{"r": "p"}'; sck $SC/c.json 1 '{"x": 1, "y": 1}'; sck $SC/c.json 0 '{"x": 1}'
  verdict "ADMIRAL schema-check: items, allOf, if/then and not"

  print -r -- '{"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "urn:x", "$comment": "c", "title": "t", "description": "d", "default": 1, "examples": [1], "type": "object"}' > $SC/a.json
  sck $SC/a.json 0 '{}'
  for k in '"unevaluatedProperties": false' '"dependentRequired": {"a": ["b"]}' '"propertyNames": {"maxLength": 2}' '"contains": {"type": "string"}'; do
    print -r -- "{\"type\": \"object\", $k}" > $SC/u.json
    sck $SC/u.json 2 '{}'; grep -q "${${k#\"}%%\"*}" $SC/err || P+="stderr doesn't name ${${k#\"}%%\"*}: $(head -c 150 $SC/err)"
  done
  print -r -- '{"properties": {"deep": {"allOf": [{"unevaluatedItems": false}]}}}' > $SC/u.json
  sck $SC/u.json 2 '{}'
  sck $SC/u.json 2 '{"deep": 1}'
  verdict "ADMIRAL schema-check: annotations are fine; any other keyword fails loudly (exit 2), naming it, even nested and even when the instance wouldn't reach it"

  print -r -- '{not json' > $SC/inst.json
  xrun $AD_SC $AD_REP_SCH $SC/inst.json; [[ $RC == 1 || $RC == 2 ]] && [[ -s $SC/err ]] || P+="instance that isn't JSON: exit $RC, stderr '$(head -c 100 $SC/err)'"
  [[ $RC == 0 ]] && P+="bad instance passed"
  xrun $AD_SC $SC/missing.json $SC/inst.json; [[ $RC == 2 ]] || P+="missing schema file: exit $RC, want 2"
  verdict "ADMIRAL schema-check: an instance that isn't JSON fails, and a missing schema exits 2"

  sck $AD_REP_SCH 1 "$(jqm $AD_DONE 'del(.why)')"; grep -q why $SC/err || P+="the reason doesn't name the missing field: $(head -c 150 $SC/err)"
  sck $AD_ITEM_SCH 1 "$(jqm $AD_Q '.created="soon"')"; grep -q created $SC/err || P+="the reason doesn't name created: $(head -c 150 $SC/err)"
  sck $AD_ITEM_SCH 1 "$(jqm $AD_Q '.kind="x"')"; grep -q kind $SC/err || P+="the reason doesn't name kind: $(head -c 150 $SC/err)"
  verdict "ADMIRAL schema-check: the reasons on stderr name the offending field"

  AD_QD='{"version":1,"id":"../../evil","id":"ok-2","kind":"question","kind":"review","created":"2026-09-21T13:33:20Z","title":"t","question":{"questions":[]}}'
  sck $AD_ITEM_SCH 1 "$AD_QD"; grep -q 'duplicate key' $SC/err || P+="duplicate id and kind: the reason doesn't say so: $(head -c 150 $SC/err)"
  sck $AD_REP_SCH 1 '{"version": 1, "result": "done", "why": "a", "why": "b"}'
  sck $AD_REP_SCH 1 '{"version": 1, "result": "done", "why": "x", "assumptions": [], "assumptions": []}'
  sck $AD_REP_SCH 1 '{"version": 1, "result": "done", "why": "x", "n": NaN}'
  sck $AD_REP_SCH 1 '{"version": 1, "result": "done", "why": "x", "n": Infinity}'
  sck $AD_REP_SCH 1 '{"version": 1, "result": "done", "why": "x", "n": [-Infinity]}'
  sck $AD_REP_SCH 1 '{"version": 1, "result": "done", "why": "x", "n": 1e999}'
  sck $AD_REP_SCH 0 '{"version": 1, "result": "done", "why": "x", "n": 1e300}'
  print -r -- '{"a": 1, "a": 2}' > $SC/inst.json; xrun $AD_SC --json $SC/inst.json; [[ $RC == 1 && -s $SC/err ]] || P+="--json with a duplicate key: exit $RC"
  print -r -- '[NaN]' > $SC/inst.json; xrun $AD_SC --json $SC/inst.json; [[ $RC == 1 ]] || P+="--json with NaN: exit $RC"
  print -r -- '{"a": [1, 2.5, "x"]}' > $SC/inst.json; xrun $AD_SC --json $SC/inst.json; [[ $RC == 0 ]] || P+="--json with plain JSON: exit $RC"
  print -r -- '{"required": "abc"}' > $SC/s.json; sck $SC/s.json 2 '{}'
  print -r -- '{"properties": [1]}' > $SC/s.json; sck $SC/s.json 2 '{}'
  print -r -- '{"type": 3}' > $SC/s.json; sck $SC/s.json 2 '{}'
  print -r -- '{"enum": "x"}' > $SC/s.json; sck $SC/s.json 2 '{}'
  print -r -- '{"allOf": {}}' > $SC/s.json; sck $SC/s.json 2 '{}'
  print -r -- '{"pattern": 1}' > $SC/s.json; sck $SC/s.json 2 '{}'
  print -r -- '{"properties": {"a": 5}}' > $SC/s.json; sck $SC/s.json 2 '{}'
  print -r -- '[]' > $SC/s.json; sck $SC/s.json 2 '{}'
  print -r -- '{"pattern": "^a\\\\$"}' > $SC/s.json; sck $SC/s.json 0 '"a\\"'; sck $SC/s.json 1 '"a\\\n"'
  print -r -- '{"pattern": "^[$]x$"}' > $SC/s.json; sck $SC/s.json 0 '"$x"'; sck $SC/s.json 1 '"$x\n"'
  verdict "ADMIRAL schema-check: duplicate keys, NaN, Infinity and 1e999 are refused; a keyword with the wrong kind of argument exits 2; \$ in a pattern means end of string"
}

# ad_sc <name>: a scenario with draft path $SC/draft.json and the inbox/report locations Admiral would set
ad_sc() { sc $1; INB=$SC/ship/inbox/s1/; REP=$SC/ship/reports/s1.json; DR=$SC/draft.json }
ad_draft() { print -r -- "$1" > $DR; }

want admiral-item && {
  ad_sc admiral-item-publish
  ad_draft "$AD_Q"
  aio ADMIRAL_INBOX=$INB -- item $DR
  [[ $RC == 0 ]] || P+="exit $RC; stderr: $(head -c 200 $SC/err)"
  same_json $SC/ship/inbox/s1/q-1.json "$AD_Q"
  [[ $(nfiles $SC/ship/inbox) == 1 ]] || P+="files left in the inbox: $(find $SC/ship/inbox -type f 2>/dev/null | tr '\n' ' ')"
  [[ -s $SC/out ]] && P+="stdout: $(head -c 100 $SC/out)"
  ad_draft "$AD_R"; aio ADMIRAL_INBOX=$SC/inbox2 ADMIRAL_REPORT=$REP -- item $DR
  [[ $RC == 0 ]] || P+="review item: exit $RC; stderr: $(head -c 200 $SC/err)"
  same_json $SC/inbox2/rv-7.json "$AD_R"
  ad_draft "$AD_F"; aio ADMIRAL_INBOX=$SC/inbox2 -- item $DR
  [[ $RC == 0 ]] || P+="findings item: exit $RC; stderr: $(head -c 200 $SC/err)"
  same_json $SC/inbox2/f-3.json "$AD_F"
  [[ $(nfiles $SC/inbox2) == 2 && ! -e $REP ]] || P+="inbox2 holds: $(find $SC/inbox2 -type f 2>/dev/null | tr '\n' ' '); report exists: $([[ -e $REP ]] && echo yes)"
  verdict "ADMIRAL item: publishes a valid item of each kind to <inbox>/<id>.json (creating the directory), leaving no temp file"

  ad_sc admiral-item-unset
  ad_draft "$AD_Q"
  aio -- item $DR
  [[ $RC == 0 ]] || P+="unset: exit $RC"
  [[ $(wc -l < $SC/err | tr -d ' ') == 1 ]] || P+="unset: stderr should be exactly one line: '$(head -c 200 $SC/err)'"
  aio ADMIRAL_INBOX= -- item $DR
  [[ $RC == 0 && $(wc -l < $SC/err | tr -d ' ') == 1 ]] || P+="empty: exit $RC, stderr '$(head -c 200 $SC/err)'"
  aio ADMIRAL_REPORT=$REP -- item $DR
  [[ $RC == 0 && $(wc -l < $SC/err | tr -d ' ') == 1 ]] || P+="only ADMIRAL_REPORT set: exit $RC, stderr '$(head -c 200 $SC/err)'"
  print -r -- '{not json' > $DR
  aio -- item $DR
  [[ $RC == 0 ]] || P+="unset with a broken draft: exit $RC (the draft isn't read)"
  rm -f $DR; aio -- item $DR
  [[ $RC == 0 ]] || P+="unset with no draft file: exit $RC (the draft isn't read)"
  [[ $(nfiles $SC/ship) == 0 && ! -e $SC/ship ]] || P+="created $SC/ship"
  verdict "ADMIRAL item: with ADMIRAL_INBOX unset or empty it reads nothing, writes nothing and exits 0 with one stderr line"

  ad_sc admiral-item-invalid
  for d f in \
    'no title' 'del(.title)' 'no kind' 'del(.kind)' 'two kind objects' '.review={"pr_url":"u","review_id":1,"summary":"s"}' \
    'bad created' '.created="soon"' 'id with a dot' '.id="q-1.answer"' 'id traversal' '.id="../q-1"' 'hidden id' '.id=".q"' \
    'no version' 'del(.version)' 'version 2' '.version=2' 'no id' 'del(.id)' 'no created' 'del(.created)' 'bogus kind' '.kind="note"'; do
    ad_draft "$(jqm $AD_Q "$f")"; rm -rf $SC/ship
    aio ADMIRAL_INBOX=$INB -- item $DR
    [[ $RC == 2 ]] || P+="'$d': exit $RC, want 2"
    [[ -s $SC/err ]] || P+="'$d': no reason on stderr"
    [[ $(nfiles $SC/ship) == 0 ]] || P+="'$d' wrote: $(find $SC/ship -type f 2>/dev/null | tr '\n' ' ')"
  done
  print -r -- '{"version": 1, "id": "q-1"' > $DR; aio ADMIRAL_INBOX=$INB -- item $DR
  [[ $RC == 2 && -s $SC/err && $(nfiles $SC/ship) == 0 ]] || P+="truncated draft: exit $RC, files $(nfiles $SC/ship)"
  ad_draft '[]'; aio ADMIRAL_INBOX=$INB -- item $DR
  [[ $RC == 2 && $(nfiles $SC/ship) == 0 ]] || P+="array draft: exit $RC"
  for d t in \
    'duplicate id and kind' '{"version":1,"id":"../../evil","id":"ok-2","kind":"question","kind":"review","created":"2026-09-21T13:33:20Z","title":"t","question":{"questions":[]}}' \
    'duplicate title' '{"version":1,"id":"q-9","kind":"review","created":"2026-09-21T13:33:20Z","title":"a","title":"b","review":{"pr_url":"u","review_id":1,"summary":"s"}}' \
    'NaN' '{"version":1,"id":"q-9","kind":"review","created":"2026-09-21T13:33:20Z","title":"a","x":NaN,"review":{"pr_url":"u","review_id":1,"summary":"s"}}' \
    'Infinity' '{"version":1,"id":"q-9","kind":"review","created":"2026-09-21T13:33:20Z","title":"a","x":[Infinity],"review":{"pr_url":"u","review_id":1,"summary":"s"}}' \
    '1e999' '{"version":1,"id":"q-9","kind":"review","created":"2026-09-21T13:33:20Z","title":"a","x":1e999,"review":{"pr_url":"u","review_id":1,"summary":"s"}}'; do
    rm -rf $SC/ship; ad_draft "$t"; aio ADMIRAL_INBOX=$INB -- item $DR
    [[ $RC == 2 && -s $SC/err && $(nfiles $SC/ship) == 0 ]] || P+="$d: exit $RC, files $(nfiles $SC/ship)"
  done
  ad_draft "$AD_Q"; aio ADMIRAL_INBOX=$INB -- item $SC/no-such-draft.json
  [[ $RC == 2 || $RC == 5 ]] && [[ $(nfiles $SC/ship) == 0 ]] || P+="missing draft file: exit $RC"
  ad_draft "$(jqm $AD_Q '.id="../../escape"')"; aio ADMIRAL_INBOX=$INB -- item $DR
  [[ ! -e $SC/ship/escape.json && ! -e $SC/escape.json && ! -e $SC/ship/inbox/escape.json ]] || P+="an id with .. escaped the inbox"
  verdict "ADMIRAL item: an invalid draft (missing field, two kind objects, bad created, bad id, not JSON) exits 2 with reasons and writes nothing"

  ad_sc admiral-item-exists
  ad_draft "$AD_Q"
  aio ADMIRAL_INBOX=$INB -- item $DR; [[ $RC == 0 ]] || P+="first publish: exit $RC"
  ad_draft "$(jqm $AD_Q '.title="a different question"')"
  aio ADMIRAL_INBOX=$INB -- item $DR
  [[ $RC == 2 ]] || P+="second publish of q-1: exit $RC, want 2"
  [[ -s $SC/err ]] || P+="no reason on stderr"
  [[ $(jq -r .title $SC/ship/inbox/s1/q-1.json 2>/dev/null) == 'Two calls need you' ]] || P+="the item was overwritten"
  [[ $(nfiles $INB) == 1 ]] || P+="temp file left: $(find $INB -type f 2>/dev/null | tr '\n' ' ')"
  ad_draft "$(jqm $AD_Q '.id="q-2"')"; aio ADMIRAL_INBOX=$INB -- item $DR
  [[ $RC == 0 && $(nfiles $INB) == 2 ]] || P+="a new id is refused: exit $RC"
  verdict "ADMIRAL item: an item is never overwritten; the second publish of an id exits 2, leaves the first intact and no temp file"

  ad_sc admiral-item-dest
  ad_draft "$AD_Q"; mkdir -p $INB/q-1.json
  aio ADMIRAL_INBOX=$INB -- item $DR
  [[ $RC == 2 && -s $SC/err ]] || P+="a directory at <id>.json: exit $RC, want 2 with a reason"
  [[ $(nfiles $INB) == 0 ]] || P+="a directory at <id>.json: files left: $(find $INB -type f 2>/dev/null | tr '\n' ' ')"
  rmdir $INB/q-1.json; mkdir -p $SC/elsewhere; ln -s $SC/elsewhere $INB/q-1.json
  aio ADMIRAL_INBOX=$INB -- item $DR
  [[ $RC == 2 ]] || P+="a symlink to a directory at <id>.json: exit $RC, want 2"
  [[ $(nfiles $SC/elsewhere) == 0 ]] || P+="wrote through the symlink: $(find $SC/elsewhere -type f 2>/dev/null | tr '\n' ' ')"
  rm -f $INB/q-1.json; ln -s $SC/no-such-target $INB/q-1.json
  aio ADMIRAL_INBOX=$INB -- item $DR
  [[ $RC == 2 && ! -e $SC/no-such-target ]] || P+="a dangling symlink at <id>.json: exit $RC"
  aio ADMIRAL_INBOX=/ -- item $DR
  [[ $RC == 2 && ! -e $SC/cwd/q-1.json && ! -e /q-1.json ]] || P+="ADMIRAL_INBOX=/: exit $RC"
  verdict "ADMIRAL item: a directory, a symlink or ADMIRAL_INBOX=/ doesn't publish and doesn't succeed (exit 2, no temp file left)"

  ad_sc admiral-item-hostile
  T='x"; touch '$SC'/pwned; $(touch '$SC'/pwned2) `touch '$SC'/pwned3` \n é 😀'
  ad_draft "$(print -r -- $AD_Q | jq -c --arg t "$T" '.title=$t')"
  aio ADMIRAL_INBOX=$INB -- item $DR
  [[ $RC == 0 ]] || P+="exit $RC; stderr: $(head -c 200 $SC/err)"
  [[ $(jq -r .title $SC/ship/inbox/s1/q-1.json 2>/dev/null) == $(jq -r .title $DR) ]] || P+="the title changed on the way"
  [[ -e $SC/pwned || -e $SC/pwned2 || -e $SC/pwned3 ]] && P+="draft text was executed"
  verdict "ADMIRAL item: text in the draft is data, never evaluated, and survives unchanged"

  ad_sc admiral-item-trailing
  ad_draft "$AD_Q"
  aio ADMIRAL_INBOX=$SC/in/box -- item $DR
  [[ $RC == 0 && -f $SC/in/box/q-1.json ]] || P+="without a trailing slash: exit $RC"
  verdict "ADMIRAL item: ADMIRAL_INBOX with or without a trailing slash"
}

want admiral-report && {
  ad_sc admiral-report-publish
  for r in "done $AD_DONE" "partial $AD_PART" "failed $AD_FAIL"; do
    rm -rf $SC/ship; ad_draft "${r#* }"
    aio ADMIRAL_REPORT=$REP -- report $DR
    [[ $RC == 0 ]] || P+="${r%% *}: exit $RC; stderr: $(head -c 200 $SC/err)"
    same_json $REP "${r#* }"
    [[ $(nfiles $SC/ship) == 1 ]] || P+="${r%% *}: files: $(find $SC/ship -type f 2>/dev/null | tr '\n' ' ')"
  done
  verdict "ADMIRAL report: publishes a done, a partial and a failed report to \$ADMIRAL_REPORT, creating its parent directory, leaving no temp file"

  ad_sc admiral-report-replace
  ad_draft "$AD_PART"; aio ADMIRAL_REPORT=$REP -- report $DR
  ad_draft "$AD_FAIL"; aio ADMIRAL_REPORT=$REP -- report $DR
  [[ $RC == 0 ]] || P+="a repeat in one ship: exit $RC; stderr: $(head -c 200 $SC/err)"
  same_json $REP "$AD_FAIL"
  [[ $(nfiles $SC/ship/reports) == 1 ]] || P+="files: $(find $SC/ship -type f 2>/dev/null | tr '\n' ' ')"
  verdict "ADMIRAL report: a second report in the same ship replaces the first"

  ad_sc admiral-report-dest
  ad_draft "$AD_DONE"; mkdir -p $REP
  aio ADMIRAL_REPORT=$REP -- report $DR
  [[ $RC == 2 && -s $SC/err ]] || P+="a directory at the report path: exit $RC, want 2 with a reason"
  [[ $(nfiles $REP) == 0 ]] || P+="files left in it: $(find $REP -type f 2>/dev/null | tr '\n' ' ')"
  rmdir $REP; aio ADMIRAL_REPORT=$SC/ship/reports/r2/ -- report $DR
  [[ $RC == 2 && ! -e $SC/ship/reports/r2 ]] || P+="a report path ending in a slash: exit $RC"
  for d t in \
    'duplicate why' '{"version": 1, "result": "done", "why": "a", "why": "b"}' \
    'duplicate result' '{"version": 1, "result": "failed", "result": "done", "why": "a"}' \
    'NaN' '{"version": 1, "result": "done", "why": "a", "n": NaN}' \
    'Infinity' '{"version": 1, "result": "done", "why": "a", "n": Infinity}'; do
    rm -rf $SC/ship; ad_draft "$t"; aio ADMIRAL_REPORT=$REP -- report $DR
    [[ $RC == 2 && -s $SC/err && ! -e $SC/ship ]] || P+="$d: exit $RC"
  done
  verdict "ADMIRAL report: a directory or a path ending in a slash doesn't publish; duplicate keys and NaN exit 2"

  ad_sc admiral-report-unset
  ad_draft "$AD_DONE"
  aio -- report $DR
  [[ $RC == 0 && $(wc -l < $SC/err | tr -d ' ') == 1 ]] || P+="unset: exit $RC, stderr '$(head -c 200 $SC/err)'"
  aio ADMIRAL_REPORT= -- report $DR
  [[ $RC == 0 && $(wc -l < $SC/err | tr -d ' ') == 1 ]] || P+="empty: exit $RC, stderr '$(head -c 200 $SC/err)'"
  aio ADMIRAL_INBOX=$INB -- report $DR
  [[ $RC == 0 && $(wc -l < $SC/err | tr -d ' ') == 1 ]] || P+="only ADMIRAL_INBOX set: exit $RC, stderr '$(head -c 200 $SC/err)'"
  print -r -- 'broken' > $DR; aio -- report $DR
  [[ $RC == 0 ]] || P+="unset with a broken draft: exit $RC (the draft isn't read)"
  [[ ! -e $SC/ship ]] || P+="created $SC/ship"
  verdict "ADMIRAL report: with ADMIRAL_REPORT unset or empty it reads nothing, writes nothing and exits 0 with one stderr line"

  ad_sc admiral-report-invalid
  ad_draft "$AD_PART"; aio ADMIRAL_REPORT=$REP -- report $DR   # a good report is already in place
  for d f in \
    'no result' 'del(.result)' 'bad result' '.result="ok"' 'no why' 'del(.why)' 'no version' 'del(.version)' \
    'partial without resume' 'del(.resume)' 'prs not an array' '.prs="u"'; do
    ad_draft "$(jqm $AD_PART "$f")"
    aio ADMIRAL_REPORT=$REP -- report $DR
    [[ $RC == 2 && -s $SC/err ]] || P+="'$d': exit $RC, want 2 with a reason"
    same_json $REP "$AD_PART"
    [[ $(nfiles $SC/ship) == 1 ]] || P+="'$d' left files: $(find $SC/ship -type f 2>/dev/null | tr '\n' ' ')"
  done
  print -r -- '{"version": 1,' > $DR; aio ADMIRAL_REPORT=$REP -- report $DR
  [[ $RC == 2 ]] || P+="truncated draft: exit $RC"
  same_json $REP "$AD_PART"
  ad_sc admiral-report-invalid-fresh; ad_draft "$(jqm $AD_DONE 'del(.why)')"
  aio ADMIRAL_REPORT=$REP -- report $DR
  [[ $RC == 2 && ! -e $SC/ship ]] || P+="fresh invalid: exit $RC, created $SC/ship"
  verdict "ADMIRAL report: an invalid draft exits 2 with reasons and leaves any report already in place untouched"
}

want admiral-answer && {
  ad_sc admiral-answer
  mkdir -p $SC/inbox; A='{"answers": {"1": "Hold", "2": ["unit"]}, "note": "é"}'
  print -r -- "$A" > $SC/inbox/q-1.answer.json
  aio -- answer $SC/inbox q-1
  [[ $RC == 0 ]] || P+="exit $RC; stderr: $(head -c 200 $SC/err)"
  [[ $(jq -S . $SC/out 2>&1) == $(print -r -- "$A" | jq -S .) ]] || P+="stdout isn't the answer: $(head -c 150 $SC/out)"
  aio ADMIRAL_INBOX=$SC/elsewhere -- answer $SC/inbox/ q-1
  [[ $RC == 0 && $(jq -c .note $SC/out 2>&1) == '"é"' ]] || P+="with a trailing slash and another ADMIRAL_INBOX: exit $RC"
  print -r -- '"just a string"' > $SC/inbox/q-s.answer.json
  aio -- answer $SC/inbox q-s
  [[ $RC == 0 && $(jq -r . $SC/out) == 'just a string' ]] || P+="a non-object JSON answer: exit $RC"
  verdict "ADMIRAL answer: prints <inbox-dir>/<id>.answer.json and exits 0, whatever the ADMIRAL variables"

  aio -- answer $SC/inbox q-2
  [[ $RC == 3 && ! -s $SC/out ]] || P+="missing: exit $RC, stdout '$(head -c 100 $SC/out)'"
  aio -- answer $SC/no-such-dir q-1
  [[ $RC == 3 && ! -s $SC/out ]] || P+="no such directory: exit $RC, stdout '$(head -c 100 $SC/out)'"
  print -r -- '{"answers": {"1": "Ho' > $SC/inbox/q-3.answer.json
  aio -- answer $SC/inbox q-3
  [[ $RC == 3 && ! -s $SC/out ]] || P+="mid-write: exit $RC, stdout '$(head -c 100 $SC/out)'"
  [[ -s $SC/err ]] || P+="mid-write: no stderr note"
  : > $SC/inbox/q-4.answer.json
  aio -- answer $SC/inbox q-4
  [[ $RC == 3 && ! -s $SC/out ]] || P+="empty file: exit $RC, stdout '$(head -c 100 $SC/out)'"
  print -r -- '{"answers": {"1": NaN}}' > $SC/inbox/q-6.answer.json
  aio -- answer $SC/inbox q-6
  [[ $RC == 3 && ! -s $SC/out ]] || P+="NaN in the answer: exit $RC, stdout '$(head -c 100 $SC/out)'"
  print -r -- '{"answers": {"1": "a", "1": "b"}}' > $SC/inbox/q-7.answer.json
  aio -- answer $SC/inbox q-7
  [[ $RC == 3 && ! -s $SC/out ]] || P+="duplicate key in the answer: exit $RC, stdout '$(head -c 100 $SC/out)'"
  print -r -- "$A" > $SC/inbox/q-5.json   # the item itself is not its answer
  aio -- answer $SC/inbox q-5
  [[ $RC == 3 && ! -s $SC/out ]] || P+="only the item exists: exit $RC"
  verdict "ADMIRAL answer: a missing, empty or half-written answer exits 3 with nothing on stdout (a note on stderr for the half-written one)"

  print -r -- "$A" > $SC/q-1.answer.json
  for id in 'q-1.answer' '../q-1' '.q' 'a/b' '' '-q' "${(l:65::a:)}"; do
    mkdir -p $SC/inbox/sub; print -r -- "$A" > $SC/inbox/sub/x.answer.json; print -r -- "$A" > $SC/inbox/.q.answer.json
    aio -- answer $SC/inbox/sub "$id"
    [[ $RC == 2 && ! -s $SC/out ]] || P+="id '$id': exit $RC, want 2, stdout '$(head -c 80 $SC/out)'"
  done
  verdict "ADMIRAL answer: an id that fails the id rule exits 2 and reads nothing (no .., no hidden files, no q-1.answer)"
}

want admiral-usage && {
  ad_sc admiral-usage
  ad_draft "$AD_Q"
  for args in '' 'bogus' 'item' 'report' 'answer' 'answer d' 'item a b' 'answer a b c'; do
    aio ADMIRAL_INBOX=$INB ADMIRAL_REPORT=$REP -- ${=args}
    [[ $RC == 5 ]] || P+="'$args': exit $RC, want 5"
    grep -q 'admiral-io.sh item' $SC/out || P+="'$args': usage block not on stdout"
  done
  [[ $(nfiles $SC/ship) == 0 ]] || P+="a usage error wrote: $(find $SC/ship -type f 2>/dev/null | tr '\n' ' ')"
  verdict "ADMIRAL admiral-io.sh: no arguments, an unknown command or the wrong argument count exit 5 and print the usage block"
}

# ======================================================================================================================
# AUTOPILOT: doc checks for Commodore's autopilot mode (issue #116, parent jbuffin/admiral#112). They pin what the skill
# text must say, by meaning-bearing phrases, not exact prose: the `## Autopilot mode` section in SKILL.md and the
# pointers to it from each gate, the mission files' autopilot rules, the Codex and Copilot rows, and that
# the lines autopilot overrides still read as before when it is off (AC1). Assertion style; `tests/run.sh autopilot`
# runs just these.
# ======================================================================================================================
AP_CMD=$ROOT/skills/engineering/commodore
AP_SK=$AP_CMD/SKILL.md
AP_REF=$AP_CMD/references
# ap_sec <file> <heading regex>: the body of the `## ` section whose heading matches, up to the next `## `
ap_sec() { awk -v h="$2" '$0 ~ h && /^## /{p=1; next} p && /^## /{p=0} p' $1; }
# ap_need <text> <regex> <what is missing>: the text must match the case-insensitive extended regex
ap_need() { print -r -- "$1" | grep -qiE -- "$2" || P+="$3"; }
# ap_has <file> <fixed string> <what is missing>: the file still holds this existing line (or fragment) verbatim
ap_has() { grep -qF -- "$2" $1 || P+="$3"; }
# ap_aut <file>: the autopilot parts of a mission or harness file: every `Autopilot` heading's body, and every line naming it
ap_aut() { awk '/^#+ .*[Aa]utopilot/{p=1; next} p && /^#/{p=0} p' $1; grep -i autopilot $1; }

want autopilot && {
  sec=$(ap_sec $AP_SK '^## Autopilot mode$')
  words=$(ap_sec $AP_SK '^## Words used here$')

  [[ $(grep -c '^## Autopilot mode$' $AP_SK) == 1 ]] || P+="SKILL.md must have exactly one '## Autopilot mode' heading"
  (( ${#sec} > 400 )) || P+="the '## Autopilot mode' section is missing or nearly empty"
  verdict "AUTOPILOT SKILL.md has one '## Autopilot mode' section"

  for t in 'autopilot mode' 'call' 'low-stakes' 'high-stakes' 'question item' 'Admiral report'; do
    print -r -- $words | grep -qiE -- "^- (A|An|The) \*\*[^*]*${t}" || P+="'Words used here' has no bullet defining '$t'"
  done
  print -r -- $words | grep -qE 'ADMIRAL_REPORT' || P+="the Admiral report's definition doesn't name \$ADMIRAL_REPORT"
  print -r -- $words | grep -qiE 'final report' || P+="the Admiral report isn't told apart from the final report"
  verdict "AUTOPILOT 'Words used here' defines autopilot mode, call, low-stakes and high-stakes call, question item and Admiral report"

  ap_need "$sec" 'ADMIRAL_AUTOPILOT=1' "turn-on: ADMIRAL_AUTOPILOT=1 isn't named"
  ap_need "$sec" 'launch text.*--autopilot|--autopilot.*launch text|starts? with .?--autopilot' "turn-on: launch text starting with --autopilot isn't named"
  ap_need "$sec" 'autopilot: on' "turn-on: 'autopilot: on' isn't recorded"
  ap_need "$sec" 'Mode, phase, current unit' "turn-on: the record doesn't go under '## Mode, phase, current unit'"
  ap_need "$sec" 'resum.*(show|print|say|report)|(show|print|say|report).*resum' "turn-on: resume doesn't show autopilot"
  ap_need "$sec" 'final report' "turn-on: the final report doesn't show autopilot"
  ap_need "$sec" 'current (launch|run).*(decid|set)|(decid|set).*current launch|launch.*decides' "turn-on: on a resume the current launch doesn't decide, nor is it recorded again"
  verdict "AUTOPILOT section: turning it on, recording 'autopilot: on', showing it on resume and in the final report, the current launch deciding"

  ap_need "$sec" 'ADMIRAL_LOW_STAKES' "classifier: ADMIRAL_LOW_STAKES isn't named"
  ap_need "$sec" '`?advisor`?.*default|default.*`?advisor`?' "classifier: 'advisor' isn't the default"
  ap_need "$sec" 'empty' "classifier: an empty value isn't treated as the default"
  ap_need "$sec" 'low or high stakes, and why' "classifier: the question put to the advisor ('low or high stakes, and why') is missing"
  ap_need "$sec" 'question.*options.*recommendation' "classifier: the advisor isn't given the question, the options and the recommendation"
  ap_need "$sec" 'clear.{0,12}"?low' "classifier: only a clear 'low' counts as low"
  ap_need "$sec" '`never`' "classifier: the 'never' value isn't named"
  ap_need "$sec" 'any other value|other value.*never|unknown value' "classifier: any other value doesn't count as never"
  verdict "AUTOPILOT section: ADMIRAL_LOW_STAKES advisor (default, also empty) and never; any other value is never; only a clear 'low' is low"

  ap_need "$sec" 'no advisor|advisor tool' "high-stakes: no advisor tool in the session isn't a case"
  ap_need "$sec" 'ADVISOR=none' "high-stakes: ADVISOR=none isn't a case"
  ap_need "$sec" 'ADVISOR OFF' "high-stakes: the 'ADVISOR OFF' probe line isn't a case"
  ap_need "$sec" 'on the codex and copilot harnesses' "high-stakes: Codex and Copilot aren't named as always high-stakes"
  ap_need "$sec" 'anything (but|other than) a clear' "high-stakes: an answer other than a clear 'low' isn't a case"
  ap_need "$sec" 'product, scope, departures from the source.*external or irreversible' "high-stakes: product, scope, departures from the source, external and irreversible calls aren't always high-stakes"
  ap_need "$sec" 'cheap to reverse.*part of that question|part of that question.*cheap to reverse' "classifier: 'cheap to reverse' isn't part of the question put to the advisor"
  print -r -- $words | grep -qi 'cheap to reverse' && P+="'Words used here' still adds a second 'cheap to reverse' test to low-stakes"
  ap_need "$sec" 'So is a permission denial \(the denial rule in' "high-stakes: a permission denial isn't a case"
  ap_need "$sec" 'Guarding the coordinator' "high-stakes: the denial rule in 'Guarding the coordinator' isn't pointed at"
  verdict "AUTOPILOT section: every call is high-stakes with no advisor, on Codex and Copilot, on a non-'low' answer; product, scope, irreversible and denials too"

  ap_need "$sec" 'security stop' "security stops: not named as security stops"
  ap_need "$sec" 'never classif|not classif|without classif|skip the classifier|no classifier' "security stops: not marked as never classified"
  ap_need "$sec" 'agent-config' "security stops: mission-review's agent-config stop isn't named"
  ap_need "$sec" 'fork steward|steward.*fork|fork.*steward' "security stops: mission-review's fork-steward question isn't named"
  ap_need "$sec" 'head.mismatch' "security stops: mission-pr-feedback's head-mismatch stop isn't named"
  ap_need "$sec" "mission-pr-feedback.s head.mismatch and agent-config" "security stops: mission-pr-feedback's two stops aren't named"
  verdict "AUTOPILOT section: the four security stops are always high-stakes and never classified"

  ap_need "$sec" '## Autopilot calls|Autopilot calls' "recording: '## Autopilot calls' isn't named"
  ap_need "$sec" 'state\.md' "recording: state.md isn't named"
  ap_need "$sec" 'classification.*reason|reason.*classification' "recording: the classification and its reason aren't recorded"
  ap_need "$sec" 'item id.*inbox dir|inbox dir.*item id' "recording: a high-stakes call's item id and inbox directory aren't recorded"
  ap_need "$sec" "team-init.s template stays unchanged" "recording: that team-init's template stays unchanged and the coordinator adds the heading isn't said"
  ap_need "$sec" 'assumptions' "recording: the Admiral report's assumptions aren't named"
  ap_need "$sec" 'default: ' "recording: the 'default: …' label isn't given"
  ap_need "$sec" 'asked: … \(item <id>\)' "recording: the 'asked: … (item <id>)' label isn't given"
  verdict "AUTOPILOT section: every call under '## Autopilot calls' and in the report's assumptions, labelled default: or asked:"

  ap_need "$sec" 'Mission confirmation \(the mission section, step 3\)' "gate: mission confirmation isn't covered"
  ap_need "$sec" 'detected mission|take the detected' "gate: mission confirmation doesn't take the detected mission"
  ap_need "$sec" 'none or (more than one|several)|more than one|fits none' "gate: none or several fitting missions isn't high-stakes"
  ap_need "$sec" 'can.t tell|unclear' "gate: the unclear pre-mission run isn't covered"
  ap_need "$sec" 'smallest cut' "gate: phase 1 step 2's smallest cut isn't covered"
  ap_need "$sec" 'decision batch' "gate: the decision batch isn't covered"
  ap_need "$sec" 'allow rules.*mode.*ground rules|proposed defaults' "gate: the decision batch doesn't take the proposed defaults for allow rules, mode and ground rules"
  ap_need "$sec" 'security role skill' "gate: the no-security-role-skill rule isn't covered"
  ap_need "$sec" 'security role skill.*push code.*high-stakes' "gate: no security role skill isn't high-stakes when the run would push code"
  ap_need "$sec" 'review pushes nothing.*classifier' "gate: for review, no security role skill doesn't go through the classifier"
  ap_need "$sec" 'clear "low" takes the default.*no security reviewer' "gate: for review, a clear 'low' doesn't take the default (no security reviewer)"
  ap_need "$sec" 'anything else makes it a question item' "gate: for review, anything but a clear 'low' isn't a question item"
  ap_need "$sec" 'keychain' "gate: step 5's Keychain secrets aren't covered"
  ap_need "$sec" 'finding of the probe \(step 5\.4\)' "gate: the probe's findings (step 5.4) aren't covered"
  ap_need "$sec" 'bubbling questions up' "gate: 'Bubbling questions up' isn't covered"
  ap_need "$sec" 'when the advisor is off' "gate: 'When the advisor is off' isn't covered"
  ap_need "$sec" "record.*don.t wait|don.t wait|never wait|without waiting" "gate: an off advisor isn't recorded without waiting"
  ap_need "$sec" 'mission-review' "gate: the review mission's posting doesn't point to mission-review"
  verdict "AUTOPILOT section: names each gate and what it does (mission confirmation, unclear run, smallest cut, decision batch, secrets, probe, bubbling, advisor off, review posting)"

  ap_need "$sec" 'AskUserQuestion' "gates: the section doesn't say it replaces AskUserQuestion"
  ap_need "$sec" 'ask the engineer' "gates: the section doesn't say it replaces 'ask the engineer'"
  ap_need "$sec" 'replac' "gates: the section doesn't say it replaces the engineer questions"
  verdict "AUTOPILOT section: replaces AskUserQuestion and 'ask the engineer' wherever a gate uses them"

  mis=$(ap_sec $AP_SK '^## The mission, before phase 1$')
  s2=$(grep -E '^2\. Plan the units' $AP_SK)
  s5=$(awk '/^5\. Run pre-flight/{p=1; next} p && /^6\. Write the common brief/{p=0} p' $AP_SK)
  bub=$(ap_sec $AP_SK '^## Bubbling questions up$')
  grd=$(ap_sec $AP_SK '^## Guarding the coordinator$')
  for pair in 'the mission section:mis' 'phase 1 step 2:s2' 'phase 1 step 5:s5' "'Bubbling questions up':bub" "'Guarding the coordinator':grd"; do
    nm=${pair%:*}; txt=${(P)${pair##*:}}
    print -r -- $txt | grep -qiE 'autopilot' && print -r -- $txt | grep -qF '(#autopilot-mode)' || P+="$nm has no pointer to [Autopilot mode](#autopilot-mode)"
  done
  print -r -- $mis | grep -qiE 'autopilot' && print -r -- $mis | grep -qiE 'confirm' || P+="the mission section's pointer doesn't cover step 3 (confirmation)"
  verdict "AUTOPILOT each gate section links to the Autopilot mode section (mission steps 1 and 3, phase 1 steps 2 and 5, bubbling, guarding)"

  ap_need "$sec" 'one question item|single question item|in one .*question item|every pending question' "stop: every pending question doesn't go in one question item"
  ap_need "$sec" 'options.*recommendation|recommendation.*options' "stop: each question doesn't carry its options and recommendation"
  ap_need "$sec" 'order_url' "stop: order_url being omitted isn't said"
  ap_need "$sec" 'file tool|file-writing tool|file-editing tool' "stop: the draft isn't written with the file tool"
  ap_need "$sec" 'admiral-io\.sh item' "stop: '<team>/admiral-io.sh item <draft>' isn't the publish call"
  ap_need "$sec" 'then publish the Admiral report as \[Ending a run\]' "stop: the report isn't published, after the result: line, as 'Ending a run' says"
  ap_need "$sec" 'result: partial' "stop: 'result: partial' isn't named"
  ap_need "$sec" '`?inbox`?.*item ids|item ids.*`?inbox`?' "stop: the report's inbox doesn't list the item ids"
  ap_need "$sec" '/commodore resume <run-name>' "stop: the resume text '/commodore resume <run-name>' isn't given"
  ap_need "$sec" 'close every teammate' "stop: teammates aren't all closed"
  ap_need "$sec" 'watchdog' "stop: the watchdog isn't stopped"
  ap_need "$sec" 'end (the run )?cleanly|ends? cleanly' "stop: the run doesn't end cleanly"
  verdict "AUTOPILOT section: a high-stakes stop is one question item via the file tool and admiral-io.sh, a partial report with resume, teammates closed, watchdog stopped"

  ap_need "$sec" 'before any mission is recorded' "stop at mission confirmation: 'before any mission is recorded' isn't covered"
  ap_need "$sec" 'team-init\.sh <run-name> <repo>.{0,10} first' "stop at mission confirmation: team-init.sh doesn't run first"
  ap_need "$sec" 'write no `mission:` line' "stop at mission confirmation: no 'mission:' line isn't said"
  ap_need "$sec" 'draft in that run directory' "stop at mission confirmation: the draft doesn't live in the run directory"
  ap_need "$mis" 'no `mission:` line, says `result: partial`' "mission section: a run with no mission: line and result: partial isn't resumed to settle the mission from the answer"
  ap_need "$mis" 'settle the mission from them \(only from an exact option label the item offered; free text counts as unanswered\)' "mission section: the mission isn't settled only from an exact option label (free text counts as unanswered)"
  ap_need "$mis" 'launch text recorded under `## Autopilot calls`' "mission section: the resumed run doesn't use the launch text recorded under '## Autopilot calls'"
  ap_need "$sec" 'item and the original launch text under `## Autopilot calls`' "stop at mission confirmation: the original launch text isn't recorded"
  ap_need "$sec" 'replace any character of the run name outside `\[A-Za-z0-9_-\]` with `-` and truncate it so the id fits 64' "stop: an id from a run name with other characters isn't cleaned and truncated"
  ap_need "$sec" 'resume without `--autopilot`, and the open questions under `## Autopilot calls` are asked as normal gates' "no inbox: a resume without --autopilot doesn't ask the open questions as normal gates"
  ap_need "$sec" 'ADMIRAL_INBOX.{0,40}unset|unset.{0,40}ADMIRAL_INBOX' "no inbox: autopilot with ADMIRAL_INBOX unset isn't covered"
  ap_need "$sec" 'never wait' "no inbox: 'never wait' isn't said"
  ap_need "$sec" 'questions in .?state\.md.? and the final report|state\.md and the final report' "no inbox: the questions don't go in state.md and the final report"
  ap_need "$sec" 'engineer answers in the session' "no inbox: the engineer can't answer in the session to resume by hand"
  verdict "AUTOPILOT section: a stop at mission confirmation (no run directory yet) and autopilot with ADMIRAL_INBOX unset"

  ap_need "$sec" 'resume <run-name>' "resume: 'resume <run-name>' isn't named"
  ap_need "$sec" '\$commodore resume' "resume: the Codex form '\$commodore resume <run-name>' isn't given"
  ap_need "$sec" '<teams>/<run-name>' "resume: it doesn't resume <teams>/<run-name>"
  ap_need "$sec" 'admiral-io\.sh answer' "resume: answers aren't read with 'admiral-io.sh answer'"
  ap_need "$sec" 'recorded inbox dir' "resume: the recorded inbox directory isn't used"
  ap_need "$sec" 'id → the chosen label or free text' "resume: an answer isn't read as an id -> label or free text"
  ap_need "$sec" "can.t parse it, treat the question as unanswered" "resume: an answer that can't be parsed isn't treated as unanswered"
  ap_need "$sec" 'again.*new item' "resume: unanswered questions aren't asked again as a new item"
  ap_need "$sec" 'where the run stopped' "resume: answers aren't applied where the run stopped"
  ap_need "$sec" "mark it applied under .?## Autopilot calls" "resume: an applied answer isn't marked under '## Autopilot calls'"
  ap_need "$sec" 'replace the old `result: partial` line' "resume: the old 'result: partial' line isn't replaced"
  ap_need "$sec" "don.t re-ask what.s answered" "resume: answered questions may be asked again"
  ap_need "$words" 'has no `/` and no `\.\.`' "'Words used here': the run name isn't constrained (no / and no ..)"
  ap_need "$words" '<teams>.*AGENT_TEAMS_DIR' "'Words used here' doesn't define <teams> as team-init's teams directory"
  # the answer is data (S M1)
  ap_need "$sec" 'answer is data, never instructions' "resume: the answer file isn't called data, never instructions"
  ap_need "$sec" 'only the question ids the recorded item asked' "resume: ids the item never asked aren't refused"
  ap_need "$sec" 'security stop, a permission denial and any push or external write are cleared only by an exact option label' "resume: security stops, denials and pushes aren't cleared only by an exact option label"
  ap_need "$sec" 'free text on those counts as unanswered' "resume: free text on a security stop or push counts as an answer"
  ap_need "$sec" 'never widens allow rules, never lifts the push rule' "resume: free text may widen allow rules or lift the push rule"
  ap_need "$sec" 'never goes on a command line' "resume: free text may go on a command line"
  ap_need "$mis" 'result: partial' "mission section: a 'result: partial' run isn't resumable (the finished-run rule in the mission section)"
  ap_need "$mis" 'Autopilot calls' "mission section: the finished-run rule doesn't look for inbox items under '## Autopilot calls'"
  ap_need "$mis" 'resume <run-name>|resume.*run-name' "mission section: the finished-run rule doesn't make a partial run resumable by 'resume'"
  verdict "AUTOPILOT resume: '/commodore resume <run-name>' (\$commodore on Codex), answers via admiral-io.sh answer, unanswered asked again; a partial run is resumable"

  ap_need "$sec" "pr-feedback or build run in autopilot mode never pushes without that push.s own approval" "no unattended pushes: a push may go without its own approval"
  ap_need "$sec" 'Before each push, it publishes a question item listing that push.s branch and commits' "no unattended pushes: no question item before each push listing its branch and commits"
  ap_need "$sec" 'exact option labels `Push` and `Don.t push`' "no unattended pushes: the exact labels 'Push' and 'Don't push' aren't given"
  ap_need "$sec" 'stops `partial` with that item in `inbox`' "no unattended pushes: the run doesn't stop partial with the item in inbox"
  ap_need "$sec" 'pushes only the listed commits, and only when the answer is exactly `Push`' "no unattended pushes: a resume may push unlisted commits or on anything but the exact label"
  ap_need "$sec" 'A later push, including a CI fix or another unit, needs a new item' "no unattended pushes: a later push doesn't need a new item"
  ap_need "$sec" 'Don.t push. ends the run `partial`, lists the unpushed branches and worktrees, and removes nothing' "no unattended pushes: 'Don't push' doesn't end partial, list the unpushed work and remove nothing"
  print -r -- $sec | grep -qi 'first push' && P+="the push rule still says 'first push' (each push needs its own approval)"
  verdict "AUTOPILOT section: a pr-feedback or build run never pushes without an exact-label approval (question item, partial stop, resume pushes only on 'Push')"

  ap_need "$sec" 'applies only in autopilot mode\. With it off, every gate reads as written' "scope: the section doesn't say that with it off every gate reads as written"
  verdict "AUTOPILOT section limits itself to autopilot mode (with it off, every gate reads as written)"

  # ---- ending a run: one shared rule outside the Autopilot section ----
  endr=$(ap_sec $AP_SK '^## Ending a run$')
  ap_need "$endr" 'in any mode' "ending a run: the rule isn't for any mode"
  ap_need "$endr" 'Write the `result:` line into `state\.md`' "ending a run: the result: line in state.md isn't written"
  ap_need "$endr" '`done`, `partial` or `failed`' "ending a run: done, partial and failed aren't the results"
  ap_need "$endr" '`failed` means the run can.t go on for a reason no answer would fix' "ending a run: 'failed' isn't defined"
  ap_need "$endr" 'a tool or a script fails, the repo or the PR is gone' "ending a run: failed doesn't give its causes"
  ap_need "$endr" 'When `ADMIRAL_REPORT` is set, publish the Admiral report' "ending a run: the Admiral report isn't published when ADMIRAL_REPORT is set"
  ap_need "$endr" 'for `partial` a `resume` of `/commodore resume <run-name>`' "ending a run: every partial doesn't get a resume"
  ap_need "$endr" 'admiral-report\.schema\.json' "ending a run: the report schema isn't linked"
  ap_need "$endr" 'version. \(1\), `result`, `why`' "ending a run: the report's required fields aren't listed"
  ap_need "$endr" 'admiral-io\.sh report <draft>' "ending a run: '<team>/admiral-io.sh report <draft>' isn't the report call"
  ap_need "$endr" 'Exit 2 means fix the draft' "ending a run: exit 2 isn't handled"
  ap_need "$endr" 'every draft you publish.*file tool, never with a heredoc, `printf` or its text on a command line' "ending a run: the file-tool rule for every draft isn't stated"
  ap_need "$endr" 'question and review items' "ending a run: the file-tool rule doesn't cover question and review items"
  print -r -- $sec | grep -qiE 'ADMIRAL_REPORT' && P+="the Autopilot section still carries the every-run rule (it belongs in 'Ending a run')"
  print -r -- $sec | grep -qF '(#ending-a-run)' || P+="the Autopilot section doesn't point at 'Ending a run'"
  for pair in "mission-build.md:$AP_REF/mission-build.md" "mission-pr-feedback.md:$AP_REF/mission-pr-feedback.md" "mission-review.md:$AP_REF/mission-review.md"; do
    f=${pair#*:}
    grep -F 'End it with a `result:` line' $f | grep -qF '(../SKILL.md#ending-a-run) writes it into `state.md` and publishes the Admiral report; the run can also end `failed`' || P+="${pair%%:*}: the result: line doesn't point at 'Ending a run', or doesn't say failed is possible"
    grep -qF 'Write the same `result:` line' $f && P+="${pair%%:*}: still copies the result: line instead of linking 'Ending a run'"
  done
  print -r -- "$endr" | grep -q '^1\. Write the `result:` line' || P+="ending a run: the result: line isn't step 1 (before the report)"
  ap_need "$endr" 'resume. of a finished run says it.s finished and stops' "ending a run: a resume of a finished run isn't said to stop"
  grep -F 'skip to phase 3 step 6 and end with `result: partial`' $AP_REF/mission-review.md | grep -qF '(../SKILL.md#ending-a-run)' || P+="mission-review.md: the security 'no' (result: partial) doesn't point at 'Ending a run'"
  ap_need "$sec" 'admiral-inbox-item\.schema\.json' "stop: the item schema isn't linked"
  ap_need "$sec" '<run-name>-q<n>' "stop: the item id scheme '<run-name>-q<n>' isn't given"
  ap_need "$sec" 'a re-ask gets the next `n`' "stop: a re-ask doesn't get the next n"
  ap_need "$sec" '`version` \(1\), `id`.*`kind` `question`, `created`' "stop: the item's required fields aren't listed"
  ap_need "$sec" 'each with .id., .text., .options\[\]. \(.label., .description.\), .recommended. and .multi.' "stop: each question's fields aren't listed"
  verdict "AUTOPILOT 'Ending a run': one rule for any mode (result: line, Admiral report when ADMIRAL_REPORT is set, partial resume, failed defined, file-tool drafts), pointed at by each mission and the stop"

  # ---- mission-review --------------------------------------------------------------------------------------------
  mr=$AP_REF/mission-review.md
  mra=$(ap_aut $mr)
  mr3=$(awk '/^## Phase 3/{p=1; next} p && /^## /{p=0} p' $mr)
  ap_need "$mra" 'autopilot' "mission-review.md never mentions autopilot mode"
  ap_need "$mra" 'Autopilot mode\]\(\.\./SKILL\.md#autopilot-mode\)|SKILL\.md#autopilot-mode' "mission-review.md doesn't link SKILL.md's Autopilot mode section"
  ap_need "$mra" 'go into one question item' "mission-review: direct questions don't go into one question item"
  ap_need "$mra" "step 2.s clone question" "mission-review: the clone question (phase 1 step 2) isn't covered"
  ap_need "$mra" 'security role skill \(phase 1 step 7\) is a call that goes through the classifier' "mission-review: the no-security-role-skill call (phase 1 step 7) doesn't go through the classifier"
  ap_need "$mra" 'security stop' "mission-review: the agent-config stop and fork steward aren't security stops"
  ap_need "$mra" 'agent-config stop \(phase 1 step 6\)' "mission-review: the agent-config stop (phase 1 step 6) isn't named"
  ap_need "$mra" 'fork steward question \(phase 1 step 8\)' "mission-review: the fork steward (phase 1 step 8) isn't named"
  verdict "AUTOPILOT mission-review: direct questions in one question item; agent-config stop and fork steward are security stops"

  ap_need "$mra" 'builds `review.json` with no `event`' "mission-review posting: review.json has no event"
  ap_need "$mra" 'so the review stays PENDING' "mission-review posting: the review isn't left PENDING"
  ap_need "$mra" 'same `gh api … /reviews` request' "mission-review posting: the same 'gh api … /reviews' request isn't used"
  ap_need "$mra" 'integer REST `id`' "mission-review posting: the review id isn't the integer REST id"
  ap_need "$mra" '`review_id` \(that integer\)' "mission-review posting: the item's review_id isn't that integer"
  ap_need "$mra" 'publish a `review` item' "mission-review posting: no 'review' inbox item is published"
  ap_need "$mra" '`id` \(`<run-name>-review`, with the run name cleaned' "mission-review posting: the review item's id scheme isn't given"
  ap_need "$mra" 'already exists means it.s already published: carry on' "mission-review posting: exit 2 'already exists' on the review item isn't 'carry on'"
  ap_need "$mra" 'admiral-inbox-item\.schema\.json' "mission-review posting: the item schema isn't linked"
  ap_need "$mra" '`version` \(1\), `id`.*`kind` `review`, `created`, `title`' "mission-review posting: the item's required fields aren't listed"
  ap_need "$mra" 'pr_url' "mission-review posting: the item lacks pr_url"
  ap_need "$mra" 'at most 3 lines|3 lines at most|three lines' "mission-review posting: the summary isn't capped at 3 lines"
  ap_need "$mra" 'admiral-io\.sh item' "mission-review posting: the item isn't published with admiral-io.sh item"
  ap_need "$mra" 'publish a `done` Admiral report' "mission-review posting: a done Admiral report isn't published"
  ap_need "$mra" 'file tool.*as that section says|file tool, as that section says' "mission-review posting: the file-tool rule isn't pointed at"
  ap_need "$mra" 'PENDING review of yours is already on the PR and its body matches `review.json`, it.s this run.s own post' "mission-review posting: a PENDING review matching review.json isn't treated as this run's own post"
  ap_need "$mra" 'record its `id` and go on to the review item' "mission-review posting: this run's own PENDING review isn't recorded"
  ap_need "$mra" 'exact labels `Posted again after I submitted or deleted it` and `Stop`' "mission-review posting: a foreign PENDING review's item lacks the exact labels"
  ap_need "$mra" 'A resume re-checks the reviews before it posts' "mission-review posting: a resume doesn't re-check the reviews first"
  ap_need "$mra" '`Stop` ends the run `done` with nothing posted' "mission-review posting: 'Stop' doesn't end the run done with nothing posted"
  ap_need "$mra" 'phase 3 step 5 stays: post exactly one review' "mission-review: what of phase 3 step 5 is overridden isn't said (post exactly one review stays)"
  ap_need "$mra" 'Never submit, delete or edit the existing review' "mission-review posting: an existing PENDING review may be submitted, deleted or edited"
  ap_need "$mra" "item.s id in .inbox., as \[Ending a run\]" "mission-review posting: the done report doesn't list the item in inbox, as 'Ending a run' says"
  ap_need "$mra" 'never submit' "mission-review posting: 'never submit' isn't said"
  ap_need "$mra" '/events' "mission-review posting: the /events call isn't ruled out"
  ap_need "$mra" 'Phase 3 step 3 doesn.t ask' "mission-review posting: phase 3 step 3 still asks (it should not in autopilot mode)"
  ap_need "$mr3" 'autopilot' "mission-review Phase 3 never mentions autopilot mode"
  verdict "AUTOPILOT mission-review posting: no event (PENDING), same /reviews call, review id recorded, review item, done report, never submits"

  ev=$(grep -F 'Always set `event`' $mr)
  [[ -n $ev ]] || P+="mission-review.md lost the 'Always set \`event\`' line (AC1: it stays for the engineer-present path)"
  print -r -- $ev | grep -qi autopilot || P+="the 'Always set \`event\`' line isn't overridden for autopilot mode"
  ap_need "$mra" 'Overridden in autopilot mode only' "mission-review: nothing is said to override the lines that contradict autopilot"
  ap_need "$mra" 'the stop rule in phase 1 step 7' "mission-review: the stop rule (phase 1 step 7: 'the engineer declines to post') isn't overridden"
  ap_need "$mra" "you.ll need them again to approve the findings" "mission-review: phase 1's closing ('you'll need them again') isn't overridden"
  ap_need "$mra" 'worktree removal, so the worktrees stay and you list them' "mission-review: phase 3 step 6 (worktrees stay; list them) isn't overridden"
  verdict "AUTOPILOT mission-review overrides, in autopilot mode only, 'Always set event', the stop rule, phase 1's 'you'll need them again' and phase 3 step 6 (worktrees stay; list them)"

  # ---- mission-pr-feedback ---------------------------------------------------------------------------------------
  pf=$AP_REF/mission-pr-feedback.md
  pfa=$(ap_aut $pf)
  ap_need "$pfa" 'autopilot' "mission-pr-feedback.md never mentions autopilot mode"
  ap_need "$pfa" 'SKILL\.md#autopilot-mode' "mission-pr-feedback.md doesn't link SKILL.md's Autopilot mode section"
  ap_need "$pfa" 'security stop' "mission-pr-feedback: the pre-triage stops (phase 1 step 3) aren't security stops"
  ap_need "$pfa" 'the head mismatch' "mission-pr-feedback: the head-mismatch stop (phase 1 step 3) isn't named"
  ap_need "$pfa" 'commits that touch agent config' "mission-pr-feedback: the agent-config commits stop (phase 1 step 3) isn't named"
  ap_need "$pfa" 'run the triage, then' "mission-pr-feedback: autopilot doesn't run the triage first"
  ap_need "$pfa" "approval gate \(step 11.s decision batch\)" "mission-pr-feedback: the approval gate (phase 1 step 11) isn't named"
  ap_need "$pfa" "approval gate \(step 11.s decision batch\) as high-stakes" "mission-pr-feedback: the approval gate isn't high-stakes"
  ap_need "$pfa" 'one question item' "mission-pr-feedback: the stop isn't one question item"
  ap_need "$pfa" 'summari[sz]es? the triage' "mission-pr-feedback: the item doesn't summarise the triage"
  ap_need "$pfa" 'edited push-back reply \(step 11\) is asked again as its own item, with the edited text and an `Approve` label' "mission-pr-feedback: an edited reply isn't asked again as its own item with an Approve label"
  ap_need "$pfa" 'a `partial` Admiral report, stop' "mission-pr-feedback: the stop isn't a partial Admiral report, then stop"
  ap_need "$pfa" 'before each push follow \[Autopilot mode\]\(\.\./SKILL\.md#autopilot-mode\) \(Resume, No unattended pushes\)' "mission-pr-feedback: Resume and the push approval before each push aren't pointed at"
  verdict "AUTOPILOT mission-pr-feedback: pre-triage stops are security stops; otherwise triage, then the approval gate is one question item, a partial report, stop"

  # ---- mission-build ---------------------------------------------------------------------------------------------
  mb=$AP_REF/mission-build.md
  mba=$(ap_aut $mb)
  ap_need "$mba" 'autopilot' "mission-build.md never mentions autopilot mode"
  ap_need "$mba" 'SKILL\.md#autopilot-mode' "mission-build.md doesn't link SKILL.md's Autopilot mode section"
  ap_need "$mba" 'plan \(phase 1 steps 1–4\)' "mission-build: autopilot doesn't plan first (phase 1 steps 1-4)"
  ap_need "$mba" 'allow rules' "mission-build: autopilot doesn't draft the allow rules (step 5.1)"
  ap_need "$mba" 'list the secrets \(step 5\.1\)' "mission-build: autopilot doesn't list the secrets (step 5.1)"
  ap_need "$mba" 'decision batch' "mission-build: the decision batch isn't in the item"
  ap_need "$mba" "step 2.s cut question" "mission-build: step 2's cut question isn't in the item"
  ap_need "$mba" 'one question item' "mission-build: the stop isn't one question item"
  ap_need "$mba" 'report `partial` and stop' "mission-build: the stop isn't a partial Admiral report, then stop"
  ap_need "$mba" 'before each push follow \[Autopilot mode\]\(\.\./SKILL\.md#autopilot-mode\) \(Resume, No unattended pushes\)' "mission-build: Resume and the push approval before each push aren't pointed at"
  verdict "AUTOPILOT mission-build: plan, draft the allow rules, list the secrets, then decision batch, secrets and cut question in one question item, partial, stop"

  # ---- Codex and Copilot -----------------------------------------------------------------------------------------
  for h in codex copilot; do
    hf=$AP_REF/harness-$h.md
    row=$(grep -E '^\| Use AskUserQuestion' $hf)
    print -r -- $row | grep -qi autopilot || P+="harness-$h.md: the AskUserQuestion row doesn't mention autopilot mode"
    print -r -- $row | grep -qi inbox || P+="harness-$h.md: the AskUserQuestion row doesn't say the inbox replaces the plain question"
    ha=$(ap_aut $hf)
    print -r -- $ha | grep -qiE 'same rules|follows' || P+="harness-$h.md: doesn't say autopilot mode follows the same rules"
    print -r -- $ha | grep -qiE 'every call.{0,40}high-stakes|high-stakes.{0,40}every call' || P+="harness-$h.md: doesn't say every call is high-stakes there"
    print -r -- $ha | grep -qiE 'no advisor' || P+="harness-$h.md: doesn't give 'no advisor' as the reason"
  done
  cpp=$(awk -v RS= '/unattended run on Copilot/' $AP_REF/harness-copilot.md)
  print -r -- $cpp | grep -qi autopilot && print -r -- $cpp | grep -qi 'high-stakes' || P+="harness-copilot.md: the unattended-review rule isn't a high-stakes call in autopilot mode"
  cxp=$(awk -v RS= '/MCP question/' $AP_REF/harness-codex.md)
  print -r -- $cxp | grep -qi autopilot && print -r -- $cxp | grep -qi 'high-stakes' || P+="harness-codex.md: the MCP question isn't a high-stakes call in autopilot mode"
  verdict "AUTOPILOT Codex and Copilot: the AskUserQuestion row sends questions to the inbox, every call is high-stakes, Copilot's unattended-review rule and Codex's MCP question are high-stakes calls"

  # ---- AC1: with autopilot off, the lines autopilot overrides still read as before -----------------------------------
  ap_has $AP_SK 'Use AskUserQuestion with the mission that will run as the first option.' "SKILL.md: mission confirmation (step 3) changed"
  ap_has $AP_SK 'When the input fits more than one mission, or none, say so and ask the engineer which one they mean.' "SKILL.md: the detection fallback changed"
  ap_has $AP_SK 'A run is finished when its `state.md` has a `result:` line' "SKILL.md: the finished-run rule changed"
  ap_has $AP_SK 'propose the smallest cut that meets the stop rule, and ask.' "SKILL.md: phase 1 step 2's cut question changed"
  ap_has $AP_SK 'Ask one decision batch: the allow rules, the mode, every question from steps 1–4, and the run'"'"'s ground rules' "SKILL.md: the decision batch (step 5.2) changed"
  ap_has $AP_SK 'have the engineer store the Keychain secrets' "SKILL.md: step 5.1's Keychain secrets changed"
  ap_has $AP_SK 'It starts only once the engineer approves that.' "SKILL.md: the no-security-role-skill ground rule changed"
  ap_has $AP_SK 'If the engineer is around, use AskUserQuestion with your recommendation first. If not, end your update with a `needs input:` line' "SKILL.md: Bubbling questions up changed"
  ap_has $AP_SK 'When a denial is about the outcome rather than the syntax, stop and ask' "SKILL.md: the denial rule changed"
  ap_has $AP_REF/mission-review.md 'Ask with AskUserQuestion: post as `COMMENT` (first option)' "mission-review.md: phase 3 step 3 changed"
  ap_has $AP_REF/mission-review.md 'If the engineer is away, end your update with a `needs input:` line and post nothing.' "mission-review.md: the engineer-away rule changed"
  ap_has $AP_REF/mission-review.md '"event": "COMMENT"' "mission-review.md: review.json's event changed"
  ap_has $AP_REF/mission-review.md "you'll need them again to approve the findings" "mission-review.md: phase 1's closing line changed"
  ap_has $AP_REF/mission-review.md 'only when the engineer says so.' "mission-review.md: the worktree removal rule changed"
  ap_has $AP_REF/mission-pr-feedback.md 'launch nobody until they say they recognise them and to go ahead.' "mission-pr-feedback.md: the agent-config commits stop changed"
  ap_has $AP_REF/harness-claude.md "If they've already left, put it in your next update and carry on." "harness-claude.md: 'When the advisor is off' step 1 changed"
  ap_has $AP_REF/harness-codex.md '| Use AskUserQuestion | Ask a plain question in your reply, with your recommendation first, and wait for the answer' "harness-codex.md: the AskUserQuestion row's plain-question text changed"
  ap_has $AP_REF/harness-copilot.md '| Use AskUserQuestion | Ask a plain question in your reply, with your recommendation first, and wait for the answer' "harness-copilot.md: the AskUserQuestion row's plain-question text changed"
  verdict "AUTOPILOT AC1: with autopilot off, the existing gate lines the brief names still read as before"
}

# ======================================================================================================================
# ROUNDS: review-round.sh caps each unit's review at two rounds (issue #129). `tests/run.sh rounds` runs just these.
# ======================================================================================================================
want rounds && {
  mk rounds-cap
  xrun $CM/review-round.sh $D u1; rc_is 0
  [[ $(<$SC/out) == "round 1 of 2 for u1: full review."* ]] || P+="round 1: $(<$SC/out)"
  xrun $CM/review-round.sh $D u1; rc_is 0
  [[ $(<$SC/out) == "round 2 of 2 for u1, the last:"*"Only HIGH blocks"* ]] || P+="round 2: $(<$SC/out)"
  xrun $CM/review-round.sh $D u1; rc_is 1
  [[ $(<$SC/out) == "CAP u1: 2 review rounds done;"* ]] || P+="round 3: $(<$SC/out)"
  xrun $CM/review-round.sh $D u2; rc_is 0
  [[ $(<$SC/out) == "round 1 of 2 for u2:"* ]] || P+="u2 counts apart from u1: $(<$SC/out)"
  [[ $(<$D/rounds.tsv) == $'u1 1\nu1 2\nu2 1' ]] || P+="rounds.tsv: $(<$D/rounds.tsv | tr '\n' '|')"
  verdict "ROUNDS review-round.sh gives each unit round 1 then round 2, refuses a third with exit 1, and records only rounds started"

  mk rounds-refuse
  xrun $CM/review-round.sh $D 'u1;x'; rc_is 5
  xrun $CM/review-round.sh $SC/no-run u1; rc_is 5
  [[ -e $D/rounds.tsv ]] && P+="a refused call wrote rounds.tsv"
  verdict "ROUNDS review-round.sh refuses a bad unit name or a directory without team.env, and writes nothing"
}

# ======================================================================================================================
# LINT: the checks CI runs on shell files, including the files its shebang search misses.
# ======================================================================================================================
bad=(); sbad=()
# Like CI: zsh -n on zsh scripts and on files with no shebang (team-env.zsh, driver.env), Markdown excepted; shellcheck on bash and sh scripts.
for f in $(find $shared -type f ! -name '*.md' | LC_ALL=C sort) $ROOT/tests/run.sh; do
  first=$(head -1 $f)
  case $first in
    '#!/usr/bin/env bash'*|'#!/bin/bash'*|'#!/bin/sh'*) command -v shellcheck >/dev/null && { shellcheck $f >/dev/null 2>&1 || sbad+=${f#$ROOT/}; } ;;
    '#!'*python*|'#!/usr/bin/env python'*) ;;
    *) zsh -n $f 2>/dev/null || bad+=${f#$ROOT/} ;;
  esac
done
(( $#sbad )) && fail "LINT shellcheck shared scripts" "fails: ${sbad[*]}" || pass "LINT shellcheck shared scripts (bash and sh shebangs)"
(( $#bad )) && fail "LINT zsh -n" "fails: ${(u)bad[*]}" || pass "LINT zsh -n (zsh and shebang-less files, run.sh)"
if command -v shellcheck >/dev/null; then
  shellcheck $ROOT/tests/bin/* >/dev/null 2>&1 && pass "LINT shellcheck tests/bin" || fail "LINT shellcheck tests/bin" "$(shellcheck $ROOT/tests/bin/* 2>&1 | head -8)"
else echo "skip  LINT shellcheck tests/bin (shellcheck not installed)"; fi

echo
echo "$NPASS passed, $NFAIL failed"
(( NFAIL )) && { echo "failed: ${(j:; :)FAILED}"; exit 1; }
exit 0
