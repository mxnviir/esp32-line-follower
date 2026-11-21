#!/bin/bash
# decisive normal-adjoint test on a wall-resolved (layered) coarse mesh (ROUTES.md 2026-11-21 15:15)
cd /home/user/esp32-line-follower/research/sidepod_opt
until grep -q BCCHECK2_DONE gate/bccheck2.log; do sleep 30; done
export PY=/opt/py/bin/python RES=coarse TAG=coarsewr WALL_RESOLVED=1 NP=4 ITERS=2000
bash fine_campaign/campaign.sh steady
BUMP_ITERS=1000 JOBS=2 NP=2 bash fine_campaign/campaign.sh bumps
source /usr/lib/openfoam/openfoam2412/etc/bashrc 2>/dev/null
mkdir -p gate_results_coarsewr_up/esi
for turb in frozen sst; do
  python -W ignore esi/esi_on_state.py gate/refA_coarsewr_up gate/esi_coarsewr_$turb $turb 4 3000 100 > gate/esi_coarsewr_$turb.log 2>&1
  if [ -f gate/esi_coarsewr_$turb/esi_sens.npz ]; then
    cp gate/esi_coarsewr_$turb/esi_sens.npz gate_results_coarsewr_up/esi/esi_sens_$turb.npz
    $PY -W ignore dafoam/pair_judge.py gate_results_coarsewr_up/esi/esi_sens_$turb.npz gate_results_coarsewr_up --sites pod_rear pod_front_low pod_rear_top --out gate_results_coarsewr_up/esi/pair_judge_$turb.json > /dev/null 2>&1
    echo "done esi $turb $($PY -c "import json;d=json.load(open('gate_results_coarsewr_up/esi/pair_judge_$turb.json'));print('signs',d.get('signs'),'r',d.get('pearson_r'),'ratios',[round(x,2) for x in d.get('ratio_pred_over_meas',[])])")"
  else echo "FAILED esi $turb: $(grep -m1 -E 'ESI_FAILED|FATAL' gate/esi_coarsewr_$turb.log)"; fi
done
echo ESI_LAYERS_DONE
