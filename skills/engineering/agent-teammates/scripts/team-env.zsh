# Sourced by the agent-teammates scripts, with D set to the team directory.
# Loads <team-dir>/team.env if present, then fills defaults.
#   MODEL            teammate model (default sonnet), for launches without --model or --role
#   MODEL_<ROLE>     model for launches with --role <role> (the role uppercased, "-" as "_"); no default: unset or empty refuses the launch
#   REQUIRE_ROLE     1: a launch needs --role or --model; no default
#   PERMISSION_MODE  teammate permission mode (default auto); same class as the coordinator, or messages are held
#   VIEWER           none | cmux | tmux; optional panes that attach to a teammate; closing one never stops it
#   REPO             a checkout teammates must never start in
#   STALL_MIN        minutes a working teammate may go without writing to its transcript before STALL (default 10)
[[ -f $D/team.env ]] && source $D/team.env
: ${MODEL:=sonnet}; : ${STALL_MIN:=10}; : ${PERMISSION_MODE:=auto}; : ${VIEWER:=none}
: ${CMUX:=${CMUX_BUNDLED_CLI_PATH:-/Applications/cmux.app/Contents/Resources/bin/cmux}}
REG=$D/teammates.tsv     # name id tasked-epoch|closed viewer-ref|- workdir
mkdir -p $D/reports; touch $REG
# A session's transcript; its mtime moves with every message and tool call, so it doubles as a progress signal.
transcript_of() { print -r -- ${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects/*/$1*.jsonl(Nom[1]); }
reg_field() { awk -v n=$1 -v f=$2 '$1==n {v=$f} END {print v}' $REG; }   # last row for a name wins
# Names and labels become file names and registry fields: letters, digits, '.', '_' and '-' only.
valid_name() { [[ $1 =~ '^[A-Za-z0-9._-]+$' && $1 != .* ]] || { echo "invalid name '$1': use letters, digits, '.', '_' and '-', not starting with '.'"; exit 5; }; }
