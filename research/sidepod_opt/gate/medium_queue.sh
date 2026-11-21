#!/bin/bash
# finer-mesh (medium, ~520k cells) production check of tonight's key designs, cold start, 4 cores each
cd /home/user/esp32-line-follower/research/sidepod_opt
source /usr/lib/openfoam/openfoam2412/etc/bashrc
export PATH=/opt/py/bin:$PATH OMPI_ALLOW_RUN_AS_ROOT=1 OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 OMPI_MCA_rmaps_base_oversubscribe=1 PRODCHECK_RES=medium
for job in "runs/cloud_original/it_000/car team" "runs/concepts/channel/car channel" "runs/cloud_original/it_008/car adjoint_it8" "runs/concepts/win3/car win3" "runs/cloud_lean/it_000/car nopod"; do
  set -- $job
  [ -f gate_results_medium/prodcheck_$2.json ] || python -W ignore prodcheck.py $1 $2 4 cold > gate/prodcheck_medium_$2.log 2>&1
  echo "done $2 $(date -u +%T)"
done
echo MEDIUM_DONE
