#!/bin/bash
# Run the DAFoam case in its Docker image (no local install). Same script on this machine, GitHub
# Actions and a Codespace (all have Docker).
#   dafoam/run_docker.sh <case_dir> [np] [image]
# The case dir gets: renumberMesh, then mpirun -np <np> python runScript.py -> dafoam_sens.npz / .json
set -euo pipefail
CASE=$(realpath "$1"); NP=${2:-4}; IMAGE=${3:-${DAFOAM_IMAGE:-dafoam/opt-packages:v5.1.1}}
HERE=$(cd "$(dirname "$0")" && pwd)
cp "$HERE/runScript.py" "$CASE/"
chmod -R a+rwX "$CASE"                       # the image runs as dafoamuser
docker run --rm -u dafoamuser --shm-size=2g \
  --mount "type=bind,src=$CASE,target=/home/dafoamuser/case" -w /home/dafoamuser/case \
  -e DAF_GMRES_TOL -e DAF_GMRES_ITERS -e DAF_PC_FILL -e DAF_PC_LEVEL "$IMAGE" bash -c '
    . /home/dafoamuser/dafoam/loadDAFoam.sh >/dev/null
    set -e
    if [ ! -f .renumbered ]; then
      renumberMesh -overwrite > log.renumberMesh 2>&1
      # the AD build reads ASCII only: convert mesh and fields once (controlDict says ascii)
      foamFormatConvert -constant > log.formatConvert 2>&1
      touch .renumbered
    fi
    rm -rf processor* *Coloring*.bin
    mpirun -np '"$NP"' python runScript.py 2>&1 | tee log.dafoam
  '
