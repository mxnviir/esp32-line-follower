#!/bin/bash
# DAFoam drag gradient of the trial car on any machine with Docker: a GitHub Actions runner
# (.github/workflows/dafoam_adjoint.yml) or a Codespace (dafoam/codespace.sh).
#   dafoam/remote_run.sh <out_dir> [np] [primal_iters]
# 1. State A with Part 2's own pipeline (OpenFOAM v2412 + gate.py base, 2000 iterations), unless
#    STATE_DIR names an existing converged case folder (e.g. one unzipped from a release).
# 2. dafoam/make_case.py: same mesh, BCs and schemes, flow started from state A.
# 3. dafoam/run_docker.sh: DAFoam primal + adjoint, giving dafoam_sens.npz/json, copied to <out_dir>.
# A gradient from another machine's state A scores against bumps measured on THAT state A only; the
# accuracy test against gate_results/ needs gate/refA from the machine that ran the gate.
set -euo pipefail
OUT=$(realpath -m "$1"); NP=${2:-4}; ITERS=${3:-300}
cd "$(dirname "$0")/.."                                  # research/sidepod_opt
mkdir -p "$OUT"
if [ -z "${STATE_DIR:-}" ]; then
  if ! command -v simpleFoam >/dev/null 2>&1; then
    [ -f /usr/lib/openfoam/openfoam2412/etc/bashrc ] || {
      ((for i in 1 2 3; do timeout 120 sudo apt-get update -q && break; sleep 20; done) || true)
      sudo apt-get install -y -q libopengl0 libglu1-mesa libegl1 libgl1 libgomp1 libxkbcommon0
      curl -s https://dl.openfoam.com/add-debian-repo.sh | sudo bash
      sudo apt-get install -y -q openfoam2412-default; }
    set +u; source /usr/lib/openfoam/openfoam2412/etc/bashrc; set -u
  fi
  [ -f gate/original/car_half.stl ] || python -W ignore -c "
from pathlib import Path; from geometry import Car
c = Car(); c.export_car_folder(c.body_mesh, Path('gate/original'), 'original')"
  GATE_RESULTS="$OUT/stateA" python -W ignore gate.py base "$NP" | tail -3
  STATE_DIR=gate/refA
fi
python dafoam/make_case.py --src "$STATE_DIR" --out gate/dafoam_case --iters "$ITERS"
dafoam/run_docker.sh gate/dafoam_case "$NP"
cp gate/dafoam_case/dafoam_sens.npz gate/dafoam_case/dafoam_sens.json gate/dafoam_case/log.dafoam "$OUT/"
echo "DAFOAM_REMOTE_DONE $OUT"
