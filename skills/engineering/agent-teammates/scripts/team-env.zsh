# Sourced by the agent-teammates scripts with D set to the team directory: loads <team-dir>/team.env, then fills defaults.
# The variables and their defaults are in the team.env table in SKILL.md.
source ${0:A:h}/advisor-family.zsh
unset HARNESS   # HARNESS comes from team.env alone, never from the caller's environment
ADMIRAL_SHIP_ENV=$ADMIRAL_SHIP   # what the caller's environment holds; an autopilot caller may pass --ship only for that
[[ -f $D/team.env ]] && source $D/team.env
[[ -n $ADMIRAL_SHIP_ENV ]] && ADMIRAL_SHIP=$ADMIRAL_SHIP_ENV
: ${MODEL:=sonnet}; : ${ADVISOR:=opus}; : ${STALL_MIN:=10}; : ${PERMISSION_MODE:=auto}; : ${VIEWER:=none}
: ${LAUNCH_WAIT:=90}; : ${LAUNCH_POLL:=2}
: ${HARNESS:=claude}   # a team.env from before drivers has no HARNESS line; every earlier run was Claude
TEAM_SCRIPTS=${0:A:h}
# select_driver <harness> [name [where]]: sets TH, HARNESS_DRIVER (the harness's own driver) and DRIVER (the one the shared
# scripts call); on a bad name it prints why and returns 5.
select_driver() {
  local h=$1 what=${2:-harness} where=$3
  [[ $h =~ '^[a-z0-9-]+$' ]] || { echo "invalid $what '$h'${where:+ in $where}: use lowercase letters, digits and '-'"; return 5; }
  # as a harness, admiral would call itself
  [[ $h == admiral ]] && { echo "admiral is a host driver, not a harness: set $what to the harness and ADMIRAL_SHIP to the ship"; return 5; }
  [[ -d $TEAM_SCRIPTS/drivers/$h ]] || { echo "no driver for harness $h ($TEAM_SCRIPTS/drivers/$h)"; return 5; }
  TH=$h
  HARNESS_DRIVER=$TEAM_SCRIPTS/drivers/$h   # the teammate's harness's own driver; the admiral driver defers to it
  DRIVER=$HARNESS_DRIVER
  # under autopilot Admiral refuses codex and copilot boats, so those keep their own driver
  [[ -n $ADMIRAL_SHIP && ( $h == claude || $ADMIRAL_AUTOPILOT != 1 ) ]] && DRIVER=$TEAM_SCRIPTS/drivers/admiral
  return 0
}
if [[ -n $TEAMMATE_HARNESS ]]; then select_driver $TEAMMATE_HARNESS TEAMMATE_HARNESS || exit 5
else select_driver $HARNESS HARNESS $D/team.env || exit 5; fi
: ${CMUX:=${CMUX_BUNDLED_CLI_PATH:-/Applications/cmux.app/Contents/Resources/bin/cmux}}
REG=$D/teammates.tsv     # name id tasked-epoch|closed viewer-ref|- workdir harness (a five-column row is the run's harness)
mkdir -p $D/reports; [[ -e $REG ]] || touch $REG 2>/dev/null   # quiet in a writer's sandbox, which can't write here
# drv <op> <args>: a missing operation returns 9, which no operation uses as its own exit code
drv() { local op=$1; shift; [[ -x $DRIVER/$op ]] || { echo "harness $TH has no $op operation ($DRIVER)" >&2; return 9; }; TEAMMATE_HARNESS=$TH $DRIVER/$op "$@"; }
reg_field() { awk -v n=$1 -v f=$2 '$1==n {v=$f} END {print v}' $REG; }   # last row for a name wins
# Names and labels become file names and registry fields: letters, digits, '.', '_' and '-' only.
valid_name() { [[ $1 =~ '^[A-Za-z0-9._-]+$' && $1 != .* ]] || { echo "invalid name '$1': use letters, digits, '.', '_' and '-', not starting with '.'"; exit 5; }; }
# reg_harness <name|id>: the teammate's harness in H, with its driver selected. Column 6 is untrusted (a Copilot writer can
# write the team dir), so it goes through select_driver.
reg_harness() {
  H=$(awk -v n=$1 '$1==n {a=$6; hit=1} $2==n {b=$6} END {print hit ? a : b}' $REG)   # a name wins over an id
  HCOL=$H   # the raw column: empty for a five-column row, which later rows keep five columns so it keeps following HARNESS
  : ${H:=$HARNESS}
  select_driver $H >/dev/null || return 5
}
# reg_open <name>: exits 5 for an unregistered or closed teammate; sets ID, V (viewer-ref), W (workdir) and H, and selects the driver.
reg_open() {
  ID=$(reg_field $1 2); V=$(reg_field $1 4); W=$(reg_field $1 5)
  [[ -z $ID ]] && { echo "$1 is not registered in $REG"; exit 5; }
  [[ $(reg_field $1 3) == closed ]] && { echo "$1 is closed; launch a new teammate instead"; exit 5; }
  reg_harness $1 || { echo "bad harness '$H' for $1 in the registry $REG"; exit 5; }
  return 0
}
# reg_retask <name>: the new row resets the teammate's watchdog clock
reg_retask() {
  printf '%s %s %s %s %s%s\n' "$1" "$ID" "$(date -u +%s)" "${V:--}" "$W" "${HCOL:+ $HCOL}" >> $REG
  echo "$1 re-tasked (session $ID)"
}
