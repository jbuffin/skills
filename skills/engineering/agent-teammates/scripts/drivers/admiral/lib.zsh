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
