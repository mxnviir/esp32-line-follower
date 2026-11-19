#!/bin/bash
# Re-run of the lane that failed on the missing results file; then judge once everything is done.
cd "$(dirname "$0")"
REPO=$(git rev-parse --show-toplevel)
commit() { (cd "$REPO" && git add research/sidepod_opt/gate_results && git commit -q -m "adjoint gate: $1

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019HSvoZEkpXwbb9LF44Vpfg" && for i in 1 2 3 4; do git push -q origin HEAD 2>/dev/null && break; sleep $((2**i)); done) || true; }
./gate_run.sh zero zero 2; commit "zero run (original on the morph path)"
for k in pod_rear nose_top pod_front pod_rear_low tail_side; do ./gate_run.sh b_$k bump $k 2; commit "bump $k"; done
while pgrep -f "gate_queue.sh" >/dev/null; do sleep 60; done
python -W ignore gate.py judge > gate/job_judge.log 2>&1; commit "judge: adjoint vs measured"
echo LANE2_DONE $(date -u) >> gate/job_judge.log
