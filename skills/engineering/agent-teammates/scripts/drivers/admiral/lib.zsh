# Sourced by the admiral driver's operations. SHIP_ARG and the checks below need team-env.zsh sourced first; harness_driver doesn't.
# --ship for every `crew` call: the ship team-env.zsh resolved. Under ADMIRAL_AUTOPILOT=1 Admiral refuses --ship when the
# caller's environment has no ADMIRAL_SHIP (cli.md), so it is left out there.
SHIP_ARG=()
[[ -n $ADMIRAL_SHIP && ( -n $ADMIRAL_SHIP_ENV || $ADMIRAL_AUTOPILOT != 1 ) ]] && SHIP_ARG=(--ship $ADMIRAL_SHIP)
# Does the installed `crew launch` take --arg? Admiral has no version flag for it and v0.3.0 lacks --arg, so this reads the
# usage text `admiral crew` prints with no arguments (stderr, exit 2). That text is undocumented: when it doesn't show a
# `crew launch` line at all, give the benefit of the doubt.
crew_takes_arg() {
  local usage
  usage=$(admiral crew 2>&1)
  [[ $usage != *"crew launch"* || $usage == *"--arg"* ]]
}
OLD_ADMIRAL="admiral crew launch has no --arg: Admiral newer than 0.3.0 is needed (main at 992f678 or later)"
NAME_RULE="lowercase letters and digits, with '-' inside (not first)"
DRIVERS=${0:A:h:h}
# harness_driver <team-dir>: the run harness's driver directory. Reads team.env alone, without team-env.zsh, which creates
# files in the run dir; has-skill and list-skills write nothing and advisor-probe cleans up after itself.
harness_driver() {
  local h
  h=$(unset HARNESS; [[ -f $1/team.env ]] && source $1/team.env; print -r -- ${HARNESS:-claude})
  # the same rules as team-env.zsh
  [[ $h =~ '^[a-z0-9-]+$' ]] || { echo "invalid HARNESS '$h' in $1/team.env: use lowercase letters, digits and '-'" >&2; return 5; }
  [[ $h == admiral ]] && { echo "admiral is a host driver, not a harness: set HARNESS to the harness and ADMIRAL_SHIP to the ship" >&2; return 5; }
  print -r -- $DRIVERS/$h
}
# delegated <id> [listing]: 0 when <id> is a read-only Codex/Copilot teammate that launch handed to the harness driver
# (headless, so no crew boat). Needs team-env.zsh sourced. The id must be in <team>/admiral-delegated, have a registry row,
# and not be an open crew boat's name in `crew list --json` (pass the listing when the caller already holds one). The listing
# check is there because a Copilot writer can write the team dir (--add-dir <team-dir>): it could put a live boat's name in the
# file and steer `stop` or `send` away from that boat. It is the only defence: the registry-row check adds nothing against such
# a writer, which can append to teammates.tsv as easily as to the file, so don't drop the listing check as redundant. A listing
# that fails or isn't a JSON array counts as not delegated.
delegated() {
  [[ -f $D/admiral-delegated ]] && grep -qxF -- $1 $D/admiral-delegated || return 1
  awk -v i=$1 '$2 == i {f = 1} END {exit !f}' $REG || return 1
  local listing=$2
  [[ -n $listing ]] || listing=$(admiral crew list --json $SHIP_ARG 2>/dev/null) || return 1
  print -r -- $listing | jq -e 'type == "array"' >/dev/null 2>&1 || return 1
  [[ -z $(print -r -- $listing | jq -r --arg n $1 '.[] | select(.name == $n) | .name' 2>/dev/null) ]]
}
# delegate_if <op> <id> <args...>: when <id> is a delegated teammate, runs the harness driver's <op> with <args> (and doesn't
# return); otherwise returns 1 and the caller takes the crew-boat path.
delegate_if() {
  local op=$1 id=$2; shift 2
  delegated $id || return 1
  exec $HARNESS_DRIVER/$op "$@"
}
