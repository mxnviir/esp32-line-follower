"""p1_wall_stop_lab: why a cut on the start block is refused as min_wall (queue-code tests,
anass 43902774172, 2026-11-16). Wraps phi_updater.thin_wall_mask so each sub-step's check
prints the cells it calls newly thin: where (mm), old and new half thickness, whether the
cell is rule-forced solid, and the start block's own thin cells and thinnest wall.

    python ../.github/lab/p1_wall_stop_lab.py <spacing_mm>:<dT_dn>   (e.g. 2:1, 2:-1, 1:1; from part5-simulation)"""
import json
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path.cwd().parent / "part1-simulation"))
import numpy as np  # noqa: E402

import coarse  # noqa: E402
import cutter  # noqa: E402
import phi_updater as pu  # noqa: E402
from unified_phi import extract_half_surface  # noqa: E402

sp, val = map(float, sys.argv[1].split(":"))
coarse.use_spacing(sp)
lay = {"W": 120.3, "x_front": 46.0, "d_halo": 43.72}
g = cutter.start_block(lay, spacing_mm=sp)
mesh = SimpleNamespace(vertices=np.asarray(extract_half_surface(g).vertices))
d = sp * 1e-3
st = {"half0": None, "call": 0}
orig = pu.thin_wall_mask



def spy(grid, spacing_m, min_wall_m):
    h = pu._wall_half(grid, spacing_m)
    m = h < min_wall_m / 2.0
    st["call"] += 1
    hm_s = g.phi.hard_mask_solid
    if st["half0"] is None:
        st["half0"], st["m0"] = h, m
        idx = np.argwhere(m)
        print("LAB start " + json.dumps({"spacing_mm": sp, "thin_cells": int(m.sum()),
              "min_wall_mm": float(2e3 * h.min()), "thin_in_forced_solid": int((m & hm_s).sum()),
              "first": [[*np.round(np.asarray(g.region.origin_m) * 1e3 + np.array(i) * sp, 1).tolist(), round(2e3 * h[tuple(i)], 3)] for i in idx[:15]]}), flush=True)
    else:
        new = m & ~st["m0"]
        idx = np.argwhere(new)
        from scipy.ndimage import minimum_filter
        loc = minimum_filter(np.where(np.isfinite(st["half0"]), st["half0"], 1e9), size=3)
        print("LAB check " + json.dumps({"call": st["call"], "new_thin": int(new.sum()),
              "new_in_forced_solid": int((new & hm_s).sum()),
              "new_where_old_3x3_was_thin": int((new & (loc < min_wall_m / 2)).sum()),
              "new_min_wall_mm": float(2e3 * h[new].min()) if new.any() else None,
              "cells": [[*map(int, i), round(2e3 * h[tuple(i)], 3),
                         round(2e3 * float(st["half0"][tuple(i)]), 3) if np.isfinite(st["half0"][tuple(i)]) else None,
                         bool(hm_s[tuple(i)])] for i in idx[:25]]}), flush=True)
    return m


pu.thin_wall_mask = spy
_orig_thinned = pu._thinned


def spy_thinned(before, after, spacing_m, min_wall_m):
    """The new guard (wall_guard) calls _thinned: print each sub-step's flagged cells in mm, with
    old (3x3x3 min) and new wall mm, phi before and after mm (growth lowers phi), rule air within 2 cells."""
    from scipy.ndimage import binary_dilation, minimum_filter
    bad = _orig_thinned(before, after, spacing_m, min_wall_m)
    st["call"] += 1
    h0 = minimum_filter(pu._wall_half(before, spacing_m), size=3, mode="nearest")
    h1 = pu._wall_half(after, spacing_m)
    near_air = binary_dilation(g.phi.hard_mask_air, iterations=2)
    o = np.asarray(g.region.origin_m) * 1e3
    idx = np.argwhere(bad)
    cells = [[*np.round(o + i * sp, 1).tolist(),
              round(2e3 * float(h0[tuple(i)]), 3) if np.isfinite(h0[tuple(i)]) else None,
              round(2e3 * float(h1[tuple(i)]), 3), round(1e3 * float(before[tuple(i)]), 3),
              round(1e3 * float(after[tuple(i)]), 3), bool(near_air[tuple(i)])] for i in idx[:30]]
    print("LAB thinned " + json.dumps({"call": st["call"], "n": int(bad.sum()),
          "near_rule_air": int((bad & near_air).sum()), "cells": cells}), flush=True)
    return bad


pu._thinned = spy_thinned
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    _, rep = cutter.cut(g, np.full(len(mesh.vertices), val), mesh, step_m=1.0)
print("LAB result " + json.dumps({k: rep.get(k) for k in ("status", "reason", "substeps", "min_wall_stop",
      "thin_wall_cells_at_start", "disp_p90_m")}, default=str), flush=True)
