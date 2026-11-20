"""Final check of the evolved millable sidepods (drag only):
  1. body-fitted coarse CFD of the milled best design (vs coarse team / no-sidepod, measured earlier)
  2. the 917 k-cell porous model: team's sidepod vs the best design, same settings, same start flow
  3. body-fitted medium CFD of the milled best design (vs the gate's medium team car)
Writes topo/mill_final.json step by step.

    python topo/mill_final.py [--steps 1,2,3]
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SP = HERE.parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(SP))
import mill_topo as M  # noqa: E402

OUT = HERE / "mill_final.json"


def save(res):
    OUT.write_text(json.dumps(res, indent=1, default=float))


def team_surfaces(cols):
    car = cols.car
    P = (car.body0 & cols.reg & ~cols.lean)[:, cols.ypos, :]
    has = P.any(2)
    Zc = car.zs
    zb = np.where(has, Zc[np.argmax(P, 2)] - 0.5 * car.h, cols.zlo)
    zt = np.where(has, Zc[P.shape[2] - 1 - np.argmax(P[:, :, ::-1], 2)] + 0.5 * car.h, zb)
    return zb, zt


def body_fitted(cols, B, res, tag):
    import gate
    car = cols.car
    chk = car.check(B)
    out = HERE / f"final_{tag}_{res}"
    car.export_car_folder(car.body_mesh_for(B), out, tag)
    t = time.time()
    half, health, secs = gate.solve(out, M.NP, 2000, extra={"resolution": res})
    full = half.to_full_car()
    return {"D20_N": float(full.D20), "L20_N": float(full.L), "converged": bool(health.converged),
            "wall_s": round(time.time() - t), "check_ok": chk["ok"], "pod_cm3_both_sides": float((B & cols.reg).sum() * 1e-3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", default="1,2,3")
    a = ap.parse_args()
    steps = set(a.steps.split(","))
    res = json.loads(OUT.read_text()) if OUT.exists() else {}
    import mill_cma as C
    x, row, (bzb_c, bzt_c, Bc, _), cols_c, Pc = C.best_legal(HERE / "mill_coarse")   # best that passes every rule
    res["best_coarse_porous_J"] = row["J"]; res["best_gen"] = row["gen"]; res["best_x"] = list(map(float, x))
    if "1" in steps:
        res["coarse_bodyfitted_best"] = body_fitted(cols_c, Bc, "coarse", "best")
        res["coarse_bodyfitted_refs"] = {"team_D20_N": json.loads((SP / "gate_results_coarse/base.json").read_text())["full_D20_N"],
                                         "no_sidepod_D20_N": 2 * json.loads((HERE / "lean_bodyfitted_coarse.json").read_text())["D20_half_N"]}
        save(res); print(json.dumps(res["coarse_bodyfitted_best"]), flush=True)
    if "2" in steps:
        case = HERE / "mill_1m"
        cols = M.Columns(case)
        out = {}
        tzb, tzt = team_surfaces(cols)
        tzb, tzt, _, _ = cols.project(tzb, tzt)          # the team's pod, under the same rules
        J, *_ , secs = M.one_cycle(case, cols, tzb, tzt, 1500, 1, warm=True)       # team first: also the start flow
        out["team"] = {"J": J, "secs": round(secs)}
        save({**res, "1M_porous": out}); print("1M team", out["team"], flush=True)
        bzb, bzt, Bb, _ = C.Param(cols).design(x)                                  # same x, built once on this mesh's columns
        J, *_, secs = M.one_cycle(case, cols, bzb, bzt, 1000, 1, warm=False)
        out["best"] = {"J": J, "secs": round(secs)}
        out["best_minus_team_pct"] = 100 * (out["best"]["J"] - out["team"]["J"]) / out["team"]["J"]
        res["1M_porous"] = out
        save(res); print("1M best", out["best"], flush=True)
    if "3" in steps:
        res["medium_bodyfitted_best"] = body_fitted(cols_c, Bc, "medium", "best")
        res["medium_bodyfitted_refs"] = {"team_D20_N": 2 * json.loads((SP / "gate_results/base.json").read_text())["D20_half_N"]}
        save(res); print(json.dumps(res["medium_bodyfitted_best"]), flush=True)
    print("FINAL_DONE", flush=True)


if __name__ == "__main__":
    main()
