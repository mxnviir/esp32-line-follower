#!/bin/bash
# ESI adjoint with its own full setup (ROUTES.md 2026-11-21 15:30): grid sensitivities + wall distance + full ATC
cd /home/user/esp32-line-follower/research/sidepod_opt
source /usr/lib/openfoam/openfoam2412/etc/bashrc 2>/dev/null; export PATH=/opt/py/bin:$PATH
run() { # tag turb env...
  local tag=$1 turb=$2; shift 2
  [ -f gate_results_coarse_up/esi/pair_judge_$tag.json ] && return
  echo "start $tag $(date -u +%T)"
  env "$@" python -W ignore esi/esi_on_state.py gate/refA_coarse_up gate/esi_coarse_up_$tag $turb 2 3000 100 > gate/esi_$tag.log 2>&1
  if [ -f gate/esi_coarse_up_$tag/esi_sens.npz ]; then
    cp gate/esi_coarse_up_$tag/esi_sens.npz gate_results_coarse_up/esi/esi_sens_$tag.npz; cp gate/esi_coarse_up_$tag/esi_sens.json gate_results_coarse_up/esi/esi_sens_$tag.json
    python -W ignore dafoam/pair_judge.py gate_results_coarse_up/esi/esi_sens_$tag.npz gate_results_coarse_up --sites pod_rear pod_front_low pod_rear_top --out gate_results_coarse_up/esi/pair_judge_$tag.json > /dev/null 2>&1
    echo "done $tag $(date -u +%T) $(python -c "import json;d=json.load(open('gate_results_coarse_up/esi/pair_judge_$tag.json'));print('signs',d.get('signs'),'r',round(d.get('pearson_r') or 0,3),'ratios',[round(x,2) for x in d.get('ratio_pred_over_meas',[])])")"
  else echo "FAILED $tag $(date -u +%T): $(grep -m2 -E 'ESI_FAILED|FOAM FATAL|Error' gate/esi_$tag.log | tr '\n' ' ')"; fi
}
# sst_full crashed (SIGFPE in adjointkOmegaSST::divDevReff), not repeated
run sst_mesh sst ESI_MESHMOVE=1
run frozen_mesh frozen ESI_MESHMOVE=1
echo ESI_FULL_DONE
