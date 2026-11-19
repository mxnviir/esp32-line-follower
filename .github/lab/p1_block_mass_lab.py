"""p1_block_mass_lab: the start block's body mass at a grid spacing, with WALL_SCOPE all and
own, and its mass at the most-grown legal skin, to show which body targets sizing can reach
(reviewer, 2026-11-16: the 2 mm tests size to 40 g, "the whole block is under 48.2 g").

    python ../.github/lab/p1_block_mass_lab.py <spacing_mm>     (from part5-simulation)"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd().parent / "part1-simulation"))
import cutter  # noqa: E402
import param_body  # noqa: E402
import unified_phi as up  # noqa: E402

sp = float(sys.argv[1])
lay = {"W": 120.3, "x_front": 46.0, "d_halo": 43.72}
out = {"spacing_mm": sp}
for scope in ("all", "own"):
    param_body.WALL_SCOPE = scope
    g = cutter.start_block(lay, spacing_mm=sp)
    out[f"block_g_{scope}"] = round(1e3 * sum(c.mass_kg for c in up.compute_mass_com(g)), 3)
    body = param_body.build(lay["W"], lay["x_front"], lay["d_halo"], param_body.BodyParams(),
                            skin_offset_mm=0.0, field_mm=g.phi.grid * 1e3)
    out[f"built_skin0_g_{scope}"] = round(1e3 * sum(c.mass_kg for c in up.compute_mass_com(body)), 3)
print("LAB mass " + json.dumps(out), flush=True)
