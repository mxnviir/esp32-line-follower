"""The car, the sidepod design region and the scorer's geometry, on one 3 mm grid.

STEP frame: x forward (nose at +x), y left, z up, mm. Front axle x = 173.25, rear 35.25.
The design is done on the y >= 0 half and mirrored (the car is symmetric).

Region (per side), from the team's sketch and the 2026-27 regulations:
  box     x 49.4..159.1 (between the wheels), 0 <= y <= 32.5 (T1.14 block half-width),
          z 1.5..40 (T3.7 clearance at the bottom; the deck above stays)
  minus   T7.9.2 wedge behind the front wheel (15 mm at the inner edge, 60 deg),
          T7.9.3 wedge ahead of the rear wheel (5 mm, 45 deg),
          above z = 27 for x >= 115 (T4.4.2: the halo must be seen from the side) -> AIR
  fixed   the spine: original body at |y| <= 13.5, z >= 17 (deck, halo, cockpit)
  must    T4.2 virtual cargo: 60 mm wedge, 55 -> 10 mm wide, 10 mm tall, wide end
          forward, x 76..136, z 17..27: the layer the trial car is solid across its full
          width (the car has a tunnel under the spine below z 17.5)  -> forced SOLID
Everything else of the original body outside the region is kept as it is.
"""
from __future__ import annotations
import numpy as np
from pathlib import Path
from scipy import ndimage

HERE = Path(__file__).resolve().parent
H = 3.0                                  # mm per cell (design + LBM)
X_FRONT_AXLE, X_REAR_AXLE, R_WHEEL = 173.25, 35.25, 14.12
FRONT_INNER_Y, REAR_INNER_Y = 19.25, 16.25
REGION_X = (49.4, 159.1)
REGION_YMAX = 32.5
REGION_Z = (1.5, 40.0)
SPINE_Y, SPINE_Z = 13.5, 17.0
CARGO_X = (76.0, 136.0)                  # narrow end at 76, wide end (55 mm) at 136
CARGO_Z = (17.0, 27.0)                   # the layer that is solid full-width on the trial car
FOAM_G_CM3 = 0.163
HALO_X, HALO_ZMIN = (115.0, 160.0), 27.0      # halo ring x 120-160, z 28-38 on this STEP


def load_1mm():
    d = np.load(HERE / "cad/vox1mm.npz")
    xs, ys, zs = d["xs"], d["ys"], d["zs"]
    body = d["car_body"]
    wheels = d["wheel_rl"] | d["wheel_fl"] | d["wheel_lr"] | d["wheel_fr"]
    return xs, ys, zs, body, wheels


def coarse(a1, f=3):
    """1 mm bool grid -> 3 mm grid (a cell is solid if over half of its 27 sub-cells are)."""
    nx, ny, nz = (s // f for s in a1.shape)
    a = a1[: nx * f, : ny * f, : nz * f].reshape(nx, f, ny, f, nz, f)
    return a.mean((1, 3, 5)) > 0.5


class Car:
    """Everything on the 3 mm half grid (y >= 0)."""

    def __init__(self):
        xs, ys, zs, body, wheels = load_1mm()
        jy = np.searchsorted(ys, 0.0)                    # first y > 0 (ys are cell centres)
        body, wheels, ys = body[:, jy:], wheels[:, jy:], ys[jy:]
        n = 3
        self.body = coarse(body); self.wheels = coarse(wheels)
        self.xs = xs[: self.body.shape[0] * n].reshape(-1, n).mean(1)
        self.ys = ys[: self.body.shape[1] * n].reshape(-1, n).mean(1)
        self.zs = zs[: self.body.shape[2] * n].reshape(-1, n).mean(1)
        X, Y, Z = np.meshgrid(self.xs, self.ys, self.zs, indexing="ij")
        self.X, self.Y, self.Z = X, Y, Z
        box = ((X >= REGION_X[0]) & (X <= REGION_X[1]) & (Y <= REGION_YMAX)
               & (Z >= REGION_Z[0]) & (Z <= REGION_Z[1]))
        halo_side = (X >= HALO_X[0]) & (Z > HALO_ZMIN)          # T4.4.2: keep the halo visible from the side
        xf_rear_face = X_FRONT_AXLE - R_WHEEL
        dy = np.clip(Y - FRONT_INNER_Y, 0, None)
        t792 = (Y >= FRONT_INNER_Y) & (X >= xf_rear_face - (15.0 + dy / np.tan(np.radians(60)))) & (X <= X_FRONT_AXLE)
        xr_front_face = X_REAR_AXLE + R_WHEEL
        dy = np.clip(Y - REAR_INNER_Y, 0, None)
        t793 = (Y >= REAR_INNER_Y) & (X <= xr_front_face + (5.0 + dy)) & (X >= X_REAR_AXLE)
        self.forbid = (t792 | t793 | halo_side) & box
        self.spine = self.body & (Y <= SPINE_Y) & (Z >= SPINE_Z)
        half_w = 5.0 + (X - CARGO_X[0]) / (CARGO_X[1] - CARGO_X[0]) * (27.5 - 5.0)
        self.cargo = ((X >= CARGO_X[0]) & (X <= CARGO_X[1]) & (Y <= half_w)
                      & (Z >= CARGO_Z[0]) & (Z <= CARGO_Z[1]))
        self.region = box & ~self.forbid & ~self.spine          # cells a method may choose
        fixed = (self.body & ~box) | (self.spine & box)         # original body kept as is
        lab, n = ndimage.label(fixed)                           # drop 3 mm-coarsening crumbs
        big = np.argmax(ndimage.sum(fixed, lab, range(1, n + 1))) + 1
        self.fixed = lab == big
        self.body = self.body & ~(fixed & ~self.fixed)
        self.spine = self.spine & self.fixed
        self.original = self.body.copy()
        self.must = self.cargo
        # normalised coordinates over the region (inputs for CPPNs / bases)
        self.xn = (X - 0.5 * sum(REGION_X)) / (0.5 * (REGION_X[1] - REGION_X[0]))
        self.yn = Y / REGION_YMAX
        self.zn = (Z - 0.5 * sum(REGION_Z)) / (0.5 * (REGION_Z[1] - REGION_Z[0]))

    # ---------------------------------------------------------------- finishing
    def finish(self, field, tool_cells=1):
        """Design field (positive = solid) -> whole legal half body, or None.
        Like Part 1: rule zones forced, cargo forced, made millable (closing then opening
        with the tool), kept only if joined to the rest of the car (one piece)."""
        s = (field > 0) & self.region
        s |= self.must
        s = (ndimage.binary_closing(s, iterations=tool_cells) & self.region) | self.must
        s = ndimage.binary_opening(s, iterations=tool_cells) | self.must
        body = (s & self.region) | self.fixed | self.must
        lab, n = ndimage.label(body)
        ids = set(np.unique(lab[self.fixed])) - {0}
        if len(ids) != 1 or not (lab[self.must] == next(iter(ids))).all():
            return None                      # cargo or deck cut loose
        return lab == next(iter(ids))

    def full(self, half):
        """Half grid -> both halves (for pictures and mass)."""
        return np.concatenate([half[:, ::-1], half], 1)

