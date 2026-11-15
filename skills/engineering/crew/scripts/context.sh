#!/bin/zsh
# usage: context.sh    prints fenced, teammate, ship, autopilot and top as key: value lines
(( $# )) && { echo "usage: context.sh"; exit 5; }
top=$(git rev-parse --show-toplevel 2>/dev/null) || top=
ship=no autopilot=no teammate=no fenced=no
[[ -n $ADMIRAL_SHIP ]] && ship=yes
[[ $ADMIRAL_AUTOPILOT == 1 ]] && autopilot=yes
[[ $autopilot == yes && $ship == no ]] && teammate=yes
# -e misses a dangling symlink; -L catches it. No repo fails closed.
if [[ -z $top || -e $top/.admiral/untrusted || -L $top/.admiral/untrusted ]]; then fenced=yes; fi
echo "fenced: $fenced"
echo "teammate: $teammate"
echo "ship: $ship"
echo "autopilot: $autopilot"
echo "top: $top"
