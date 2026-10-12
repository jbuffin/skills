# Sourced by the agent-teammates scripts, with D set to the team directory.
# Loads <team-dir>/team.env if present, then fills defaults.
#   MODEL            teammate model (default sonnet), for launches without --model or --role
#   ADVISOR          built-in advisor model for every teammate (default opus; none turns it off)
#   MODEL_<ROLE>     model for launches with --role <role> (the role uppercased, "-" and "." as "_"); no default: unset or empty refuses the launch
#   REQUIRE_ROLE     1: a launch needs --role or --model; no default
#   PERMISSION_MODE  teammate permission mode (default auto); same class as the coordinator, or messages are held
#   VIEWER           none | cmux | tmux; optional panes that attach to a teammate; closing one never stops it
#   HARNESS          the harness the run was started from (default claude); selects scripts/drivers/<HARNESS>
#   REPO             a checkout teammates must never start in
#   STALL_MIN        minutes a working teammate may go without writing to its transcript before STALL (default 10)
# HARNESS comes from team.env alone, never from the caller's environment.
unset HARNESS
[[ -f $D/team.env ]] && source $D/team.env
: ${MODEL:=sonnet}; : ${ADVISOR:=opus}; : ${STALL_MIN:=10}; : ${PERMISSION_MODE:=auto}; : ${VIEWER:=none}
: ${HARNESS:=claude}   # a team.env from before drivers has no HARNESS line; every earlier run was Claude
[[ $HARNESS =~ '^[a-z0-9-]+$' ]] || { echo "invalid HARNESS '$HARNESS' in $D/team.env: use lowercase letters, digits and '-'"; exit 5; }
DRIVER=${0:A:h}/drivers/$HARNESS
: ${CMUX:=${CMUX_BUNDLED_CLI_PATH:-/Applications/cmux.app/Contents/Resources/bin/cmux}}
REG=$D/teammates.tsv     # name id tasked-epoch|closed viewer-ref|- workdir
mkdir -p $D/reports; touch $REG
# Run a driver operation: drv <op> <args>. The driver is chosen by HARNESS in team.env.
# A missing operation returns 9 (no operation can use it as its own exit code) with a message on stderr; the caller decides what to do.
drv() { local op=$1; shift; [[ -x $DRIVER/$op ]] || { echo "harness $HARNESS has no $op operation ($DRIVER)" >&2; return 9; }; $DRIVER/$op "$@"; }
reg_field() { awk -v n=$1 -v f=$2 '$1==n {v=$f} END {print v}' $REG; }   # last row for a name wins
# Names and labels become file names and registry fields: letters, digits, '.', '_' and '-' only.
valid_name() { [[ $1 =~ '^[A-Za-z0-9._-]+$' && $1 != .* ]] || { echo "invalid name '$1': use letters, digits, '.', '_' and '-', not starting with '.'"; exit 5; }; }
# The re-task steps shared by retasked.sh and retask.sh.
# reg_open <name>: refuses (exit 5) an unregistered or closed teammate; sets ID, V (viewer-ref) and W (workdir).
reg_open() {
  ID=$(reg_field $1 2); V=$(reg_field $1 4); W=$(reg_field $1 5)
  [[ -z $ID ]] && { echo "$1 is not registered in $REG"; exit 5; }
  [[ $(reg_field $1 3) == closed ]] && { echo "$1 is closed; launch a new teammate instead"; exit 5; }
  return 0
}
# reg_retask <name>: appends the re-task row (after reg_open), which resets the watchdog clock for the teammate.
reg_retask() {
  printf '%s %s %s %s %s\n' "$1" "$ID" "$(date -u +%s)" "${V:--}" "$W" >> $REG
  echo "$1 re-tasked (session $ID)"
}
