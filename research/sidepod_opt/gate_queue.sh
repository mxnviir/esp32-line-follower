#!/bin/bash
# The whole adjoint accuracy test, unattended. Two lanes x 2 cores after the base solve.
# Commits the small result files (gate_results/) after every job.
cd "$(dirname "$0")"
REPO=$(git rev-parse --show-toplevel)
commit() {   # $1 message
  (cd "$REPO" && git add research/sidepod_opt/gate_results && git commit -q -m "adjoint gate: $1

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019HSvoZEkpXwbb9LF44Vpfg" && \
   for i in 1 2 3 4; do git push -q origin HEAD 2>/dev/null && break; sleep $((2**i)); done) || true
}
# 1. wait for the base solve (started separately), then keep its run folder as state A
while ! grep -q "^EXIT" gate/job_base.log 2>/dev/null; do sleep 60; done
python - <<'PY'
import json, shutil, glob
from pathlib import Path
R = Path("gate_results"); G = Path("gate")
old = Path("gate/results/base.json")
b = json.loads(old.read_text()) if old.exists() else json.loads((R / "base.json").read_text())
runs = sorted(glob.glob("../../part2-simulation/cfd_case_template/runs/run_2750_*"))
if runs and not (G / "refA").exists():
    shutil.copytree(runs[-1], G / "refA", ignore=shutil.ignore_patterns("processor*"))
b["run_dir_kept"] = str((G / "refA").resolve())
(R / "base.json").write_text(json.dumps(b, indent=1))
print("state A:", b["run_dir_kept"], "D20 half", b.get("D20_half_N"), "converged", b.get("converged"))
PY
commit "base solve of the original (state A)"
# 2. zero run on the morph path, then one bump to confirm the morph path holds
./gate_run.sh zero zero 4;            commit "zero run (original on the morph path)"
./gate_run.sh b_pod_rear bump pod_rear 4; commit "bump pod_rear"
# 3. two lanes: adjoint + bumps
( ./gate_run.sh adjoint adjoint 2; commit "ESI adjoint on the original"
  for k in nose_side pod_front_low pod_rear_top; do ./gate_run.sh b_$k bump $k 2; commit "bump $k"; done ) &
( for k in nose_top pod_front pod_rear_low tail_side; do ./gate_run.sh b_$k bump $k 2; commit "bump $k"; done ) &
wait
python -W ignore gate.py judge > gate/job_judge.log 2>&1; commit "judge: adjoint vs measured"
echo QUEUE_DONE $(date -u) >> gate/job_judge.log
