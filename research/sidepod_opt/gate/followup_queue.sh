#!/bin/bash
# controls for the medium-mesh surprise (ROUTES.md 2026-11-21 09:30). Waits for the medium five.
cd /home/user/esp32-line-follower/research/sidepod_opt
source /usr/lib/openfoam/openfoam2412/etc/bashrc
export PATH=/opt/py/bin:$PATH OMPI_ALLOW_RUN_AS_ROOT=1 OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 OMPI_MCA_rmaps_base_oversubscribe=1
until grep -q MEDIUM_DONE gate/medium_queue.log; do sleep 30; done
run() { # res folder tag
  [ -f gate_results_$1/prodcheck_$3.json ] || PRODCHECK_RES=$1 python -W ignore prodcheck.py $2 $3 4 cold > gate/prodcheck_$1_$3.log 2>&1
  [ -f gate_results_$1/prodcheck_$3.json ] && echo "done $1 $3 $(date -u +%T)" || echo "FAILED $1 $3 $(date -u +%T)"
}
run coarse runs/cloud_original/it_000/car cold_team
run coarse runs/cloud_original/it_008/car cold_it8
run medium runs/concepts/it8_p05/car adjoint_it8_p05
run medium runs/concepts/seed_p05/car team_p05
echo FOLLOWUP_DONE
