#!/bin/zsh
# usage: tests/run.sh [--record] [name-filter]
# Deterministic checks for the team skills' harness seam (agent-teammates + commodore). Exits 0 only when every check
# passes. No network, no real `claude`: tests/bin holds fakes (claude, date, sleep, tmux, cmux, and a stat shim on
# Linux) that go first on PATH, and every script under test runs under `env -i` with an explicit environment inside a
# scratch directory.
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
# C1: nothing outside drivers/claude calls claude or reads its transcripts.
# ======================================================================================================================
shared=( $ROOT/skills/engineering/agent-teammates/scripts $ROOT/skills/engineering/commodore/scripts )
shared_code() {  # shared_code <egrep-pattern>: matching non-comment lines in shared scripts, as file:line:text
  local f
  find $shared -path '*/drivers/claude' -prune -o -type f -print | LC_ALL=C sort | while read -r f; do
    grep -nE -- "$1" $f | grep -vE '^[0-9]+:[[:space:]]*#' | sed -e 's#== \.claude ||#== DOTCLAUDE ||#' | grep -E -- "$1" | sed "s#^#${f#$ROOT/}:#"
  done
}
hits=$(shared_code '(^|[^-/a-z])claude ')
[[ -z $hits ]] && pass "C1 no shared script calls claude" || fail "C1 no shared script calls claude" "$(print -r -- $hits | wc -l | tr -d ' ') lines, first 6:
$(print -r -- $hits | head -6)"
hits=$(shared_code '\.jsonl|/projects|\.claude\.json')
[[ -z $hits ]] && pass "C1 no shared script reads Claude transcript or config paths" || fail "C1 no shared script reads Claude transcript or config paths" "$(print -r -- $hits | wc -l | tr -d ' ') lines, first 6:
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

  for h in codex copilot; do
    sc c3-$h; xrun HARNESS=$h $CM/team-init.sh run1 $SC/repo
    if [[ $RC == 7 && ! -e $SC/teams/run1 && $(cat $SC/out $SC/err) == *"$h: not supported yet"* ]]; then pass "C3 HARNESS=$h: not supported yet, exit 7"
    else fail "C3 HARNESS=$h: not supported yet, exit 7" "exit $RC (want 7); run dir exists: $([[ -e $SC/teams/run1 ]] && echo yes || echo no) (want no); output: $(cat $SC/out $SC/err | head -c 300 | tr '\n' ' ')"; fi
  done
  sc c3-codex-inside-claude; xrun HARNESS=codex CLAUDECODE=1 $CM/team-init.sh run1 $SC/repo
  if [[ $RC == 7 && ! -e $SC/teams/run1 && $(cat $SC/out $SC/err) == *"codex: not supported yet"* ]]; then pass "C3 HARNESS=codex wins over CLAUDECODE=1"
  else fail "C3 HARNESS=codex wins over CLAUDECODE=1" "exit $RC (want 7); output: $(cat $SC/out $SC/err | head -c 300 | tr '\n' ' ')"; fi
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
  pf_case "C4 HARNESS=codex inside claude fails" c4-codex-in-claude HARNESS=codex CLAUDECODE=1 fail codex
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
