#!/bin/bash
# Run a topology case made by make_topo_case.py:  topo/run_topo.sh <case> [np]
# Log: <case>/log.adjointOptimisationFoam; the design (alpha, beta) is written every 5 cycles.
set -euo pipefail
CASE=$(realpath "$1"); NP=${2:-4}
set +eu; source /usr/lib/openfoam/openfoam2412/etc/bashrc; set -eu
export OMPI_ALLOW_RUN_AS_ROOT=1 OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 OMPI_MCA_rmaps_base_oversubscribe=1
cd "$CASE"
sed -i "s/numberOfSubdomains .*/numberOfSubdomains $NP;/" system/decomposeParDict
decomposePar -force > log.decomposePar 2>&1
start=$(date +%s)
mpirun -np "$NP" adjointOptimisationFoam -parallel > log.adjointOptimisationFoam 2>&1 || echo "SOLVER_EXIT $?" >> log.adjointOptimisationFoam
reconstructPar > log.reconstructPar 2>&1 || true
echo "TOPO_DONE $(( $(date +%s) - start )) s" >> log.adjointOptimisationFoam
