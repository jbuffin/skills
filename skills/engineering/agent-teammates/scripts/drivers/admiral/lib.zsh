# Sourced by the admiral driver's operations; all but harness_driver need team-env.zsh sourced first.
# Under ADMIRAL_AUTOPILOT=1 Admiral refuses --ship unless the caller's environment has ADMIRAL_SHIP.
SHIP_ARG=()
[[ -n $ADMIRAL_SHIP && ( -n $ADMIRAL_SHIP_ENV || $ADMIRAL_AUTOPILOT != 1 ) ]] && SHIP_ARG=(--ship $ADMIRAL_SHIP)
# Admiral has no version flag and 0.3.0 lacks --arg, so read the undocumented usage text; without a `crew launch` line,
# give the benefit of the doubt.
crew_takes_arg() {
  local usage
  usage=$(admiral crew 2>&1)
  [[ $usage != *"crew launch"* || $usage == *"--arg"* ]]
}
OLD_ADMIRAL="admiral crew launch has no --arg: Admiral newer than 0.3.0 is needed (main at 992f678 or later)"
NAME_RULE="lowercase letters and digits, with '-' inside (not first)"
DRIVERS=${0:A:h:h}
# harness_driver <team-dir>: reads team.env alone, because team-env.zsh creates files in the run dir
harness_driver() {
  local h
  h=$(unset HARNESS; [[ -f $1/team.env ]] && source $1/team.env; print -r -- ${HARNESS:-claude})
  # the same rules as team-env.zsh
  [[ $h =~ '^[a-z0-9-]+$' ]] || { echo "invalid HARNESS '$h' in $1/team.env: use lowercase letters, digits and '-'" >&2; return 5; }
  [[ $h == admiral ]] && { echo "admiral is a host driver, not a harness: set HARNESS to the harness and ADMIRAL_SHIP to the ship" >&2; return 5; }
  print -r -- $DRIVERS/$h
}
# delegated <id> [listing]: 0 for a headless teammate launch handed to the harness driver. The boat-listing check is the only
# defence against a Copilot writer naming a live boat in the team dir to steer stop or send; don't drop it as redundant.
delegated() {
  [[ -f $D/admiral-delegated ]] && grep -qxF -- $1 $D/admiral-delegated || return 1
  awk -v i=$1 '$2 == i {f = 1} END {exit !f}' $REG || return 1
  local listing=$2
  [[ -n $listing ]] || listing=$(admiral crew list --json $SHIP_ARG 2>/dev/null) || return 1
  print -r -- $listing | jq -e 'type == "array"' >/dev/null 2>&1 || return 1
  [[ -z $(print -r -- $listing | jq -r --arg n $1 '.[] | select(.name == $n) | .name' 2>/dev/null) ]]
}
# delegate_if <op> <id> <args...>: execs the harness driver's <op> for a delegated teammate, else returns 1
delegate_if() {
  local op=$1 id=$2; shift 2
  delegated $id || return 1
  exec $HARNESS_DRIVER/$op "$@"
}
