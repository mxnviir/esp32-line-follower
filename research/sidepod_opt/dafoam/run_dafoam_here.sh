#!/bin/bash
# DAFoam adjoint on the coarse state A case (gate/dafoam_coarseA, from make_case.py), in Docker, 4 ranks.
#   DAF_ADJ=fixedPoint|Krylov dafoam/run_dafoam_here.sh      -> gate/dafoam_coarseA_<ADJ>.out
cd "$(dirname "$0")/.."   # research/sidepod_opt
ADJ=${DAF_ADJ:-fixedPoint}
echo START $ADJ $(date -u)
DAF_ADJ=$ADJ DAF_PC_FILL=${DAF_PC_FILL:-0} DAF_PC_LEVEL=${DAF_PC_LEVEL:-1} DAF_GMRES_ITERS=${DAF_GMRES_ITERS:-2000} \
  DAF_GMRES_RESTART=${DAF_GMRES_RESTART:-200} DAF_FP_ITERS=${DAF_FP_ITERS:-2000} \
  dafoam/run_docker.sh ${DAF_CASE:-gate/dafoam_coarseA} 4 > ${DAF_CASE:-gate/dafoam_coarseA}_$ADJ.out 2>&1
echo EXIT $? $(date -u)
