#!/bin/bash
# The DAFoam accuracy test, end to end, on Part 2's COARSE mesh (about 100 k cells), so DAFoam's
# adjoint fits a 16 GB machine. Every number is self-consistent: state A, the zero run, the measured
# bumps and the DAFoam gradient all come from this coarse state A on this machine.
#   nohup dafoam/coarse_test.sh > gate/coarse_test.log 2>&1 &
# Results: gate_results_coarse/ (base, zero, bump_*.json, judge.json, dafoam_judge.json, dafoam_sens.*)
set -uo pipefail
cd "$(dirname "$0")/.."                                       # research/sidepod_opt
export GATE_RES=coarse GATE_RESULTS=$PWD/gate_results_coarse
mkdir -p "$GATE_RESULTS"; cp gate_results/bumps.json "$GATE_RESULTS/"
step() { echo "== $* $(date -u +%T)"; }
run() { ./gate_run.sh "coarse_$1" "${@:2}"; tail -1 "gate/job_coarse_$1.log"; }

[ -f "$GATE_RESULTS/base.json" ] || { step "state A (coarse, 2000 it)"; run base base 4; }
[ -f "$GATE_RESULTS/zero.json" ] || { step "zero run"; run zero zero 4; }
# +/- pairs at two sidepod sites and along the ESI gradient shape, plus a null bump
BUMPS="pod_rear pod_rear_m pod_front_low pod_front_low_m pod_front pod_front_m grad_p15 grad_m15 null_pod_front"
lane() { for k in "$@"; do [ -f "$GATE_RESULTS/bump_$k.json" ] || run "b_$k" bump "$k" 2; done; }
step "bumps"
set -- $BUMPS
lane "${@:1:5}" & L1=$!
lane "${@:6}" & L2=$!
wait $L1 $L2
step "judge (measured)"; python -W ignore gate.py judge > gate/coarse_judge.log 2>&1; tail -3 gate/coarse_judge.log

step "DAFoam case from coarse state A"
python dafoam/make_case.py --src gate/refA_coarse --out gate/dafoam_coarseA --iters 300 | tail -1
step "DAFoam primal + adjoint"
DAF_ADJ=Krylov DAF_PC_FILL=${DAF_PC_FILL:-0} DAF_PC_LEVEL=${DAF_PC_LEVEL:-1} DAF_GMRES_ITERS=${DAF_GMRES_ITERS:-2000} \
  DAF_GMRES_RESTART=${DAF_GMRES_RESTART:-200} dafoam/run_docker.sh gate/dafoam_coarseA 4 > gate/dafoam_coarseA.out 2>&1
grep -E "DAFOAM|Killed" gate/dafoam_coarseA.out
cp gate/dafoam_coarseA/dafoam_sens.npz gate/dafoam_coarseA/dafoam_sens.json "$GATE_RESULTS/" 2>/dev/null
step "DAFoam judge"
python -W ignore dafoam/judge.py "$GATE_RESULTS/dafoam_sens.npz" --tag dafoam
step "COARSE_TEST_DONE"
