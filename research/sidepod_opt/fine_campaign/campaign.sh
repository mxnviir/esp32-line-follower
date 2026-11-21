#!/bin/bash
# Fine-mesh campaign (ROUTES.md 2026-11-21 13:00): re-test every conclusion on finer meshes, and test
# whether the adjoint works on them. Resumable: every finished job leaves a JSON and is skipped next time.
#
#   RES=fine     NP=16 JOBS=4 bash fine_campaign/campaign.sh <stage>
#   RES=resolved NP=32 JOBS=2 bash fine_campaign/campaign.sh <stage>
#
# Stages (run in this order; each prints what it decided):
#   cars      rebuild all test cars from code (fine_campaign/make_cars.py)           minutes, 1 core
#   stage0    the team pod alone: cells, y+, peak memory, time per run.              STOP and read it
#   forward   18 runs: 8 designs x 1-3 meshes each (production model, cold start)
#   steady    production state of the original car, then the first-order "steady model" on top of it;
#             PASS/FAIL: does the wake go steady on this mesh? (the adjoint needs it)
#   bumps     6 measured +/-1 mm bumps on the steady state (the gradient check's known answers)
#   adjoint   DAFoam Krylov adjoint on the steady state (refuses if memory looks too small)
#   judge     adjoint vs bumps (same pass marks as the coarse check)
#   bccheck   cheap, any machine: does DAFoam accept the wall-resolved boundary conditions (coarse mesh)?
#   summary   tables + pass marks for everything finished so far -> fine_campaign/SUMMARY_<RES>.md
#
# Environment: RES (fine|resolved|medium|coarse), NP (cores per run), JOBS (runs at once), ITERS (cold
# iterations, default 3000), TIMEOUT (s per OpenFOAM stage, default 172800), OF_BASHRC, PY (python with
# the repo's requirements), PUSH=0 to not commit/push, ONLY="team groove" to run a subset (smoke tests),
# TAG (results folder suffix, for smoke tests), FORCE_ADJOINT=1 to skip the memory refusal.
set -uo pipefail
cd "$(dirname "$0")/.."                                       # research/sidepod_opt
STAGE=${1:?stage}
RES=${RES:-fine}; NP=${NP:-4}; JOBS=${JOBS:-1}; ITERS=${ITERS:-3000}; TIMEOUT=${TIMEOUT:-172800}
PY=${PY:-$(command -v python3)}; OF_BASHRC=${OF_BASHRC:-/usr/lib/openfoam/openfoam2412/etc/bashrc}
TAG=${TAG:-$RES}; OUT=$PWD/gate_results_$TAG; UP=$PWD/gate_results_${TAG}_up; CARS=$PWD/runs/fine_cars
mkdir -p "$OUT" "$UP" gate
set +u; source "$OF_BASHRC" || true; set -u          # OpenFOAM's bashrc reads unset variables
export OF_BASHRC OMPI_ALLOW_RUN_AS_ROOT=1 OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 OMPI_MCA_rmaps_base_oversubscribe=1
LOG=gate/campaign_$TAG.log
say() { echo "$* $(date -u +%F_%T)" | tee -a "$LOG"; }

commit() {   # commit + push the results (never the run folders)
  [ "${PUSH:-1}" = 1 ] || return 0
  ( cd "$(git rev-parse --show-toplevel)" || exit 0
    git add research/sidepod_opt/gate_results_$TAG research/sidepod_opt/gate_results_${TAG}_up 2>/dev/null
    git commit -q -m "fine campaign ($TAG): $1

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019HSvoaxAjmcpDSsbf6r9F3" || exit 0
    BR=$(git rev-parse --abbrev-ref HEAD)
    for i in 1 2 3 4; do git pull -q --no-rebase --no-edit origin "$BR" 2>/dev/null; git push -q origin "$BR" 2>/dev/null && break; sleep $((2 ** i)); done ) || true
}

measure() {  # measure <json> <cmd...>: peak memory (RAM + swap in use, whole machine) and wall time
  local out=$1; shift
  local t0=$SECONDS peak=0 m
  "$@" & local pid=$!
  while kill -0 $pid 2>/dev/null; do
    m=$(awk '/MemTotal/{t=$2}/MemAvailable/{a=$2}/SwapTotal/{st=$2}/SwapFree/{sf=$2}END{print int((t-a+st-sf)/1024)}' /proc/meminfo)
    [ "$m" -gt "$peak" ] && peak=$m; sleep 10
  done
  wait $pid; local rc=$?
  echo "{\"peak_used_MB_whole_machine\": $peak, \"wall_s\": $((SECONDS - t0)), \"rc\": $rc, \"n_proc\": $NP, \"jobs_at_once\": $JOBS, \"host_cores\": $(nproc), \"host_mem_MB\": $(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo)}" > "$out"
  return $rc
}

# design tag -> number of meshes; order = priority
FORWARD="team team_p05 team_m05 groove groove_p05 groove_m05 adjoint8 adjoint8_p05 adjoint8_m05 win3 win3_p05 nopod nopod_p05 blend50 blend50_p05 blend75 blend75_p05 win5"
selected() { local t; for t in $FORWARD; do
  if [ -n "${ONLY:-}" ]; then for o in $ONLY; do [ "$t" = "$o" ] && echo $t; done; else echo $t; fi; done; }

one_forward() {   # one production run of a car on a fresh $RES mesh, cold start
  local t=$1
  [ -f "$OUT/prodcheck_$t.json" ] && return 0
  [ -f "$CARS/$t/car/car_half.stl" ] || { say "MISSING car $t (run the cars stage)"; return 1; }
  say "start $t"
  PRODCHECK_RES=$RES PRODCHECK_RESULTS=$OUT PRODCHECK_ITERS=$ITERS PRODCHECK_TIMEOUT=$TIMEOUT \
    measure "$OUT/resources_$t.json" "$PY" -W ignore prodcheck.py "$CARS/$t/car" "$t" "$NP" cold > "gate/prodcheck_${TAG}_$t.log" 2>&1
  if [ -f "$OUT/prodcheck_$t.json" ]; then say "done $t $("$PY" -c "import json;d=json.load(open('$OUT/prodcheck_$t.json'));print(round(d['D20_half_N']*1e3,2),'mN cells',d.get('n_cells'),'y+max',round(d.get('y_plus_max') or 0,1),'conv',d['converged'])")"; commit "forward $t"
  else say "FAILED $t (gate/prodcheck_${TAG}_$t.log)"; fi
}

run_parallel() {  # run_parallel <fn> <items...> with $JOBS at once
  local fn=$1; shift; local it
  for it in "$@"; do
    while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do wait -n; done
    $fn "$it" &
    sleep 5
  done
  wait
}

case $STAGE in
cars)
  "$PY" -W ignore fine_campaign/make_cars.py "$CARS" 2>&1 | grep -v Warn | tee -a "$LOG" ;;
stage0)
  ONLY=team one_forward team
  "$PY" fine_campaign/summarize.py "$TAG" | tee -a "$LOG"
  say "STAGE0_DONE: read cells, y+, peak memory and wall time above before starting 'forward'" ;;
forward)
  run_parallel one_forward $(selected)
  "$PY" fine_campaign/summarize.py "$TAG" > /dev/null; commit "forward summary"; say "FORWARD_DONE" ;;
steady)
  # 1) production state A of the ORIGINAL car on this mesh, kept; 2) steady (upwind) continuation
  [ -d gate/original ] || "$PY" -W ignore -c "
import sys; sys.path.insert(0,'.'); sys.path.insert(0,'../../part2-simulation')
from pathlib import Path; from geometry import Car
c = Car(); c.export_car_folder(c.body_mesh, Path('gate/original'), 'original')"
  if [ ! -f "$OUT/prodcheck_stateA.json" ]; then
    say "start production state A ($RES)"
    PRODCHECK_WALL_RESOLVED=${WALL_RESOLVED:-0} PRODCHECK_RES=$RES PRODCHECK_RESULTS=$OUT PRODCHECK_ITERS=$ITERS PRODCHECK_TIMEOUT=$TIMEOUT PRODCHECK_KEEP=$PWD/gate/refA_$TAG \
      measure "$OUT/resources_stateA.json" "$PY" -W ignore prodcheck.py gate/original stateA "$NP" cold > gate/prodcheck_${TAG}_stateA.log 2>&1 \
      || { say "FAILED state A"; exit 1; }
    commit "production state A"
  fi
  say "start steady continuation (upwind U, ${STEADY_ITERS:-3000} more iterations)"
  measure "$UP/resources_steady.json" "$PY" fine_campaign/steady_base.py gate/refA_$TAG gate/refA_${TAG}_up "$UP" "$NP" "${STEADY_ITERS:-3000}" \
    > gate/steady_$TAG.log 2>&1
  tail -2 gate/steady_$TAG.log | tee -a "$LOG"; commit "steady base"; say "STEADY_DONE" ;;
bumps)
  grep -q '"steady_pass": true' "$UP/base.json" 2>/dev/null || [ "${SMOKE:-0}" = 1 ] || { say "REFUSED: steady base missing or FAILED its mark ($UP/base.json)"; exit 1; }
  export GATE_RES=$RES GATE_RESULTS=$UP GATE_ITERS=${BUMP_ITERS:-1500} GATE_TIMEOUT=$TIMEOUT CFD_DIV_U="bounded Gauss upwind" GATE_WALL_RESOLVED=${WALL_RESOLVED:-0}
  if [ ! -f gate/bump_pod_rear_top_m/car_half.stl ]; then      # the bump geometry (mesh-independent)
    "$PY" -W ignore gate.py bumps > gate/bumps_make.log 2>&1
    for v in pod_rear pod_front_low pod_rear_top; do "$PY" -W ignore gate.py variant ${v}_m $v -1 >> gate/bumps_make.log 2>&1; done
  fi
  [ -f "$UP/bumps.json" ] || cp gate_results/bumps.json "$UP/"
  one_bump() { local k=$1; [ -f "$UP/bump_$k.json" ] && return 0; say "start bump $k"
    measure "$UP/resources_bump_$k.json" "$PY" -W ignore gate.py bump "$k" "$NP" > gate/bump_${TAG}_$k.log 2>&1
    say "done bump $k $(grep -o '"D20_half_N": [0-9.]*\|"morph_fallback": [a-z]*' "$UP/bump_$k.json" 2>/dev/null | tr '\n' ' ')"; commit "bump $k"; }
  run_parallel one_bump pod_rear pod_rear_m pod_front_low pod_front_low_m pod_rear_top pod_rear_top_m
  say "BUMPS_DONE" ;;
adjoint)
  grep -q '"steady_pass": true' "$UP/base.json" 2>/dev/null || [ "${SMOKE:-0}" = 1 ] || { say "REFUSED: steady base missing or FAILED"; exit 1; }
  CELLS=$("$PY" -c "import json;print(json.load(open('$OUT/prodcheck_stateA.json')).get('n_cells') or 0)")
  NEED_GB=$(( CELLS * 150 / 1000000 ))                       # ~150 kB/cell measured on coarse (ROUTES.md)
  HAVE_GB=$(awk '/MemTotal/{t=$2}/SwapTotal/{s=$2}END{print int((t+s)/1048576)}' /proc/meminfo)
  say "adjoint: $CELLS cells, estimated need ~${NEED_GB} GB (extrapolated), this machine RAM+swap ${HAVE_GB} GB"
  [ "$HAVE_GB" -ge "$NEED_GB" ] || [ "${FORCE_ADJOINT:-0}" = 1 ] || { say "REFUSED: not enough memory (FORCE_ADJOINT=1 to try anyway)"; exit 1; }
  "$PY" dafoam/make_case.py --src gate/refA_${TAG}_up --out gate/dafoam_${TAG}_up --iters ${DAF_PRIMAL_ITERS:-300} | tail -1
  DAF_ADJ=Krylov DAF_PC_FILL=${DAF_PC_FILL:-0} DAF_PC_LEVEL=${DAF_PC_LEVEL:-1} DAF_GMRES_ITERS=${DAF_GMRES_ITERS:-2000} \
  DAF_GMRES_RESTART=${DAF_GMRES_RESTART:-200} DAF_GMRES_TOL=${DAF_GMRES_TOL:-1e-4} \
    measure "$UP/resources_adjoint.json" dafoam/run_docker.sh gate/dafoam_${TAG}_up "$NP" > gate/dafoam_${TAG}_up.out 2>&1
  grep -E "DAFOAM|Killed|GMRES|Error" gate/dafoam_${TAG}_up.out | tail -5 | tee -a "$LOG"
  mkdir -p "$UP/dafoam"; cp gate/dafoam_${TAG}_up/dafoam_sens.npz gate/dafoam_${TAG}_up/dafoam_sens.json "$UP/dafoam/" 2>/dev/null
  commit "adjoint"; say "ADJOINT_DONE" ;;
judge)
  "$PY" -W ignore dafoam/pair_judge.py "$UP/dafoam/dafoam_sens.npz" "$UP" --sites pod_rear pod_front_low pod_rear_top | tee -a "$LOG"
  commit "judge"; say "JUDGE_DONE" ;;
bccheck)
  # coarse mesh WITH the wall-resolved layer stack (kLowReWallFunction etc.), then DAFoam primal only
  B=$PWD/gate_results_bccheck; mkdir -p "$B"
  [ -d gate/original ] || { say "run the steady stage once first (it exports gate/original)"; exit 1; }
  [ -f "$B/prodcheck_stateA.json" ] || PRODCHECK_RES=coarse PRODCHECK_RESULTS=$B PRODCHECK_WALL_RESOLVED=1 PRODCHECK_ITERS=${ITERS} \
    PRODCHECK_TIMEOUT=$TIMEOUT PRODCHECK_KEEP=$PWD/gate/refA_bccheck measure "$B/resources_stateA.json" \
    "$PY" -W ignore prodcheck.py gate/original stateA "$NP" cold > gate/bccheck_stateA.log 2>&1
  "$PY" dafoam/make_case.py --src gate/refA_bccheck --out gate/dafoam_bccheck --iters ${DAF_PRIMAL_ITERS:-300} | tail -1
  DAF_PRIMAL_ONLY=1 DAF_ADJ=Krylov measure "$B/resources_dafoam_primal.json" dafoam/run_docker.sh gate/dafoam_bccheck "$NP" > gate/dafoam_bccheck.out 2>&1
  cp gate/dafoam_bccheck/dafoam_primal.json "$B/" 2>/dev/null
  "$PY" - "$B" <<'PY' | tee -a "$LOG"
import json, sys
from pathlib import Path
B = Path(sys.argv[1]); a = json.loads((B / "prodcheck_stateA.json").read_text())
p = B / "dafoam_primal.json"
if not p.exists():
    print("BCCHECK_FAIL: DAFoam primal did not finish (gate/dafoam_bccheck.out)"); sys.exit()
snap = Path("gate/refA_bccheck/logs/snappyHexMesh.log")
import re
cov = re.findall(r"Extruding (\d+) out of (\d+) faces", snap.read_text(errors="replace")) if snap.exists() else []
if cov and int(cov[-1][0]) < 0.5 * int(cov[-1][1]):
    print(f"BCCHECK_INVALID: layers extruded on only {cov[-1][0]} of {cov[-1][1]} wall faces"); sys.exit()
if snap.exists() and "No layers to generate" in snap.read_text(errors="replace"):
    print("BCCHECK_INVALID: the mesh has no wall layers, so wall-resolved conditions were not tested"); sys.exit()
d = json.loads(p.read_text()); r = d["D_half_N"] / a["D20_half_N"] - 1
print(f"pipeline {a['D20_half_N']*1e3:.2f} mN (y+ max {a.get('y_plus_max')}), DAFoam primal {d['D_half_N']*1e3:.2f} mN, diff {r*100:+.2f} %")
print("BCCHECK_PASS" if abs(r) <= 0.02 else "BCCHECK_FAIL (|diff| > 2 %)")
PY
  ( cd "$(git rev-parse --show-toplevel)" && git add research/sidepod_opt/gate_results_bccheck ) ; commit "wall-resolved BC check" ;;
summary)
  "$PY" fine_campaign/summarize.py "$TAG" | tee "fine_campaign/SUMMARY_$TAG.md"; ( cd "$(git rev-parse --show-toplevel)" && git add research/sidepod_opt/fine_campaign/SUMMARY_$TAG.md ); commit "summary" ;;
*) echo "unknown stage $STAGE"; exit 2 ;;
esac
