#!/bin/bash
# known-answer test of the drag proxy: porous empty vs porous original vs body-fitted lean/original
cd "$(dirname "$0")/.."
for v in fixed_empty fixed_original; do topo/run_topo.sh topo/kat_$v 4; echo "done $v $(date -u +%T)"; done
export OMPI_ALLOW_RUN_AS_ROOT=1 OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 OMPI_MCA_rmaps_base_oversubscribe=1
set +eu; source /usr/lib/openfoam/openfoam2412/etc/bashrc; set -eu
GATE_RES=coarse python -W ignore - <<'P'
import json, sys; sys.path.insert(0, ".")
import gate
from pathlib import Path
half, health, secs = gate.solve(Path("topo/lean_car"), 4, 2000, keep=False)
d = {"D20_half_N": float(half.D20), "L20_half_N": float(half.L), "converged": bool(health.converged), "wall_s": secs}
Path("topo/lean_bodyfitted_coarse.json").write_text(json.dumps(d, indent=1))
print(d)
P
echo "KAT_DONE $(date -u +%T)"
