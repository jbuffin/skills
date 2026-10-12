#!/bin/zsh
# usage: tests/run.sh [--record] [name-filter]
# Deterministic checks for the team skills' harness seam (agent-teammates + commodore). Exits 0 only when every check
# passes. No network, no real `claude` or `codex`: tests/bin holds fakes (claude, codex, date, sleep, tmux, cmux, and a
# stat shim on Linux) that go first on PATH, and every script under test runs under `env -i` with an explicit
# environment inside a scratch directory.
#
#   D4  The scripts' behaviour matches goldens in tests/golden, recorded from the reference commit (dfb39c8) with
#       `tests/run.sh --record`. A golden holds the fake claude's argv log (with cwd), stdout, exit code, and the
#       files the scenario left in the team directory. Normalised: only the scratch directory's path (as @SB@) and
#       one `HARNESS=claude` line in team.env (added by team-init; stripped so a golden fits both sides of the change).
#       The clock is the fake date (FAKE_NOW) and file mtimes are set with touch, so nothing else varies.
#       Not compared: stderr.
#   C1  No shared script calls `claude` or reads Claude transcript paths.
#   C3  team-init detects the harness. C4  team-preflight checks HARNESS against the environment.
#   D1  The advisor operation and the `ADVISOR n/a (<harness>)` path. D2  The Claude driver's shape.
#   CODEX  The Codex driver (turn-based): launch, send/retask, status, tail, stop, preflight, the read-only marker, effort
#       plumbing and the driver's shape. Assertion style (no goldens); `tests/run.sh codex` runs just these.
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
trap 'rm -rf $SB' EXIT
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
want retask-ok && { mk retask-ok; reg t1 c51dbe46 1789999000 - $SC/wt; xrun $AT/retasked.sh $D t1; d4 retask-ok; }
want retask-closed && { mk retask-closed; reg t1 c51dbe46 closed - $SC/wt; xrun $AT/retasked.sh $D t1; d4 retask-closed; }
want retask-unregistered && { mk retask-unregistered; xrun $AT/retasked.sh $D ghost; d4 retask-unregistered; }
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
  snd=$(awk '/^#   send /{p=1; print; next} p && /^#   [a-z]/{p=0} p && /^#/{print}' $DE)
  [[ -n $snd ]] || P+="no '#   send' entry in ${DE#$ROOT/}"
  print -r -- $snd | grep -qi 'resum' || P+="the send text doesn't say it resumes the session"
  print -r -- $snd | grep -qi 'exit' || P+="the send text doesn't mention the process having exited"
  verdict "RESEND driver.env send text: gives the session its next job, resuming it if its process exited"
  print -r -- $snd | grep -qiE 'without waiting' || P+="the send text doesn't say it returns without waiting for the turn"
  print -r -- $snd | grep -qiE 'once .*(started|start)' || P+="the send text doesn't say it returns once the job has started"
  verdict "RESEND driver.env send text: returns once the job has started, without waiting for the turn"
  print -r -- $snd | grep -qiE 'non-zero' && print -r -- $snd | grep -qiE "couldn't|could not|cannot|can't" || P+="the send text doesn't say it exits non-zero if it couldn't start the job"
  verdict "RESEND driver.env send text: exits non-zero if it couldn't start the job"
  sed -n 1,3p $DE | grep -q 'retask\.sh' || P+="the header's opening doesn't mention retask.sh reading the SEND= line"
  verdict "RESEND driver.env header opening says retask.sh reads the SEND= line"
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
# C1: nothing outside drivers/claude calls claude or reads its transcripts.
# ======================================================================================================================
shared=( $ROOT/skills/engineering/agent-teammates/scripts $ROOT/skills/engineering/commodore/scripts )
shared_code() {  # shared_code <egrep-pattern>: matching non-comment lines in shared scripts, as file:line:text
  local f
  find $shared \( -path '*/drivers/claude' -o -path '*/drivers/codex' \) -prune -o -type f -print | LC_ALL=C sort | while read -r f; do
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

  for h in copilot; do
    sc c3-$h; xrun HARNESS=$h $CM/team-init.sh run1 $SC/repo
    if [[ $RC == 7 && ! -e $SC/teams/run1 && $(cat $SC/out $SC/err) == *"$h: not supported yet"* ]]; then pass "C3 HARNESS=$h: not supported yet, exit 7"
    else fail "C3 HARNESS=$h: not supported yet, exit 7" "exit $RC (want 7); run dir exists: $([[ -e $SC/teams/run1 ]] && echo yes || echo no) (want no); output: $(cat $SC/out $SC/err | head -c 300 | tr '\n' ' ')"; fi
  done
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
  undoc=(); for op in launch status tail stop advisor-probe preflight; do grep -E '^#' $DRV/driver.env 2>/dev/null | grep -q -- "$op" || undoc+=$op; done
  (( $#undoc )) && fail "D2 driver.env header documents every operation" "no header comment mentions: ${undoc[*]}" || pass "D2 driver.env header documents every operation"
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
    [[ $d == *[Hh]arness* && $d == *"Claude Code"* ]] && pass "C6 $s description says harness-aware, Claude Code supported" || fail "C6 $s description says harness-aware, Claude Code supported" "description lacks 'harness' or 'Claude Code': ${d:0:160}"
  done
  d=$(sed -n 's/^description: //p' $ATD/SKILL.md | head -1)
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
  [[ $L == *" [-o] [$D/codex-"*".out]"* ]] || P+="argv lacks -o <team>/codex-<name>.<n>.out (a path no sandbox can write)"; A_no $D/reports/t1.md; A_no --add-dir; [[ $L != *network_access* ]] || P+="argv has network_access"; A_safe
}
A_rw() {  # A_rw launch|resume: the writer flags
  if [[ $1 == launch ]]; then A_pair -s workspace-write; A_pair --add-dir $D/reports
  else A_cfg 'sandbox_mode=workspace-write' 'sandbox_mode="workspace-write"'; A_cfg "sandbox_workspace_write.writable_roots=[\"$D/reports\"]" "sandbox_workspace_write.writable_roots=['$D/reports']"; A_no -s; A_no -C; A_no --add-dir; fi
  A_cfg sandbox_workspace_write.network_access=true; A_no -o; A_safe
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
RULES_ALL=( 'prefix_rule(pattern=["gh", "pr", "view"], decision="allow")' 'prefix_rule(pattern=["gh", "pr", "diff"], decision="allow")'
            'prefix_rule(pattern=["gh", "issue", "view"], decision="allow")' 'prefix_rule(pattern=["git", "add"], decision="allow")'
            'prefix_rule(pattern=["git", "commit"], decision="allow")' )
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

  cxp codex-pf-missing; print -rl -- ${RULES_ALL:#*diff*} > $SC/codex-home/rules/default.rules; cxp_run
  want_line='prefix_rule(pattern=["gh", "pr", "diff"], decision="allow")'
  [[ $RC == 1 ]] || P+="exit $RC (want 1)"
  [[ -n $(grep '^FAIL' $SC/out | grep -F -- $want_line) ]] || P+="no FAIL line with $want_line; FAIL lines: $(grep '^FAIL' $SC/out | head -3 | tr '\n' '|')"
  [[ $(cxp_bad | grep -c prefix_rule) == 1 ]] || P+="want exactly one rule line named; got: $(cxp_bad | tr '\n' '|')"
  verdict "CODEX AC2 preflight with gh pr diff missing: FAIL naming that exact prefix_rule line, exit 1"

  cxp codex-pf-norules; cxp_run
  for r in $RULES_ALL; do [[ -n $(grep '^FAIL' $SC/out | grep -F -- $r) ]] || P+="no FAIL naming $r"; done
  grep -qi 'push' $SC/out && P+="the output mentions push: $(grep -i push $SC/out | head -2 | tr '\n' '|')"
  verdict "CODEX AC2 preflight without a rules file: a FAIL for each of the five rules, never suggests git push"

  cxp codex-pf-broad; print -rl -- 'prefix_rule(pattern=["gh"], decision="allow")' $RULES_ALL[4,5] > $SC/codex-home/rules/default.rules; cxp_run
  grep '^WARN' $SC/out | grep -qi 'broader' || P+="no WARN saying the gh rule is broader than needed: $(cxp_bad | tr '\n' '|')"
  [[ -z $(grep '^FAIL' $SC/out | grep -E 'prefix_rule|codex') ]] || P+="FAIL lines although a broad gh rule covers them: $(grep '^FAIL' $SC/out | grep -E 'prefix_rule|codex' | tr '\n' '|')"
  verdict "CODEX AC2 preflight with a blanket gh rule: counts as present, WARN that it's broader than needed"

  cxp codex-pf-longer; print -rl -- $RULES_ALL[1,3] 'prefix_rule(pattern=["git", "add", "-A"], decision="allow")' $RULES_ALL[5] > $SC/codex-home/rules/default.rules; cxp_run
  [[ -n $(grep '^FAIL' $SC/out | grep -F -- 'prefix_rule(pattern=["git", "add"], decision="allow")') ]] || P+="a longer git add -A rule was taken to cover git add; FAIL lines: $(grep '^FAIL' $SC/out | head -3 | tr '\n' '|')"
  verdict "CODEX AC2 preflight: a longer rule (git add -A) doesn't cover git add"

  cxp codex-pf-alternatives; print -rl -- 'prefix_rule(pattern=["gh", "pr", ["view", "diff"]], decision="allow")' $RULES_ALL[3,5] > $SC/codex-home/rules/default.rules; cxp_run
  [[ -z $(cxp_bad) ]] || P+="FAIL/WARN with alternatives covering view and diff: $(cxp_bad | tr '\n' '|')"
  grep -q Traceback $SC/out $SC/err && P+="a traceback on an alternatives list"
  grep -qE '^OK +codex' $SC/out || P+="no OK line about codex besides the advisor one"
  verdict "CODEX AC2 preflight: a pattern element that lists alternatives covers each one, no crash"

  cxp codex-pf-two-files; print -rl -- $RULES_ALL[4,5] > $SC/codex-home/rules/default.rules; print -rl -- $RULES_ALL[1,3] > $SC/codex-home/rules/team.rules; cxp_run
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

  cxp codex-pf-decision-first; print -rl -- 'prefix_rule(decision="forbidden", pattern=["gh", "pr", "view"])' $RULES_ALL[2,5] > $SC/codex-home/rules/default.rules; cxp_run
  [[ $RC == 1 && -n $(grep '^FAIL' $SC/out | grep -i forbid | grep 'view') ]] || P+="a forbidden rule written decision-first counted as allow: exit $RC; $(grep -E '^(FAIL|WARN)' $SC/out | head -3 | tr '\n' '|')"
  verdict "CODEX AC2 preflight: a forbidden rule with decision= before pattern= is a FAIL"

  cxp codex-pf-forbid-broad; print -rl -- $RULES_ALL 'prefix_rule(pattern=["git"], decision="forbidden")' > $SC/codex-home/rules/default.rules; cxp_run
  [[ $RC == 1 && -n $(grep '^FAIL' $SC/out | grep -i forbid | grep 'git add') && -n $(grep '^FAIL' $SC/out | grep -i forbid | grep 'git commit') ]] || P+="a broader forbidden rule didn't beat the exact allow rules: exit $RC; $(grep -E '^(FAIL|WARN)' $SC/out | head -3 | tr '\n' '|')"
  verdict "CODEX AC2 preflight: a broader forbidden rule wins over an exact allow rule"

  cxp codex-pf-prompt; print -rl -- 'prefix_rule(pattern=["gh", "pr", "view"], decision="prompt")' $RULES_ALL[2,5] > $SC/codex-home/rules/default.rules; cxp_run
  [[ $RC == 1 && -n $(grep '^FAIL' $SC/out | grep 'gh pr view') ]] || P+="a prompt rule counted as present: exit $RC"
  verdict "CODEX AC2 preflight: a rule that prompts isn't an allow"

  cxp codex-pf-justification; print -rl -- 'prefix_rule(pattern=["gh", "pr", "view"], decision="allow", justification="never prompt, a # here is no comment")' $RULES_ALL[2,5] > $SC/codex-home/rules/default.rules; cxp_run
  [[ -z $(cxp_bad) && $RC == 0 ]] || P+="an allow rule whose justification says 'prompt' was dropped: exit $RC; $(cxp_bad | tr '\n' '|')"
  verdict "CODEX AC2 preflight: an allow rule with 'prompt' in its justification still counts"

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
  grep -qE '^#.*TEAMMATE_EFFORT' $DRV/driver.env && pass "CODEX D2 the Claude driver.env documents TEAMMATE_EFFORT as an optional input" || fail "CODEX D2 the Claude driver.env documents TEAMMATE_EFFORT as an optional input" "no comment line in ${DRV#$ROOT/}/driver.env mentions TEAMMATE_EFFORT"
}

# ======================================================================================================================
# LINT: the checks CI runs on shell files, including the files its shebang search misses.
# ======================================================================================================================
bad=(); sbad=()
# Like CI: zsh -n on zsh scripts and on files with no shebang (team-env.zsh, driver.env); shellcheck on bash and sh scripts.
for f in $(find $shared -type f | LC_ALL=C sort) $ROOT/tests/run.sh; do
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
