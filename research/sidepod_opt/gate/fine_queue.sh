#!/bin/bash
# is the medium mesh converged? "fine" mesh, cold start (ROUTES.md 2026-11-21 10:10). Waits for the controls.
cd /home/user/esp32-line-follower/research/sidepod_opt
source /usr/lib/openfoam/openfoam2412/etc/bashrc
export PATH=/opt/py/bin:$PATH OMPI_ALLOW_RUN_AS_ROOT=1 OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 OMPI_MCA_rmaps_base_oversubscribe=1
until grep -q FOLLOWUP_DONE gate/followup_queue.log; do sleep 30; done
swapon --show | grep -q swapfile || swapon /swapfile 2>/dev/null
for job in "runs/cloud_original/it_000/car team" "runs/concepts/channel/car channel" "runs/cloud_original/it_008/car adjoint_it8"; do
  set -- $job
  [ -f gate_results_fine/prodcheck_$2.json ] || PRODCHECK_RES=fine python -W ignore prodcheck.py $1 $2 4 cold > gate/prodcheck_fine_$2.log 2>&1
  [ -f gate_results_fine/prodcheck_$2.json ] && echo "done fine $2 $(date -u +%T)" || echo "FAILED fine $2 $(date -u +%T)"
done
echo FINE_DONE
