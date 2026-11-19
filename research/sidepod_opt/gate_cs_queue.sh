#!/bin/bash
# Continue the adjoint accuracy test on another machine (a Codespace): its own state A and zero run
# (bump differences are only meaningful on one machine's mesh), then the bumps in $GATE_JOBS on
# $LANES lanes of 2 cores. Results: $GATE_RESULTS (default gate_results_cs/), committed and pushed
# after every job. The adjoint is NOT re-run: judge maps the one in gate_results/ onto this mesh.
#   GATE_JOBS="pod_front_m:pod_front:-1 nose_side_h:nose_side:0.5 pod_front:" ./gate_cs_queue.sh
#   (name:site:mm makes a variant first; "name:" is a standard bump)
cd "$(dirname "$0")"
export GATE_RESULTS=${GATE_RESULTS:-$PWD/gate_results_cs}
LANES=${LANES:-3}; NP_BASE=${NP_BASE:-4}
REPO=$(git rev-parse --show-toplevel)
commit() { (cd "$REPO" && git add "$GATE_RESULTS" && git commit -q -m "adjoint gate (codespace): $1

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019HSvoZEkpXwbb9LF44Vpfg" && for i in 1 2 3 4; do git pull -q --no-rebase --no-edit origin HEAD 2>/dev/null; git push -q origin HEAD 2>/dev/null && break; sleep $((2**i)); done) || true; }
mkdir -p "$GATE_RESULTS"; cp gate_results/bumps.json "$GATE_RESULTS/" 2>/dev/null
[ -f gate/original/car_half.stl ] || python -W ignore - <<'PY'
from pathlib import Path
from geometry import Car
c = Car(); c.export_car_folder(c.body_mesh, Path("gate/original"), "original")
PY
python -W ignore gate.py bumps
names=()
for j in $GATE_JOBS; do
  n=${j%%:*}; rest=${j#*:}
  if [ -n "$rest" ]; then python -W ignore gate.py variant "$n" "${rest%%:*}" "${rest#*:}"; fi
  names+=("$n")
done
[ -f "$GATE_RESULTS/base.json" ] || { ./gate_run.sh base base $NP_BASE; commit "base solve (state A)"; }
[ -f "$GATE_RESULTS/zero.json" ] || { ./gate_run.sh zero zero $NP_BASE; commit "zero run"; }
./gate_guard.sh > gate/guard.out 2>&1 &
GUARD=$!
pids=()
for ((l = 0; l < LANES; l++)); do
  ( for ((i = l; i < ${#names[@]}; i += LANES)); do k=${names[$i]}
      [ -f "$GATE_RESULTS/bump_$k.json" ] && continue
      ./gate_run.sh b_$k bump $k 2; commit "bump $k"; done ) &
  pids+=($!)
done
wait "${pids[@]}"
kill $GUARD
python -W ignore gate.py judge > gate/job_judge.log 2>&1; commit "judge"
echo CS_DONE $(date -u) >> gate/job_judge.log
