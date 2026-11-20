"""Score DAFoam's surface gradient against the gate's measured bumps (gate_results/judge.json).

Each bump's shape change is known per vertex of the gate's base STL (bump STL minus base STL, same
vertex order). It is interpolated onto DAFoam's surface points (inverse distance, 4 nearest), and the
predicted change is exact first order:  dD = sum_i dD/dXs_i . dX_i.
Same three readings as gate.py judge:
- rows: each bump against the zero run;
- pairs: (D+ - D-)/2, which needs no zero run;
- Part 3's pass marks (r >= 0.9, signs >= 80 %), plus a count by independent shape.

    python dafoam/judge.py gate/dafoam_case/dafoam_sens.npz [--tag name]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import trimesh
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parent
SP = HERE.parent
G = SP / "gate"
R = SP / "gate_results"


def displacement_at(points, base_v, disp, k=4):
    d, i = cKDTree(base_v).query(points, k=k)
    w = 1.0 / np.maximum(d, 1e-9) ** 2
    w /= w.sum(1, keepdims=True)
    return (disp[i] * w[..., None]).sum(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sens")
    ap.add_argument("--tag", default="dafoam")
    a = ap.parse_args()
    S = np.load(a.sens)
    X, Gd, D = S["Xs"], S["dD_dXs"], float(S["D_N"])
    base = trimesh.load(G / "original_rm" / "car_half.stl", process=False)
    J = json.loads((R / "judge.json").read_text())
    base_D = json.loads((R / "base.json").read_text())["D20_half_N"]
    rows = []
    for r in J["rows"]:
        k = r["bump"]
        bm = trimesh.load(G / f"bump_{k}" / "car_half.stl", process=False)
        if len(bm.vertices) != len(base.vertices):
            print(f"skip {k}: vertex count differs", file=sys.stderr)
            continue
        dX = displacement_at(X, base.vertices, bm.vertices - base.vertices)
        pred = float((Gd * dX).sum()) * 1e3
        rows.append({"bump": k, "site": r.get("site"), "amp_mm": r.get("amp_mm"), "measured_mN": r["measured_mN"],
                     "predicted_mN": pred, "stderr_mN": r.get("stderr_mN"), "usable": r.get("usable", True)})
    use = [r for r in rows if r["usable"] and abs(r["amp_mm"] or 1) >= 0.1]
    m = np.array([r["measured_mN"] for r in use]); p = np.array([r["predicted_mN"] for r in use])
    out = {"tag": a.tag, "D_half_N_dafoam": D, "D20_half_N_stateA": base_D,
           "primal_mismatch_pct": 100 * (D - base_D) / base_D,
           "rows": rows,
           "map": {"pearson_r": float(np.corrcoef(m, p)[0, 1]) if len(use) > 2 else None,
                   "signs": f"{int((np.sign(m) == np.sign(p)).sum())}/{len(use)}",
                   "slope_measured_per_predicted": float((m @ p) / (p @ p)) if (p @ p) > 0 else None}}
    pairs = []
    by = {r["bump"]: r for r in rows}
    for pr in J.get("pairs", []):
        if pr["plus"] in by and pr["minus"] in by:
            pp = (by[pr["plus"]]["predicted_mN"] - by[pr["minus"]]["predicted_mN"]) / 2
            pairs.append({"site": pr["site"], "amp_mm": pr["amp_mm"], "half_diff_measured_mN": pr["half_diff_measured_mN"],
                          "half_diff_stderr_mN": pr["half_diff_stderr_mN"], "half_diff_predicted_mN": pp,
                          "sigma_off": abs(pp - pr["half_diff_measured_mN"]) / max(pr["half_diff_stderr_mN"], 1e-9)})
    out["pairs"] = pairs
    out["passed_part3_marks"] = bool(out["map"]["pearson_r"] is not None and out["map"]["pearson_r"] >= 0.9
                                     and (np.sign(m) == np.sign(p)).mean() >= 0.8)
    out["pairs_within_2sigma"] = f"{sum(q['sigma_off'] <= 2 for q in pairs)}/{len(pairs)}"
    (R / f"{a.tag}_judge.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("D_half_N_dafoam", "primal_mismatch_pct", "map", "pairs_within_2sigma",
                                          "passed_part3_marks")}, indent=1))
    for q in pairs:
        print(f"pair {q['site']:>16} ±{q['amp_mm']}: measured {q['half_diff_measured_mN']:+.2f} ± {q['half_diff_stderr_mN']:.2f}"
              f"  DAFoam {q['half_diff_predicted_mN']:+.2f}")
    for r in rows:
        print(f"{r['bump']:>16}: measured {r['measured_mN']:+.2f}  DAFoam {r['predicted_mN']:+.2f}")


if __name__ == "__main__":
    main()
