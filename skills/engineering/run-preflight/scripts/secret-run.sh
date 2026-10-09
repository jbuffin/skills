#!/bin/zsh
# usage: secret-run.sh <keychain-service> <ENV_VAR> -- <command> [args...]
# Runs <command> with a Keychain secret in one environment variable. The value is never printed;
# the command must not echo it either.
setopt no_xtrace
SVC=$1; VAR=$2; shift 2
[[ $1 == -- ]] && shift
[[ -z $SVC || -z $VAR || $# -eq 0 ]] && { echo "usage: secret-run.sh <service> <ENV_VAR> -- <command...>"; exit 5; }
V=$(security find-generic-password -s "$SVC" -w 2>/dev/null) || { echo "no Keychain item for service $SVC"; exit 3; }
export $VAR="$V"; unset V
exec "$@"
