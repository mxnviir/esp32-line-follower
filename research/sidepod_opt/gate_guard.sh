#!/bin/bash
# Kill any bump whose reshaped mesh failed and fell back to a fresh mesh: that run cannot be used
# (fresh-mesh noise >> bump), so it would only waste ~80 min on 2 cores.
RUNS="$(dirname "$0")/../../part2-simulation/cfd_case_template/runs"
while true; do
  for f in "$RUNS"/run_*/MORPH_FALLBACK; do
    [ -f "$f" ] || continue
    d=$(dirname "$f"); pid=$(basename "$d" | cut -d_ -f2)
    if kill -0 "$pid" 2>/dev/null; then
      echo "$(date -u) fallback in $d: killing $pid"; cat "$f"
      pkill -TERM -P "$pid"; for c in $(pgrep -P "$pid"); do pkill -TERM -P "$c"; done; kill "$pid"
    fi
    sleep 5; rm -rf "$d"
  done
  sleep 60
done
