#!/bin/bash
# fair ESI adjoint test on the coarse steady state (ROUTES.md 2026-11-21 14:10), frozen then SST adjoint
cd /home/user/esp32-line-follower/research/sidepod_opt
source /usr/lib/openfoam/openfoam2412/etc/bashrc
export PATH=/opt/py/bin:$PATH
mkdir -p gate_results_coarse_up/esi
for turb in frozen sst; do
  [ -f gate_results_coarse_up/esi/pair_judge_$turb.json ] && continue
  echo "start $turb $(date -u +%T)"
  python -W ignore esi/esi_on_state.py gate/refA_coarse_up gate/esi_coarse_up_$turb $turb 2 3000 100 > gate/esi_$turb.log 2>&1
  if [ -f gate/esi_coarse_up_$turb/esi_sens.npz ]; then
    cp gate/esi_coarse_up_$turb/esi_sens.npz gate/esi_coarse_up_$turb/esi_sens.json gate_results_coarse_up/esi/ 2>/dev/null
    mv gate_results_coarse_up/esi/esi_sens.npz gate_results_coarse_up/esi/esi_sens_$turb.npz; mv gate_results_coarse_up/esi/esi_sens.json gate_results_coarse_up/esi/esi_sens_$turb.json
    python -W ignore dafoam/pair_judge.py gate_results_coarse_up/esi/esi_sens_$turb.npz gate_results_coarse_up --sites pod_rear pod_front_low pod_rear_top --out gate_results_coarse_up/esi/pair_judge_$turb.json > gate/esi_judge_$turb.log 2>&1
    echo "done $turb $(date -u +%T) $(python -c "import json;d=json.load(open('gate_results_coarse_up/esi/pair_judge_$turb.json'));print('signs',d.get('signs'),'r',d.get('pearson_r'),'ratios',[round(x,2) for x in d.get('ratio_pred_over_meas',[])])")"
  else
    echo "FAILED $turb $(date -u +%T): $(grep -m1 -E 'ESI_FAILED|FOAM FATAL|Error' gate/esi_$turb.log)"
  fi
done
echo ESI_DONE
