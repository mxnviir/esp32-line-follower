"""p1_dead_mode_lab: why a +-1 mm bump (sigma 10, unit False) at a surface point moves nothing
(Part 3 mode 9, under the floor: 0 cells changed side, status ok). Prints, inside 2 sigma of
the centre: the rule masks (forced air / solid cells), the speed the HJ step gets, and how many
cells have changed side after each stage of the cut (each HJ sub-step, its wall guard, the
machinability fill, thin-strip drop, pinch closing, the final guard, the rule re-apply).
The first stage where the count drops to 0 is the mechanism.

    python ../.github/lab/p1_dead_mode_lab.py <spacing_mm> <amp_mm> <x,y,z mm>   (from part5-simulation)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd().parent / "part1-simulation"))
import numpy as np  # noqa: E402

import carve  # noqa: E402
import cutter  # noqa: E402
import phi_updater as pu  # noqa: E402
import unified_phi as up  # noqa: E402

sp, amp = float(sys.argv[1]), float(sys.argv[2])
c = np.array([float(v) for v in sys.argv[3].split(",")])
lay = {"W": 120.3, "x_front": 46.0, "d_halo": 43.72}
g0 = cutter.start_block(lay, spacing_mm=sp)
o = np.asarray(g0.region.origin_m) * 1e3
X, Y, Z = np.meshgrid(*(o[k] + np.arange(g0.phi.grid.shape[k]) * sp for k in range(3)), indexing="ij")
ball = (X - c[0]) ** 2 + (np.abs(Y) - c[1]) ** 2 + (Z - c[2]) ** 2 <= 20.0 ** 2
s0 = g0.phi.grid < 0
print(f"LAB centre {c.tolist()} mm, grid k {int(round((c[2] - o[2]) / sp))} of {g0.phi.grid.shape[2]}, z0 {o[2]:.2f} mm")
print(f"LAB ball cells {int(ball.sum())}: solid {int((s0 & ball).sum())}, forced air {int((g0.phi.hard_mask_air & ball).sum())}, "
      f"forced solid {int((g0.phi.hard_mask_solid & ball).sum())}, iface {int(((np.abs(g0.phi.grid) < sp * 1e-3) & ball).sum())}, "
      f"iface free (neither mask) {int(((np.abs(g0.phi.grid) < sp * 1e-3) & ball & ~g0.phi.hard_mask_air & ~g0.phi.hard_mask_solid).sum())}")


def count(stage, grid):
    print(f"LAB {stage}: {int(((np.asarray(grid) < 0) != s0)[ball].sum())} cells changed side in the ball, "
          f"{int(((np.asarray(grid) < 0) != s0).sum())} anywhere")


def wrap(mod, name, after):
    assert hasattr(mod, name), f"{mod.__name__} has no {name}"
    f = getattr(mod, name)

    def w(*a, **k):
        r = f(*a, **k)
        after(a, r)
        return r
    setattr(mod, name, w)


# Looked up at call time: hj_update and wall_guard as phi_updater globals; enforce_machinability,
# drop_thin_strips and close_pinches imported inside apply_adjoint_to_unified from unified_phi.
G = {}
wrap(pu, "hj_update", lambda a, r: (print(f"LAB speed in ball: max {float(np.abs(a[1][ball]).max()):.3e}, "
                                          f"nonzero {int((a[1][ball] != 0).sum())}") if "sp" not in G else None,
                                    G.setdefault("sp", 1), count("hj_update", a[0].grid)))
wrap(pu, "wall_guard", lambda a, r: count(f"wall_guard ok={r[1]}", r[0] if r[1] else a[0]))
wrap(up, "enforce_machinability", lambda a, r: count(f"machinability filled={r}", a[0].phi.grid))
wrap(up, "drop_thin_strips", lambda a, r: count(f"thin strips={r}", a[0].phi.grid))
wrap(up, "close_pinches", lambda a, r: count(f"pinches={r}", a[0].phi.grid))
g, reps = carve.carve(lay, [{"bumps": [{"c_mm": c.tolist(), "amp_mm": amp, "sigma_mm": 10.0}], "unit": False}],
                      spacing_mm=sp)
count("returned", g.phi.grid)
print(f"LAB report: {reps[0]}")
