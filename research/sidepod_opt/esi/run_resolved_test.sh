#!/bin/bash
# Normal (ESI, continuous) adjoint accuracy test on the WALL-RESOLVED ~4-5 M-cell mesh (Part 2 "resolved":
# every wall at one cell size ~0.7 mm, wheels ~0.35 mm, a y+ <= 2 prism-layer stack). Instructions: esi/RESOLVED_TEST.md
#
#   NP=4 bash research/sidepod_opt/esi/run_resolved_test.sh          (resumable: re-run the same command after any stop)
#
# Env: NP (cores, default 4), OF_BASHRC (default /usr/lib/openfoam/openfoam2412/etc/bashrc), PY (python with the
# repo's packages; default python3), ITERS (production base, default 3000), STEADY_ITERS (default 3000),
# BUMP_ITERS (default 1500), ADJ_ITERS (default 3000), PUSH (1 = commit+push results after each step; default 0).
set -uo pipefail
cd "$(dirname "$0")/.."                                  # research/sidepod_opt
export NP=${NP:-4} PY=${PY:-$(command -v python3)} OF_BASHRC=${OF_BASHRC:-/usr/lib/openfoam/openfoam2412/etc/bashrc}
export RES=resolved TAG=resolved WALL_RESOLVED=1 ITERS=${ITERS:-3000} STEADY_ITERS=${STEADY_ITERS:-3000} \
       BUMP_ITERS=${BUMP_ITERS:-1500} JOBS=1 TIMEOUT=${TIMEOUT:-172800} PUSH=${PUSH:-0}
ADJ_ITERS=${ADJ_ITERS:-3000}
LOG=gate/resolved_test.log; mkdir -p gate
say() { echo "== $* $(date -u +%F_%T)" | tee -a "$LOG"; }

say "preflight"
[ -f "$OF_BASHRC" ] || { say "STOP: OpenFOAM v2412 not found at $OF_BASHRC"; exit 1; }
( set +u; source "$OF_BASHRC" >/dev/null 2>&1; command -v adjointOptimisationFoam >/dev/null ) || { say "STOP: adjointOptimisationFoam missing (needs ESI OpenFOAM v2412)"; exit 1; }
"$PY" -c "import numpy, scipy, trimesh, jax" 2>/dev/null || { say "STOP: python packages missing (part1-simulation/requirements.txt)"; exit 1; }
MEM=$(awk '/MemTotal/{t=$2}/SwapTotal/{s=$2}END{print int((t+s)/1048576)}' /proc/meminfo)
DISK=$(df -BG --output=avail . | tail -1 | tr -dc 0-9)
say "cores $(nproc), RAM+swap ${MEM} GB, free disk ${DISK} GB, NP=$NP"
[ "$MEM" -ge 24 ] || say "WARNING: RAM+swap ${MEM} GB; meshing ~5 M cells with layers may need more (add swap, see RESOLVED_TEST.md)"
[ "$DISK" -ge 40 ] || { say "STOP: need >= 40 GB free disk (have ${DISK})"; exit 1; }

# 1. production base on the resolved mesh, then the steady ("upwind U") continuation + mark A1
if ! grep -q '"steady_pass"' gate_results_resolved_up/base.json 2>/dev/null; then
  say "step 1: production base + steady continuation"
  bash fine_campaign/campaign.sh steady >> "$LOG" 2>&1
fi
SNAP=gate/refA_resolved/logs/snappyHexMesh.log
if [ -f "$SNAP" ] && grep -q "No layers to generate" "$SNAP"; then say "STOP: the mesh has NO wall layers; not a wall-resolved test"; exit 1; fi
"$PY" - <<'PY' | tee -a "$LOG"
import json
a = json.load(open("gate_results_resolved/prodcheck_stateA.json")); b = json.load(open("gate_results_resolved_up/base.json"))
print(f"mesh: {a.get('n_cells')} cells, y+ {a.get('y_plus_min')}..{a.get('y_plus_max')}; production D {a['D20_half_N']*1e3:.2f} mN; "
      f"steady D {b['D20_half_N']*1e3:.2f} mN, block span {b['block_span_last1000_mN']:.3f} mN -> {'A1 PASS' if b['steady_pass'] else 'A1 FAIL'}")
PY
grep -q '"steady_pass": true' gate_results_resolved_up/base.json || { say "STOP: mark A1 failed (wake not steady on this mesh); report it, do not run the bumps"; exit 1; }

# 2. measured answers: six +/-1 mm bumps on the steady state (mesh reshaped, warm start)
say "step 2: bumps"
bash fine_campaign/campaign.sh bumps >> "$LOG" 2>&1
grep -h '"morph_fallback": true' gate_results_resolved_up/bump_*.json >/dev/null && say "WARNING: a bump fell back to a fresh mesh; that pair is not usable"

# 3. the normal adjoint on the same mesh and flow: frozen turbulence, then full SST
set +u; source "$OF_BASHRC" >/dev/null 2>&1; set -u
mkdir -p gate_results_resolved_up/esi
for turb in frozen sst; do
  J=gate_results_resolved_up/esi/pair_judge_$turb.json
  [ -f "$J" ] && continue
  say "step 3: ESI adjoint ($turb)"
  "$PY" -W ignore esi/esi_on_state.py gate/refA_resolved_up gate/esi_resolved_$turb $turb "$NP" "$ADJ_ITERS" 100 > gate/esi_resolved_$turb.log 2>&1
  if [ -f gate/esi_resolved_$turb/esi_sens.npz ]; then
    cp gate/esi_resolved_$turb/esi_sens.npz gate_results_resolved_up/esi/esi_sens_$turb.npz
    cp gate/esi_resolved_$turb/esi_sens.json gate_results_resolved_up/esi/esi_sens_$turb.json
    "$PY" -W ignore dafoam/pair_judge.py gate_results_resolved_up/esi/esi_sens_$turb.npz gate_results_resolved_up \
      --sites pod_rear pod_front_low pod_rear_top --out "$J" > /dev/null
  else
    say "ESI $turb FAILED: $(grep -m2 -E 'ESI_FAILED|FATAL|Floating' gate/esi_resolved_$turb.log | tr '\n' ' ')"
  fi
done

# 4. verdict (marks fixed in ROUTES.md 2026-11-21 15:15 before any result)
"$PY" - <<'PY' | tee -a "$LOG" | tee gate_results_resolved_up/esi/VERDICT.txt
import json, os
for turb in ("frozen", "sst"):
    p = f"gate_results_resolved_up/esi/pair_judge_{turb}.json"
    if not os.path.exists(p):
        print(f"{turb}: no result"); continue
    d = json.load(open(p)); rows = d["pairs"]
    ratios = d.get("ratio_pred_over_meas") or []
    ok = (d.get("pearson_r") or 0) >= 0.9 and d.get("signs", "0/1").split("/")[0] == d.get("signs", "0/1").split("/")[1] \
         and len(ratios) == 3 and all(0.5 <= r <= 2.0 for r in ratios)
    print(f"{turb}: signs {d.get('signs')}, r {d.get('pearson_r')}, predicted/measured {[round(r, 2) for r in ratios]} -> {'PASS' if ok else 'FAIL'}")
    for r in rows:
        print(f"   {r['site']:14s} measured {r['measured_half_mN']:+.3f} mN  predicted {r['predicted_half_mN']:+.3f}  stderr {r['stderr_mN']:.3f}  usable {r['usable']}")
PY
if [ "$PUSH" = 1 ]; then
  ( cd "$(git rev-parse --show-toplevel)" && git add research/sidepod_opt/gate_results_resolved research/sidepod_opt/gate_results_resolved_up \
    && git commit -q -m "Normal adjoint test on the wall-resolved mesh: results" && git pull -q --no-rebase --no-edit && git push -q ) || say "push failed"
fi
say "RESOLVED_TEST_DONE"
