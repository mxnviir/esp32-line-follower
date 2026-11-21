#!/bin/bash
# medium-mesh scatter: repeat meshes of the team pod, the groove and design 8 (ROUTES.md 2026-11-21 10:45)
cd /home/user/esp32-line-follower/research/sidepod_opt
source /usr/lib/openfoam/openfoam2412/etc/bashrc
export PATH=/opt/py/bin:$PATH OMPI_ALLOW_RUN_AS_ROOT=1 OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 OMPI_MCA_rmaps_base_oversubscribe=1
until grep -q FOLLOWUP_DONE gate/followup_queue.log; do sleep 30; done
for job in "seed_m05 team_m05" "channel_p05 channel_p05" "it8_m05 adjoint_it8_m05" "channel_m05 channel_m05" "seed_p10 team_p10"; do
  set -- $job
  [ -f gate_results_medium/prodcheck_$2.json ] || PRODCHECK_RES=medium python -W ignore prodcheck.py runs/concepts/$1/car $2 4 cold > gate/prodcheck_medium_$2.log 2>&1
  [ -f gate_results_medium/prodcheck_$2.json ] && echo "done medium $2 $(date -u +%T)" || echo "FAILED medium $2 $(date -u +%T)"
done
echo SCATTER_DONE
