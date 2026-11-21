"""DAFoam gradient vs measured +/- bump pairs: half-differences only (no zero run needed).

    python dafoam/pair_judge.py <dafoam_sens.npz> <results_dir> [--sites pod_rear pod_front_low ...]
Measured half-diff = (D(+1 mm) - D(-1 mm)) / 2 from bump_<site>.json / bump_<site>_m.json.
Predicted half-diff = (sum dD/dXs . dX+  -  sum dD/dXs . dX-) / 2, the displacements interpolated from
the bump STLs onto DAFoam's surface points (judge.displacement_at). Pass marks (ROUTES.md, fixed
before the result): Pearson r >= 0.9 and signs >= 80 % over pairs whose measured half-diff is >= 3 sigma
(sigma from the runs' own force standard errors; for the cut-down check, every sign must agree).
"""
import argparse, json, sys
from pathlib import Path
import numpy as np
import trimesh
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from judge import displacement_at, G   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sens"); ap.add_argument("results")
    ap.add_argument("--sites", nargs="*", default=None)
    ap.add_argument("--out", default=None, help="verdict file (default <results>/pair_judge.json)")
    a = ap.parse_args()
    S = np.load(a.sens); X, Gd = S["Xs"], S["dD_dXs"]
    R = Path(a.results)
    base = trimesh.load(G / "original_rm" / "car_half.stl", process=False)
    sites = a.sites or sorted({p.stem[5:] for p in R.glob("bump_*.json") if not p.stem.endswith("_m")})
    rows = []
    for s in sites:
        fp, fm = R / f"bump_{s}.json", R / f"bump_{s}_m.json"
        if not (fp.exists() and fm.exists()):
            continue
        bp, bm = json.loads(fp.read_text()), json.loads(fm.read_text())
        pred = []
        for k in (s, f"{s}_m"):
            mk = trimesh.load(G / f"bump_{k}" / "car_half.stl", process=False)
            pred.append(float((Gd * displacement_at(X, base.vertices, mk.vertices - base.vertices)).sum()) * 1e3)
        se = 0.5 * np.hypot(bp.get("force_mean_stderr") or 2e-4, bm.get("force_mean_stderr") or 2e-4) * 1e3
        rows.append({"site": s, "measured_half_mN": (bp["D20_half_N"] - bm["D20_half_N"]) * 1e3 / 2,
                     "predicted_half_mN": (pred[0] - pred[1]) / 2, "stderr_mN": se,
                     "usable": not (bp.get("morph_fallback") or bm.get("morph_fallback"))})
    use = [r for r in rows if r["usable"] and abs(r["measured_half_mN"]) >= 3 * r["stderr_mN"]]
    out = {"pairs": rows, "n_pairs": len(rows), "n_clear": len(use)}
    if use:
        m = np.array([r["measured_half_mN"] for r in use]); p = np.array([r["predicted_half_mN"] for r in use])
        sg = np.sign(m) == np.sign(p)
        out.update(signs=f"{int(sg.sum())}/{len(use)}", ratio_pred_over_meas=(p / m).tolist(),
                   pearson_r=float(np.corrcoef(m, p)[0, 1]) if len(use) >= 3 else None)
    print(json.dumps(out, indent=1))
    out["sens_file"] = str(a.sens)
    Path(a.out or R / "pair_judge.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
