#!/bin/bash
# owner wants the normal-adjoint wall-resolved test first (2026-11-21 15:20): finish win3_p05, then the test,
# then the layered BC check, then the remaining medium runs
cd /home/user/esp32-line-follower/research/sidepod_opt
while pgrep -f "prodcheck.py .*win3_p05" >/dev/null; do sleep 20; done
echo "win3_p05 finished $(date -u +%T) $(ls gate_results_medium/prodcheck_win3_p05.json 2>/dev/null)"
export PY=/opt/py/bin/python
# 1) the normal-adjoint test on the coarse mesh WITH the wall-resolved layer stack
( export RES=coarse TAG=coarsewr WALL_RESOLVED=1 NP=4 ITERS=2000
  bash fine_campaign/campaign.sh steady
  BUMP_ITERS=1000 JOBS=2 NP=2 bash fine_campaign/campaign.sh bumps )
source /usr/lib/openfoam/openfoam2412/etc/bashrc 2>/dev/null
mkdir -p gate_results_coarsewr_up/esi
for turb in frozen sst; do
  $PY -W ignore esi/esi_on_state.py gate/refA_coarsewr_up gate/esi_coarsewr_$turb $turb 4 3000 100 > gate/esi_coarsewr_$turb.log 2>&1
  if [ -f gate/esi_coarsewr_$turb/esi_sens.npz ]; then
    cp gate/esi_coarsewr_$turb/esi_sens.npz gate_results_coarsewr_up/esi/esi_sens_$turb.npz
    $PY -W ignore dafoam/pair_judge.py gate_results_coarsewr_up/esi/esi_sens_$turb.npz gate_results_coarsewr_up --sites pod_rear pod_front_low pod_rear_top --out gate_results_coarsewr_up/esi/pair_judge_$turb.json > /dev/null 2>&1
    echo "done esi $turb $($PY -c "import json;d=json.load(open('gate_results_coarsewr_up/esi/pair_judge_$turb.json'));print('signs',d.get('signs'),'r',d.get('pearson_r'),'ratios',[round(x,2) for x in d.get('ratio_pred_over_meas',[])])")"
  else echo "FAILED esi $turb: $(grep -m1 -E 'ESI_FAILED|FATAL' gate/esi_coarsewr_$turb.log)"; fi
done
echo ESI_LAYERS_DONE
# 2) layered BC check for DAFoam, 3) the remaining medium runs
RES=coarse NP=4 ITERS=2000 bash fine_campaign/campaign.sh bccheck
RES=medium TAG=medium NP=4 ITERS=2000 ONLY="blend50 blend75 win5 nopod_p05 win3_p05 blend50_p05 blend75_p05" bash fine_campaign/campaign.sh forward
echo REORDER_DONE
