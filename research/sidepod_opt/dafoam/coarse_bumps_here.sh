#!/bin/bash
# Measured bumps on a coarse state A, 2 lanes x 2 cores, commit + push after each job.
#   dafoam/coarse_bumps_here.sh [results_dir]   (default gate_results_coarse)
#   CFD_DIV_U="bounded Gauss upwind" dafoam/coarse_bumps_here.sh gate_results_coarse_up
#   LANE_A="..." LANE_B="..." SKIP_ZERO=1  choose the bumps; pairs need no zero run (dafoam/pair_judge.py)
# results_dir/base.json must name the state A folder (run_dir_kept). Runs the zero run first.
cd "$(dirname "$0")/.."   # research/sidepod_opt
RES=${1:-gate_results_coarse}
export PATH=/opt/py/bin:$PATH GATE_RES=coarse GATE_RESULTS=$PWD/$RES CFD_DIV_U
commit() { (cd "$(git rev-parse --show-toplevel)" && git add "research/sidepod_opt/$RES" && git commit -q -m "coarse gate ($RES): $1

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019HSvoaxAjmcpDSsbf6r9F3" && for i in 1 2 3 4; do git push -q origin claude/dazzling-ritchie-3q792g && break; sleep $((2**i)); done) || true; }
T=$(basename "$RES")
[ -n "$SKIP_ZERO" ] || [ -f "$GATE_RESULTS/zero.json" ] || { ./gate_run.sh ${T}_zero zero 4; commit "zero run"; }
lane() { for k in "$@"; do [ -f "$GATE_RESULTS/bump_$k.json" ] && continue; ./gate_run.sh ${T}_b_$k bump $k 2; commit "bump $k"; done; }
lane ${LANE_A:-pod_rear pod_front_low pod_front_low_m pod_rear_low pod_rear_low_m null_pod_front} & A=$!
lane ${LANE_B:-pod_rear_m pod_front pod_front_m pod_rear_top pod_rear_top_m} & B=$!
wait $A $B
[ -n "$SKIP_ZERO" ] || { python -W ignore gate.py judge > gate/${T}_judge.log 2>&1; commit "judge (measured)"; }
echo BUMPS_DONE $(date -u)
