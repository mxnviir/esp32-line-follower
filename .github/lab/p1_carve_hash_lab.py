"""p1_carve_hash_lab: the field hash of fixed carves, to compare commits (run on both, diff the
lines). exact_speed (2026-11-17) should leave bias-only carves unchanged or nearly so; bump carves
change by design.

    python ../.github/lab/p1_carve_hash_lab.py   (from part5-simulation)"""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd().parent / "part1-simulation"))
import numpy as np  # noqa: E402

import carve  # noqa: E402

lay = {"W": 120.3, "x_front": 46.0, "d_halo": 43.72}
cases = {"bias-1_trust1_2mm": ([{"bias_mm": -1.0, "trust_mm": 1.0}], 2.0),
         "bias+1_trust1_2mm": ([{"bias_mm": 1.0, "trust_mm": 1.0}], 2.0),
         "bias-1_trust1_1mm": ([{"bias_mm": -1.0, "trust_mm": 1.0}], 1.0)}
for name, (edits, sp) in cases.items():
    g, reps = carve.carve(lay, edits, spacing_mm=sp)
    f = np.ascontiguousarray(g.phi.grid, dtype=np.float32)
    print(f"LAB hash {name}: {hashlib.sha256(f.tobytes()).hexdigest()} solid {int((f < 0).sum())} "
          f"substeps {[r.get('substeps') for r in reps]} status {[r.get('status') for r in reps]}")
