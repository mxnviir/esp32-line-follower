"""What the CNC actually makes from a design, and what that car weighs and does.

design (3 mm half grid) -> smooth 1 mm surface (trilinear + 1 mm blur, so the 3 mm
staircase does not turn into fake corners) -> rule zones and cargo re-applied -> Part 1's
machining rule (team process: 3-axis, 6.35 mm ball end, setups top/bottom/left/right):
any air the ball cannot clear stays foam -> one piece with the spine (and no sealed voids).
Only the sidepod region is touched; the rest of the trial body is kept exactly as drawn.

The milled 1 mm body gives the exact foam mass and COM; its 3 mm version goes in the tunnel.
"""
import sys
import numpy as np
from pathlib import Path
from scipy import ndimage

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "part1-simulation"))
import machining as MC                                         # noqa: E402
import region as RG                                            # noqa: E402

xs, ys, zs, BODY1, WHEELS1 = RG.load_1mm()
X1, Y1, Z1 = np.meshgrid(xs, ys, zs, indexing="ij")
AY = np.abs(Y1)
BOX = ((X1 >= RG.REGION_X[0]) & (X1 <= RG.REGION_X[1]) & (AY <= RG.REGION_YMAX)
       & (Z1 >= RG.REGION_Z[0]) & (Z1 <= RG.REGION_Z[1]))
_dy = np.clip(AY - RG.FRONT_INNER_Y, 0, None)
T792 = (AY >= RG.FRONT_INNER_Y) & (X1 >= RG.X_FRONT_AXLE - RG.R_WHEEL - (15 + _dy / np.tan(np.radians(60)))) & (X1 <= RG.X_FRONT_AXLE)
_dy = np.clip(AY - RG.REAR_INNER_Y, 0, None)
T793 = (AY >= RG.REAR_INNER_Y) & (X1 <= RG.X_REAR_AXLE + RG.R_WHEEL + 5 + _dy) & (X1 >= RG.X_REAR_AXLE)
HALO = (X1 >= RG.HALO_X[0]) & (Z1 > RG.HALO_ZMIN)
SPINE = BODY1 & (AY <= RG.SPINE_Y) & (Z1 >= RG.SPINE_Z)
_hw = 5.0 + (X1 - RG.CARGO_X[0]) / (RG.CARGO_X[1] - RG.CARGO_X[0]) * 22.5
CARGO = ((X1 >= RG.CARGO_X[0]) & (X1 <= RG.CARGO_X[1]) & (AY <= _hw)
         & (Z1 >= RG.CARGO_Z[0]) & (Z1 <= RG.CARGO_Z[1]))
REGION = BOX & ~T792 & ~T793 & ~HALO & ~SPINE
KEEP = BODY1 & ~REGION                                          # trial body outside the region


def smooth_1mm(car, half):
    """3 mm half body -> smooth whole body on the 1 mm grid (region only)."""
    full = car.full(half).astype(np.float32)
    up = ndimage.zoom(full, 3, order=1)
    up = ndimage.gaussian_filter(up, 1.0)
    out = np.zeros(BODY1.shape, np.float32)
    j0 = np.searchsorted(ys, -car.ys[-1] - 1.5)
    nx = min(up.shape[0], out.shape[0]); ny = min(up.shape[1], out.shape[1] - j0); nz = min(up.shape[2], out.shape[2])
    out[:nx, j0:j0 + ny, :nz] = up[:nx, :ny, :nz]
    return out > 0.5


def mill(car, half):
    """The body the team's mill would leave (whole car, 1 mm, bool) and a report."""
    D = smooth_1mm(car, half)
    B = KEEP | (D & REGION) | CARGO
    added = 0
    for _ in range(3):                                          # machining can expose new corners
        stuck = ~B & ~MC.reachable_air(~B, MC.TOOL_R_MM) & REGION
        n = int(stuck.sum())
        if n == 0:
            break
        B |= stuck; added += n
    B = ndimage.binary_fill_holes(B) & (B | REGION)             # sealed voids can't be cut: foam
    lab, _ = ndimage.label(B)
    keep = np.unique(lab[SPINE & B]); keep = keep[keep > 0]
    B = np.isin(lab, keep)                                      # anything loose is not made
    return B, dict(uncut_foam_mm3=added)


def mass_1mm(B, scorer):
    """Exact foam mass and whole-car COM of a 1 mm body (lead fills to 48.2 g)."""
    foam = B.sum() * 1e-3 * RG.FOAM_G_CM3
    fx, fz = X1[B].mean(), Z1[B].mean()
    lead = max(0.0, scorer.__class__.__module__ and 0.0)
    from score import TARGET_G, LEAD_CAP_G, BALLAST_XZ
    lead = max(0.0, TARGET_G - scorer.other_g - foam)
    tot = foam + scorer.other_g + lead
    mx = foam * fx + scorer.other_g * scorer.other_xz[0] + lead * BALLAST_XZ[0]
    mz = foam * fz + scorer.other_g * scorer.other_xz[1] + lead * BALLAST_XZ[1]
    return dict(foam_g=foam, ballast_g=lead, total_g=tot, com_x=mx / tot, com_z=mz / tot,
                mass_legal=lead <= LEAD_CAP_G)


def to_half3(car, B):
    """1 mm whole body -> 3 mm half grid (the tunnel's)."""
    j0 = np.searchsorted(ys, -car.ys[-1] - 1.5)
    nyc = 2 * len(car.ys) * 3
    sub = B[:, j0:j0 + nyc, :]
    c = RG.coarse(sub)
    nx, ny, nz = car.body.shape
    out = np.zeros((nx, 2 * ny, nz), bool)
    out[: min(nx, c.shape[0]), : min(2 * ny, c.shape[1]), : min(nz, c.shape[2])] = c[:nx, : 2 * ny, :nz]
    return out[:, ny:]
