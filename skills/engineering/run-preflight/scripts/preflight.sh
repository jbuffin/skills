#!/bin/zsh
# usage: preflight.sh <dir-or-env-file>
# Static pre-flight checks for an unattended run. Reads settings from <dir>/team.env, <dir>/preflight.env, or the
# env file given. Prints OK / WARN / FAIL per check; exits 1 if any FAIL. The live checks (each gated action
# performed once, as the run's agents will perform it) are the probe's job (see SKILL.md).
#
# Settings (all optional; set what the run needs):
#   REQUIRED_TOOLS  space-separated commands that must be on PATH (default: git)
#   REPO            the repository; BASE_BRANCH its base; BRANCH_PREFIX the run's branch prefix
#   MODE            stack: CI must run on PRs based on BRANCH_PREFIX branches; anything else: on PRs based on BASE_BRANCH
#   CI_WORKFLOW     workflow file or name; checked to run on PRs based on BRANCH_PREFIX branches
#   TARGET_URL      a URL that must answer
#   SECRETS         Keychain service names that must exist (never the values)
#   SCAN_DIR        a directory to scan for plaintext secrets (defaults to the settings dir)
A=${1:A}
if [[ -d $A ]]; then
  for f in $A/team.env $A/preflight.env; do [[ -f $f ]] && { source $f; break; }; done; : ${SCAN_DIR:=$A}
elif [[ -f $A ]]; then source $A; : ${SCAN_DIR:=${A:h}}
else sed -n 2,14p $0; exit 5; fi
REPO=${REPO:-$WORKTREE}
fail=0
ok()   { echo "OK    $*"; }
warn() { echo "WARN  $*"; }
bad()  { echo "FAIL  $*"; fail=1; }

for t in ${=${REQUIRED_TOOLS:-git}}; do command -v $t >/dev/null && ok "$t found" || bad "$t not on PATH"; done
if [[ " $REQUIRED_TOOLS " == *" gh "* ]]; then
  gh auth status >/dev/null 2>&1 && ok "gh authenticated" || bad "gh not authenticated (gh auth login)"
fi
if [[ -n $REPO ]]; then
  [[ -d $REPO ]] && ok "repository $REPO" || bad "repository $REPO missing"
  if [[ -d $REPO ]]; then
    [[ -n $(git -C $REPO config user.email) ]] && ok "git identity set" || bad "git user.email not set"
    if [[ -n $BASE_BRANCH ]]; then
      git -C $REPO rev-parse --verify -q origin/$BASE_BRANCH >/dev/null && ok "base origin/$BASE_BRANCH exists" || bad "base origin/$BASE_BRANCH not found (git fetch?)"
    fi
  fi
fi
if [[ -n $CI_WORKFLOW && -n $REPO && -d $REPO/.github/workflows ]]; then
  # compare names as literal strings: a name like "CI (iOS)" isn't a regex
  wf=$(awk -v n="$CI_WORKFLOW" 'FNR==1 {found=0} /^name:/ && !found {v=$0; sub(/^name:[[:space:]]*/, "", v); sub(/[[:space:]]*$/, "", v); gsub(/^["\047]|["\047]$/, "", v); found=1; if (v==n) {print FILENAME; exit}}' $REPO/.github/workflows/*.y*ml(N) 2>/dev/null)
  [[ -z $wf && -f $REPO/.github/workflows/$CI_WORKFLOW ]] && wf=$REPO/.github/workflows/$CI_WORKFLOW
  [[ -z $wf && -f $REPO/.github/workflows/$CI_WORKFLOW.yml ]] && wf=$REPO/.github/workflows/$CI_WORKFLOW.yml
  if [[ -z $wf ]]; then warn "CI workflow $CI_WORKFLOW not found in the repo (fine if the run adds it)"
  elif [[ -n $BASE_BRANCH || ( $MODE == stack && -n $BRANCH_PREFIX ) ]]; then
    # Stacked PRs target the branch below them, so a filter naming only the base skips every PR above the first.
    if [[ $MODE == stack && -n $BRANCH_PREFIX ]]; then base=${BRANCH_PREFIX}example; on="the run's branches"
    else base=$BASE_BRANCH; on=$BASE_BRANCH; fi
    msg=$(python3 ${0:A:h}/ci-branch-check.py $wf $base 2>&1)
    # match the verdict too: a Python traceback also exits 1
    case $?:$msg in
      0:*) ok "CI ${wf:t}: $msg" ;;
      "1:NOT covered"*) bad "CI ${wf:t}: $msg; PRs based on $on would get no CI; fix the triggers first" ;;
      "2:no pull_request trigger"*) warn "CI ${wf:t}: $msg; check that its push trigger covers the run's branches" ;;
      *) bad "CI ${wf:t}: the branch check itself failed, so CI coverage is unknown: ${${(f)msg}[-1]}" ;;
    esac
  else ok "CI workflow ${wf:t} present"; fi
fi
if [[ -n $TARGET_URL ]]; then
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$TARGET_URL")
  [[ $code == 2* || $code == 3* || $code == 401 || $code == 403 ]] && ok "target $TARGET_URL reachable (HTTP $code)" || bad "target $TARGET_URL not reachable (HTTP $code)"
fi
for s in ${=SECRETS}; do
  security find-generic-password -s "$s" >/dev/null 2>&1 && ok "Keychain item $s present" \
    || bad "Keychain item $s missing; the engineer runs, in their own terminal: security add-generic-password -U -s $s -a <account> -w"
done
for f in $SCAN_DIR/*.env(N); do
  [[ ${f:t} == team.env || ${f:t} == preflight.env || ${f:A} == $A ]] && continue
  bad "plaintext env file ${f:t} in $SCAN_DIR; move its secrets to the Keychain and delete it"
done
grep -rIl -E '(password|passwd|secret|token)[[:space:]]*[=:][[:space:]]*[^[:space:]<$]{6,}' $SCAN_DIR --include='*.md' --include='*.env' --include='*.txt' 2>/dev/null | while read -r f; do
  warn "possible secret literal in ${f#$SCAN_DIR/}; check it"
done
exit $fail
