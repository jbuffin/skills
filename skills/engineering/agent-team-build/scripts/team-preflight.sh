#!/bin/zsh
# usage: team-preflight.sh <run-dir>
# The team-specific static checks (runtime, mode, gh-stack, worktrees), then the generic ones from the
# run-preflight skill. Prints OK / WARN / FAIL; exits 1 if any FAIL.
[[ -z $1 || ! -f $1/team.env ]] && { sed -n 2,4p $0; exit 5; }
source $1/team.env
fail=0
ok()   { echo "OK    $*"; }
warn() { echo "WARN  $*"; }
bad()  { echo "FAIL  $*"; fail=1; }
REPO=${REPO:-$WORKTREE}

command -v claude >/dev/null && ok "claude found" || bad "claude not on PATH"
claude agents --json >/dev/null 2>&1 && ok "claude background sessions available (claude agents)" \
  || bad "claude agents --json failed; background sessions unavailable; teammates would fall back to in-process subagents"
python3 - "$REPO" "${CLAUDE_CONFIG_DIR:-$HOME/.claude}" <<'PY' && ok "repository is trusted for background sessions" || warn "repository not marked trusted; run \`claude\` once in $REPO and accept the prompt, or launches fail with 'Workspace not trusted'"
import json, os, sys
repo = os.path.realpath(sys.argv[1]); cfgs = [os.path.join(sys.argv[2], ".claude.json"), os.path.expanduser("~/.claude.json")]
for c in cfgs:
    try: projects = json.load(open(c)).get("projects", {})
    except Exception: continue
    for path, v in projects.items():
        if v.get("hasTrustDialogAccepted") and (repo == path or repo.startswith(path.rstrip("/") + "/")): sys.exit(0)
sys.exit(1)
PY
case ${VIEWER:-none} in
  cmux) [[ -x $CMUX && -n $CMUX_WORKSPACE ]] && $CMUX list-panes --workspace $CMUX_WORKSPACE >/dev/null 2>&1 \
          && ok "cmux viewer: workspace $CMUX_WORKSPACE found" || warn "VIEWER=cmux but workspace '$CMUX_WORKSPACE' not found (cmux identify); teammates still run, just without panes" ;;
  tmux) [[ -n $TMUX ]] && ok "tmux viewer: inside tmux" || warn "VIEWER=tmux but this session isn't inside tmux; teammates still run, just without panes" ;;
esac
[[ -z $MODE ]] && warn "MODE not set in team.env (single / stack / independent / pr)"
if [[ $MODE == stack ]]; then
  v=$(gh extension list 2>/dev/null | awk '/gh-stack/ {print $NF}' | tr -d v)
  if [[ -z $v ]]; then bad "gh stack missing (gh extension install github/gh-stack)"
  elif [[ $(printf '%s\n0.2.0\n' $v | sort -V | head -1) == 0.2.0 ]]; then ok "gh-stack $v (shares stack tracking across worktrees)"
  else bad "gh-stack $v keeps stack tracking per worktree; one worktree per unit needs >= 0.2.0 (gh extension upgrade gh-stack)"; fi
  [[ $(git -C $REPO config rerere.enabled) == true ]] && ok "rerere enabled" || warn "git rerere off (git config rerere.enabled true helps stack rebases)"
fi
WT_DIR=${WORKTREES_DIR:-$REPO/.claude/worktrees}
if [[ $WT_DIR == $REPO/* ]]; then
  git -C $REPO check-ignore -q "${WT_DIR#$REPO/}/probe" && ok "worktrees dir is git-ignored" \
    || warn "worktrees dir $WT_DIR is inside the repo but not git-ignored; it will show as untracked in the engineer's checkout"
fi
# git worktree add brings only tracked files. Ignored files the build reads (env files, local config) must be listed.
if [[ -d $REPO ]]; then
  for e in ${=WORKTREE_SETUP}; do
    [[ -e $REPO/${e#*:} ]] && ok "WORKTREE_SETUP ${e} present in the checkout" || bad "WORKTREE_SETUP ${e}: $REPO/${e#*:} missing"
  done
  unlisted=()
  # top-level ignored files, and top-level ignored directories without their trailing slash
  for f in ${(f)"$(git -C $REPO ls-files --others --ignored --exclude-standard --directory 2>/dev/null | sed -n -e '/^[^/]*$/p' -e 's#^\([^/]*\)/$#\1#p')"}; do
    [[ -z $f || $f == .claude || $REPO/$f == $WT_DIR* || " ${WORKTREE_SETUP_SKIP-.DS_Store .vscode .idea coverage} " == *" $f "* ]] && continue
    [[ " ${WORKTREE_SETUP} " == *":$f "* ]] || unlisted+=$f
  done
  (( ${#unlisted} )) && warn "ignored in the checkout, so absent from new worktrees: ${(j:, :)unlisted}. Add each one the build or tests read to WORKTREE_SETUP (copy: or clone:)"
fi
${SKILLS_DIR:-${0:A:h:h:h}}/run-preflight/scripts/preflight.sh $1 || fail=1
exit $fail
