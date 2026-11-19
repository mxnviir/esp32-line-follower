"""p1_substep_lab: what ends a carve's sub-step loop, and what the final wall check holds
(exactspeed2 review, 2026-11-17: bias -1 at 2 mm went from 6 sub-steps / -1792 cells to 2 / -13).
For one edit it prints, per HJ sub-step: dt, max |V| in the band, the interface move (p90, max,
where the max is and |grad phi| there), the sub-step wall guard (ok, cells _thinned flags), and
islands dropped. Then the final guard: cells _thinned flags against the field as given (entry) and
against the redistanced start (phi0), the first 20 as x, y, z mm and wall before -> after mm, how
many cells the freeze changed, and solid counts at each stage.

    python ../.github/lab/p1_substep_lab.py <spacing_mm> <bias_mm> [trust_mm] [x,y,z mm: a sigma-10 bump of amp bias_mm there]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd().parent / "part1-simulation"))
import numpy as np  # noqa: E402

import carve  # noqa: E402
import phi_updater as pu  # noqa: E402

sp, bias = float(sys.argv[1]), float(sys.argv[2])
trust = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
C = np.array([float(v) for v in sys.argv[4].split(",")]) * 1e-3 if len(sys.argv) > 4 else None   # bump centre, m
d = sp * 1e-3
st = {"k": 0, "entry": None, "phi0": None, "on": False}


def rows(before, after, bad, n=20):
    h0, h1 = pu._wall_half(before, d) * 2e3, pu._wall_half(after, d) * 2e3
    return [(c[0] * sp, c[1] * sp, c[2] * sp, round(float(h0[tuple(c)]), 2), round(float(h1[tuple(c)]), 2))
            for c in np.argwhere(bad)[:n]]


_reinit = pu.reinitialise_sdf


def reinit(phi, *a, **k):
    if not st["on"]:
        return _reinit(phi, *a, **k)
    if st["entry"] is None:
        st["entry"] = np.asarray(phi.grid, np.float64).copy()
    _reinit(phi, *a, **k)
    if st["phi0"] is None:
        st["phi0"] = np.asarray(phi.grid, np.float64).copy()
        e, p = st["entry"], st["phi0"]
        bad = pu._thinned(e, p, d, 3.0e-3)
        print(f"LAB entry redistance: max |dphi| {np.abs(p - e).max() * 1e3:.3f} mm, sign flips {int(((p < 0) != (e < 0)).sum())}, "
              f"thinned vs entry {int(bad.sum())}: {rows(e, p, bad)}")
        print(f"LAB thin (<3.0) cells: entry {int((pu._wall_half(e, d) < 1.5e-3).sum())}, phi0 {int((pu._wall_half(p, d) < 1.5e-3).sum())}")


pu.reinitialise_sdf = reinit
_hj = pu.hj_update


def hj(phi, V, dt):
    b = np.asarray(phi.grid, np.float64).copy()
    _hj(phi, V, dt)
    a = np.asarray(phi.grid, np.float64)
    ifc = np.abs(st["phi0"]) < d
    m = np.abs(a - st["phi0"])[ifc]
    i = np.argwhere(ifc)[m.argmax()]
    gz = np.linalg.norm(np.gradient(b, d), axis=0)[tuple(i)]
    st["k"] += 1
    if C is not None:
        ci = tuple(np.clip(np.rint((C - np.asarray(phi.bv.origin_m)) / d).astype(int), 0, np.array(a.shape) - 1))
        print(f"LAB centre cell {ci}: V {float(V[ci]):+.4e}, dt*V {dt * float(V[ci]) * 1e3:+.4f} mm, dphi {(a[ci] - b[ci]) * 1e3:+.4f} mm (vs phi0 {(a[ci] - st['phi0'][ci]) * 1e3:+.4f}), phi {a[ci] * 1e3:+.3f} mm")
    print(f"LAB sub-step {st['k']}: dt {dt:.4g}, max|V| band {float(np.abs(V[np.abs(b) < 2 * d]).max()):.3e}, "
          f"move vs phi0 p90 {np.percentile(m, 90) * 1e3:.3f} max {m.max() * 1e3:.3f} mm at {(i * sp).tolist()} |grad phi| {gz:.2f}, "
          f"solid {int((a < 0).sum())}")


pu.hj_update = hj
_wg = pu.wall_guard


def wg(before, g, spacing, mw, mode=None, tries=8):
    bad = pu._thinned(before, g, spacing, mw)
    r, ok = _wg(before, g, spacing, mw, mode=mode, tries=tries)
    tag = "final" if mode == "freeze" else "sub-step"
    print(f"LAB wall_guard {mode or pu.WALL_GUARD} ({tag}): flagged {int(bad.sum())}, ok {ok}, cells changed by it "
          f"{int((np.asarray(r) != np.asarray(g)).sum())}, solid in {int((g < 0).sum())} out {int((np.asarray(r) < 0).sum())}; "
          f"first {rows(before, g, bad)}")
    if mode == "freeze" and st["phi0"] is not None:
        b0 = pu._thinned(st["phi0"].astype(g.dtype), g, spacing, mw)
        print(f"LAB   same field vs phi0 instead: flagged {int(b0.sum())}")
    return r, ok


pu.wall_guard = wg
_aa = pu.apply_adjoint_to_unified


def aa(*a, **k):                     # only the cut's own redistancing, not start_block's clean
    st["on"] = True
    try:
        return _aa(*a, **k)
    finally:
        st["on"] = False


pu.apply_adjoint_to_unified = aa
lay = {"W": 120.3, "x_front": 46.0, "d_halo": 43.72}
edit = ({"bumps": [{"c_mm": (C * 1e3).tolist(), "amp_mm": bias, "sigma_mm": 10.0}], "unit": False} if C is not None
        else {"bias_mm": bias, "trust_mm": trust})
g, reps = carve.carve(lay, [edit], spacing_mm=sp)
if C is not None:
    print(f"LAB designed speed at the centre: {bias:+.3f} mm (amp; nearest vertex = centre for a mode centre)")
print(f"LAB report: {reps[0]}")
