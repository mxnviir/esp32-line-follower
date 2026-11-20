#!/bin/bash
# Measured +/-1 mm bump pairs on coarse state A, 2 lanes x 2 cores, commit + push after each.
cd "$(dirname "$0")/.."
export PATH=/opt/py/bin:$PATH GATE_RES=coarse GATE_RESULTS=$PWD/gate_results_coarse
commit() { (cd "$(git rev-parse --show-toplevel)" && git add research/sidepod_opt/gate_results_coarse && git commit -q -m "coarse gate (here): $1

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019HSvoaxAjmcpDSsbf6r9F3" && for i in 1 2 3 4; do git push -q origin claude/dazzling-ritchie-3q792g && break; sleep $((2**i)); done) || true; }
lane() { for k in "$@"; do [ -f "$GATE_RESULTS/bump_$k.json" ] && continue; ./gate_run.sh b_$k bump $k 2; commit "bump $k"; done; }
lane pod_front_low pod_front_low_m pod_rear_low pod_rear_low_m null_pod_front & A=$!
lane pod_rear_m pod_front pod_rear_top pod_rear_top_m & B=$!
wait $A $B
python -W ignore gate.py judge > gate/coarse_judge.log 2>&1; commit "judge (measured)"
echo BUMPS_DONE $(date -u)
