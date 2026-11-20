"""Millable sidepods by CMA-ES, DRAG ONLY, scored by the porous-model drag proxy (ESI primal).

Why not the adjoint: its per-cell topology gradient failed a finite-difference check on this car
(signs wrong on 3 mm surface moves; topo/mill_coarse/fdcheck.json). The model's own verdict on a
whole design is what passed its known-answer test (team's sidepod worth -24.5 mN, as body-fitted).

Design: top and bottom surfaces of the pod, each a smooth bicubic surface through a 6 x 3 grid of
control heights over the region's plan view (x along the car, |y| outward) = 36 variables.
Height above the region floor; material only where top > bottom. Every candidate goes through
mill_topo.Columns.project: region only, ceiling 27.0 mm, thickness 0 or >= 3 mm, loose pieces
deleted, milled from top and bottom with the 3.175 mm ball, 3 mm minimum wall.
Objective: dissipated power (drag proxy) after N warm primal iterations from a fixed base flow.

    python topo/mill_cma.py <case> --hours 3 --popsize 12
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.interpolate import RectBivariateSpline

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
import mill_topo as M  # noqa: E402

NX, NY = 6, 3


class Param:
    def __init__(self, cols):
        self.cols = cols
        act = cols.active
        xi = np.nonzero(act.any(1))[0]; yi = np.nonzero(act.any(0))[0]
        self.xr = (xi.min(), xi.max()); self.yr = (yi.min(), yi.max())
        self.cx = np.linspace(*self.xr, NX); self.cy = np.linspace(*self.yr, NY)
        self.gx = np.arange(act.shape[0]); self.gy = np.arange(act.shape[1])
        self.room = np.where(act, cols.zhi - cols.zlo, 0.0)

    def surf(self, ctrl):
        s = RectBivariateSpline(self.cx, self.cy, ctrl.reshape(NX, NY), kx=3, ky=2)
        return s(self.gx, self.gy)

    def design(self, x):
        """x: 36 values in mm (18 top heights, 18 bottom heights above the region floor)."""
        cols = self.cols
        top = np.clip(self.surf(x[:NX * NY]), 0, None)
        bot = np.clip(self.surf(x[NX * NY:]), 0, None)
        zt = np.where(cols.active, cols.zlo + np.minimum(top, self.room), cols.zlo)
        zb = np.where(cols.active, cols.zlo + np.minimum(bot, self.room), cols.zlo)
        zt = np.maximum(zt, zb)
        return cols.project(zb, zt)


def best_legal(case, top=40):
    """The best-scored design that passes every rule when built ONCE from its own variables
    (projection is not idempotent, so a design is always rebuilt from x, never re-projected)."""
    import json as _j
    case = Path(case)
    cols = M.Columns(case); P = Param(cols)
    rows = sorted((_j.loads(l) for l in open(case / "cma_log.jsonl")), key=lambda r: r["J"])
    for r in rows[:top]:
        x = np.array(r["x"]); zb, zt, B, rep = P.design(x)
        if cols.car.check(B)["ok"] and (B & cols.reg & ~cols.lean).any():
            return x, r, (zb, zt, B, rep), cols, P
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case")
    ap.add_argument("--hours", type=float, default=3.0)
    ap.add_argument("--popsize", type=int, default=12)
    ap.add_argument("--sigma", type=float, default=6.0, help="mm")
    ap.add_argument("--iters", type=int, default=800)
    ap.add_argument("--x0", default="none", choices=["none", "slab"])
    a = ap.parse_args()
    import cma
    case = Path(a.case)
    cols = M.Columns(case)
    P = Param(cols)
    x0 = np.zeros(2 * NX * NY)
    if a.x0 == "slab":
        x0[:NX * NY] = 12.0
    log = case / "cma_log.jsonl"
    es = cma.CMAEvolutionStrategy(x0, a.sigma, {"popsize": a.popsize, "bounds": [-15, 45], "seed": 1, "verbose": -9})
    t_end = time.time() + a.hours * 3600
    best = (None, np.inf)
    gen = 0
    cache = {}
    while not es.stop() and time.time() < t_end:
        X = es.ask()
        F = []
        for x in X:
            zb, zt, B, rep = P.design(np.asarray(x))
            key = np.packbits((B & cols.reg)).tobytes()
            if key in cache:                                       # same milled pod: same score
                J = cache[key]; secs = 0.0
            else:
                J, _, _, _, secs = M.one_cycle(case, cols, zb, zt, a.iters, 1, warm=False)
                cache[key] = J
            F.append(J)
            vol = float((B & cols.reg).sum() * 1e-3)
            rec = {"gen": gen, "J": J, "pod_cm3_both_sides": vol, "secs": round(secs, 1),
                   "loose_deleted_mm3": rep["loose_deleted_mm3"], "uncut_filled_mm3": rep["uncut_foam_mm3"], "x": list(map(float, x))}
            with open(log, "a") as f:
                f.write(json.dumps(rec) + "\n")
            if J < best[1]:
                best = (np.asarray(x), J)
                np.savez(case / "cma_best.npz", zb=zb, zt=zt, x=np.asarray(x), J=J)
            if time.time() > t_end:
                break
        if len(F) == len(X):
            es.tell(X, F)
        print(json.dumps({"gen": gen, "best_J": best[1], "gen_min": min(F), "gen_median": float(np.median(F)),
                          "evals": len(cache), "t": time.strftime("%H:%M:%S")}), flush=True)
        gen += 1


if __name__ == "__main__":
    main()
