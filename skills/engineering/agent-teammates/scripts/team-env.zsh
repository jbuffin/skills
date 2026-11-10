# Sourced by the agent-teammates scripts, with D set to the team directory.
# Loads <team-dir>/team.env if present, then fills defaults.
#   MODEL            teammate model (default sonnet), for launches without --model or --role
#   ADVISOR          built-in advisor model (default opus; none turns it off). A teammate whose model is in the same family
#                    gets no advisor by design (advisor-family.zsh)
#   MODEL_<ROLE>     model for launches with --role <role> (the role uppercased, "-" and "." as "_"); no default: unset or empty refuses the launch
#   EFFORT_<ROLE>   reasoning effort for launches with --role <role>, on harnesses that take one (Codex, Copilot); no default
#   REQUIRE_ROLE     1: a launch needs --role or --model; no default
#   PERMISSION_MODE  teammate permission mode (default auto); same class as the coordinator, or messages are held
#   VIEWER           none | cmux | tmux; optional panes that attach to a teammate; closing one never stops it
#   HARNESS          the harness the run was started from (default claude); selects scripts/drivers/<HARNESS> for a teammate without a lock
#   HARNESS_<ROLE>   the harness a launch with --role <role> runs on (same mangling as MODEL_<ROLE>); unset or empty means HARNESS
#   TEAMMATE_HARNESS  from the caller's environment only, set by the shared scripts per call: the teammate's harness, which replaces
#                    HARNESS for driver selection. HARNESS keeps the run's value
#   ADMIRAL_SHIP     the Admiral ship the run lives in; non-empty selects the admiral driver (except under ADMIRAL_AUTOPILOT=1 with
#                    a harness other than claude), from the caller's environment or team.env. The caller's environment wins. Pin
#                    it in team.env to keep a run on its ship
#   LAUNCH_WAIT      whole seconds an admiral-driver launch waits for the crew boat's first hook (default 90); LAUNCH_POLL, seconds
#                    between checks (default 2). A boat with no hook by then is probably at a startup prompt (folder trust).
#                    team.env wins over the environment for both
#   REPO             a checkout teammates must never start in
#   STALL_MIN        minutes a working teammate may go without writing to its transcript before STALL (default 10)
# HARNESS comes from team.env alone, never from the caller's environment.
source ${0:A:h}/advisor-family.zsh
unset HARNESS
ADMIRAL_SHIP_ENV=$ADMIRAL_SHIP   # what the caller's environment holds; an autopilot caller may pass --ship only for that
[[ -f $D/team.env ]] && source $D/team.env
[[ -n $ADMIRAL_SHIP_ENV ]] && ADMIRAL_SHIP=$ADMIRAL_SHIP_ENV
: ${MODEL:=sonnet}; : ${ADVISOR:=opus}; : ${STALL_MIN:=10}; : ${PERMISSION_MODE:=auto}; : ${VIEWER:=none}
: ${LAUNCH_WAIT:=90}; : ${LAUNCH_POLL:=2}
: ${HARNESS:=claude}   # a team.env from before drivers has no HARNESS line; every earlier run was Claude
TEAM_SCRIPTS=${0:A:h}
# select_driver <harness> [name [where]]: validates a harness name (lowercase letters, digits and '-', not admiral, and a
# drivers/<harness> folder) and sets TH (the teammate's harness), HARNESS_DRIVER (its own driver) and DRIVER (the driver the
# shared scripts call). On a bad name it prints why, naming <name> (default harness) and <where>, and returns 5; the caller exits.
select_driver() {
  local h=$1 what=${2:-harness} where=$3
  [[ $h =~ '^[a-z0-9-]+$' ]] || { echo "invalid $what '$h'${where:+ in $where}: use lowercase letters, digits and '-'"; return 5; }
  # admiral is the host driver below, never a harness: as one it would call itself.
  [[ $h == admiral ]] && { echo "admiral is a host driver, not a harness: set $what to the harness and ADMIRAL_SHIP to the ship"; return 5; }
  [[ -d $TEAM_SCRIPTS/drivers/$h ]] || { echo "no driver for harness $h ($TEAM_SCRIPTS/drivers/$h)"; return 5; }
  TH=$h
  HARNESS_DRIVER=$TEAM_SCRIPTS/drivers/$h   # the teammate's harness's own driver; the admiral driver defers to it
  DRIVER=$HARNESS_DRIVER
  # Inside an Admiral ship the host driver launches, messages, watches and stops teammates, for every harness. Under autopilot
  # Admiral refuses codex and copilot boats, so those harnesses keep drivers/$h there.
  [[ -n $ADMIRAL_SHIP && ( $h == claude || $ADMIRAL_AUTOPILOT != 1 ) ]] && DRIVER=$TEAM_SCRIPTS/drivers/admiral
  return 0
}
# TEAMMATE_HARNESS, set by the shared scripts per call, replaces HARNESS for driver selection; HARNESS stays the run's.
if [[ -n $TEAMMATE_HARNESS ]]; then select_driver $TEAMMATE_HARNESS TEAMMATE_HARNESS || exit 5
else select_driver $HARNESS HARNESS $D/team.env || exit 5; fi
: ${CMUX:=${CMUX_BUNDLED_CLI_PATH:-/Applications/cmux.app/Contents/Resources/bin/cmux}}
REG=$D/teammates.tsv     # name id tasked-epoch|closed viewer-ref|- workdir harness (a five-column row is the run's harness)
mkdir -p $D/reports; [[ -e $REG ]] || touch $REG 2>/dev/null   # quiet in a writer's sandbox, which can't write here
# Run a driver operation: drv <op> <args>. The driver is the teammate's harness driver (select_driver).
# A missing operation returns 9 (no operation can use it as its own exit code) with a message on stderr; the caller decides what to do.
# The driver sees the teammate's harness as TEAMMATE_HARNESS.
drv() { local op=$1; shift; [[ -x $DRIVER/$op ]] || { echo "harness $TH has no $op operation ($DRIVER)" >&2; return 9; }; TEAMMATE_HARNESS=$TH $DRIVER/$op "$@"; }
reg_field() { awk -v n=$1 -v f=$2 '$1==n {v=$f} END {print v}' $REG; }   # last row for a name wins
# Names and labels become file names and registry fields: letters, digits, '.', '_' and '-' only.
valid_name() { [[ $1 =~ '^[A-Za-z0-9._-]+$' && $1 != .* ]] || { echo "invalid name '$1': use letters, digits, '.', '_' and '-', not starting with '.'"; exit 5; }; }
# reg_harness <name|id>: the harness in the registry's sixth column for that teammate (the run's HARNESS for a five-column row
# or an unregistered name), in H. Column 6 is untrusted (a Copilot writer can write the team dir), so it goes through select_driver:
# returns 0 with TH, DRIVER and HARNESS_DRIVER set (drv passes TH to the driver), else 5 with H set and nothing printed.
reg_harness() {
  H=$(awk -v n=$1 '$1==n {a=$6; hit=1} $2==n {b=$6} END {print hit ? a : b}' $REG)   # a name wins over an id
  HCOL=$H   # the raw column: empty for a five-column row, which later rows keep five columns so it keeps following HARNESS
  : ${H:=$HARNESS}
  select_driver $H >/dev/null || return 5
}
# The re-task steps shared by retasked.sh and retask.sh.
# reg_open <name>: refuses (exit 5) an unregistered or closed teammate or a bad harness in its row; sets ID, V (viewer-ref), W (workdir)
# and H (its harness), and selects its driver (reg_harness).
reg_open() {
  ID=$(reg_field $1 2); V=$(reg_field $1 4); W=$(reg_field $1 5)
  [[ -z $ID ]] && { echo "$1 is not registered in $REG"; exit 5; }
  [[ $(reg_field $1 3) == closed ]] && { echo "$1 is closed; launch a new teammate instead"; exit 5; }
  reg_harness $1 || { echo "bad harness '$H' for $1 in the registry $REG"; exit 5; }
  return 0
}
# reg_retask <name>: appends the re-task row (after reg_open), which resets the watchdog clock for the teammate.
reg_retask() {
  printf '%s %s %s %s %s%s\n' "$1" "$ID" "$(date -u +%s)" "${V:--}" "$W" "${HCOL:+ $HCOL}" >> $REG
  echo "$1 re-tasked (session $ID)"
}
