#!/bin/zsh
# usage: teammate-tail.sh <team-dir> <name|id> [n]
# Plain-text view of a teammate's last n (default 8) tool calls and its latest message, read from the session
# transcript. Use it instead of `claude logs`, whose output is raw terminal frames.
D=${1:A}; W=$2; N=${3:-8}
[[ -z $1 || -z $W ]] && { sed -n 2,4p $0; exit 5; }
source ${0:A:h}/team-env.zsh
id=$(reg_field $W 2); [[ -z $id ]] && id=$W
tr=$(transcript_of $id)
[[ -z $tr ]] && { echo "no transcript for $W ($id) under ${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects"; exit 3; }
echo "transcript: $tr  (last write $(( ($(date +%s) - $(stat -f %m $tr)) / 60 )) min ago)"
jq -r 'select(.type=="assistant") | .message.content[]? |
  if .type=="tool_use" then "TOOL  \(.name): \((.input.description // .input.command // .input.file_path // .input.prompt // "") | tostring | gsub("\n";" ") | .[0:160])"
  elif .type=="text" then "SAID  \(.text | gsub("\n";" ") | .[0:240])" else empty end' $tr | tail -$N
