#!/bin/bash
# Lane 1, second half: after pod_front_low, the noise floor, a half-height nose_side (1 mm broke the
# reshaped mesh) and -1 mm partners of the two strongest predicted sites; then judge.
cd "$(dirname "$0")"
REPO=$(git rev-parse --show-toplevel)
commit() { (cd "$REPO" && git add research/sidepod_opt/gate_results && git commit -q -m "adjoint gate: $1

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019HSvoZEkpXwbb9LF44Vpfg" && for i in 1 2 3 4; do git push -q origin HEAD 2>/dev/null && break; sleep $((2**i)); done) || true; }
while pgrep -f "gate.py bump pod_front_low" >/dev/null; do sleep 30; done
commit "bump pod_front_low"
for k in ${LANE1B:-null_pod_front nose_side_h pod_front_m pod_front_low_m}; do ./gate_run.sh b_$k bump $k 2; commit "bump $k"; done
while pgrep -f "gate_lane2.sh" >/dev/null; do sleep 60; done
python -W ignore gate.py judge > gate/job_judge.log 2>&1; commit "judge: adjoint vs measured"
echo LANE1B_DONE $(date -u) >> gate/job_judge.log
