"""Does each design the methods hand over make a real car?

For every reference and every method's best design (whole car, both sides, 1 mm grid):
  weight    foam, lead, total (T3.6 >= 48.0 g); lead within the 15.7 g container
  one piece connected components of the whole body; volume of anything floating
  voids     air sealed inside the body (no cutter can reach it)
  CNC       Part 1's own machinability test (team process: 3-axis, 6.35 mm ball end, four
            setups top/bottom/left/right). Air the cutter cannot clear is foam left behind:
            the body you would actually mill is the design PLUS that foam.
  walls     foam thinner than the team's 3 mm wall (an opening by a 1.5 mm ball removes it)
  wheels    nearest foam to each wheel, and T3.7 clearance (>= 1.5 mm above the track)
The milled body (design + uncut foam) is then re-weighed.
"""
import json, sys, glob
import numpy as np
from pathlib import Path
from scipy import ndimage

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "part1-simulation"))
import machining as MC                                     # noqa: E402
from region import Car, load_1mm, FOAM_G_CM3             # noqa: E402
from score import Scorer, TARGET_G, LEAD_CAP_G             # noqa: E402

car = Car()
xs, ys, zs, body1, wheels1 = load_1mm()
base = json.loads((HERE / "results/base.json").read_text())
sc = Scorer(car, base["drag_A"], base["lift_A"])
other_g = sc.other_g


def to_1mm(half):
    """3 mm half body -> 1 mm whole body on the STEP's 1 mm grid (nearest cell)."""
    full = car.full(half)                                   # y from -39 to +39 in 3 mm cells
    up = full.repeat(3, 0).repeat(3, 1).repeat(3, 2)
    out = np.zeros_like(body1)
    nx = min(up.shape[0], out.shape[0]); nz = min(up.shape[2], out.shape[2])
    j0 = np.searchsorted(ys, -car.ys[-1] - 1.5)             # first 1 mm cell of the 3 mm grid
    ny = min(up.shape[1], out.shape[1] - j0)
    out[:nx, j0:j0 + ny, :nz] = up[:nx, :ny, :nz]
    return out


def region_1mm():
    X, Y, Z = np.meshgrid(xs, np.abs(ys), zs, indexing="ij")
    import region as RG
    return ((X >= RG.REGION_X[0]) & (X <= RG.REGION_X[1]) & (Y <= RG.REGION_YMAX)
            & (Z >= RG.REGION_Z[0]) & (Z <= RG.REGION_Z[1]))


REG = region_1mm()
Xg, Yg, Zg = np.meshgrid(xs, ys, zs, indexing="ij")


def check(half):
    B = to_1mm(half)
    out = {}
    lab, n = ndimage.label(B)
    sizes = ndimage.sum(B, lab, range(1, n + 1))
    out["pieces"] = int(n)
    out["floating_mm3"] = float(sizes.sum() - sizes.max()) if n else 0.0
    filled = ndimage.binary_fill_holes(B)
    out["sealed_voids_mm3"] = float((filled & ~B).sum())
    # CNC: air the ball can't clear, inside the block's footprint (Part 1's own test)
    A = ~B
    r = MC.TOOL_R_MM                                        # 1 mm grid: r in cells = mm
    reach = MC.reachable_air(A, r)
    reach_any = MC.reachable_air(A, r, any_side=True)
    stuck = A & ~reach
    # inside corners the ball can't fit into from ANY direction: a 3.175 mm fillet, harmless
    out["corner_fillet_mm3"] = float((A & ~reach_any & REG).sum())
    # the ball fits but no top/bottom/left/right line reaches it: a true undercut
    out["undercut_mm3"] = float((reach_any & ~reach & REG).sum())
    out["uncut_air_in_region_mm3"] = float((stuck & REG).sum())
    milled = B | (stuck & REG)                              # what the mill leaves in the region
    # walls thinner than 3 mm in the region
    # thin: foam more than 1 mm from what survives an opening by a 1.5 mm-radius ball (corners
    # of the staircase lose < 1 mm; a plate thinner than 3 mm vanishes entirely)
    k = np.arange(-2, 3); ball = (k[:, None, None] ** 2 + k[None, :, None] ** 2 + k[None, None, :] ** 2) <= 2.25
    op = ndimage.binary_opening(B, ball)
    thin = B & REG & (ndimage.distance_transform_edt(~op) > 1.0)
    out["thin_wall_mm3"] = float(thin.sum())
    # wheels and track
    dw = ndimage.distance_transform_edt(~wheels1)
    pod = B & REG
    out["nearest_wheel_mm"] = float(dw[pod].min()) if pod.any() else None
    out["lowest_pod_z_mm"] = float(Zg[pod].min() - 0.5) if pod.any() else None
    # weights: design as scored (3 mm accounting) and as milled (1 mm)
    m = sc.mass(half)
    out["scored"] = {k: round(float(v), 2) for k, v in m.items()}
    d_g = (milled.sum() - B.sum()) * 1e-3 * FOAM_G_CM3
    foam_m = m["foam_g"] + d_g
    lead = max(0.0, TARGET_G - other_g - foam_m)
    out["milled"] = dict(foam_g=round(foam_m, 2), lead_g=round(lead, 2),
                         total_g=round(foam_m + other_g + lead, 2), extra_foam_g=round(d_g, 2),
                         lead_fits=bool(lead <= LEAD_CAP_G))
    ok = (n == 1 and out["sealed_voids_mm3"] == 0 and out["milled"]["lead_fits"]
          and out["milled"]["total_g"] < 48.2 + 0.3 and out["undercut_mm3"] < 200 and out["thin_wall_mm3"] < 200)
    out["verdict"] = "OK" if ok else "PROBLEM"
    return out


if __name__ == "__main__":
    res = {}
    items = [("STEP trial car @1mm", None)] if len(sys.argv) > 1 else []
    items += [(f"ref:{p.stem[4:]}", np.load(p)) for p in sorted((HERE / "results").glob("ref_*.npy"))]
    items += [(p.stem.replace("_best", ""), np.load(p, allow_pickle=True)) for p in sorted((HERE / "results/runs").glob("*_best.npy"))]
    for name, half in items:
        if half is None:
            B = body1.copy(); A = ~B
            ra = MC.reachable_air(A, MC.TOOL_R_MM); rany = MC.reachable_air(A, MC.TOOL_R_MM, any_side=True)
            print(name, "undercut", int((rany & ~ra & REG).sum()), "fillet", int((A & ~rany & REG).sum()), "pieces", ndimage.label(B)[1])
            continue
        if half.dtype == object:
            continue
        res[name] = check(half)
        r = res[name]
        print(f"{name:22s} {r['verdict']:8s} pieces {r['pieces']} float {r['floating_mm3']:.0f} voids {r['sealed_voids_mm3']:.0f} "
              f"undercut {r['undercut_mm3']:.0f} fillet {r['corner_fillet_mm3']:.0f} mm3  thin {r['thin_wall_mm3']:.0f}  "
              f"scored {r['scored']['total_g']} g (lead {r['scored']['ballast_g']})  milled {r['milled']['total_g']} g "
              f"(lead {r['milled']['lead_g']}, +{r['milled']['extra_foam_g']} g foam)  wheel gap {r['nearest_wheel_mm']}  low z {r['lowest_pod_z_mm']}", flush=True)
    (HERE / "results/checks.json").write_text(json.dumps(res, indent=1))
