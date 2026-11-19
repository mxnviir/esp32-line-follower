"""Early look: every method's best design from the first (low-cargo) runs, as designed (not milled)."""
import json, numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
import region as RG, render as R
HERE = Path(__file__).resolve().parent
OLD = HERE / "results/old_cargo_low"
car = RG.Car()
xs, ys, zs, _b, wheels = RG.load_1mm()
NAMES = {"random": "Random", "cma": "CMA-ES", "bo": "Bayesian opt.", "sail": "SAIL", "spsa": "Level set (SPSA)",
         "neat": "CPPN-NEAT", "topo": "Adjoint topology opt."}
refs = json.loads((OLD / "refs.json").read_text()) if (OLD / "refs.json").exists() else {}
items = [("Original (trial car)", np.load(HERE / "results/ref_original.npy"), 390.0, None),
         ("Cargo only (reference)", np.load(HERE / "results/ref_lean.npy"), 376.6, None)]
for p in sorted((OLD / "runs").glob("*_best.npy")):
    tag = p.stem.replace("_best", ""); m, s = tag.rsplit("_s", 1)
    L = [json.loads(l) for l in open(OLD / "runs" / f"{tag}.jsonl") if l.strip()]
    b = min(L, key=lambda r: r["T"])
    items.append((f"{NAMES[m]} (seed {s})", np.load(p), b["D"] * 1e3, b))
n = len(items)
fig = plt.figure(figsize=(15, 3.1 * n / 2 + 1))
for k, (title, half, D, b) in enumerate(items):
    full = car.full(half)
    o = (car.xs[0] - 1.5, -car.ys[-1] - 1.5, car.zs[0] - 1.5)
    for v, (el, az) in enumerate([(28, 52), (90, -90)]):
        ax = fig.add_subplot((n + 1) // 2, 4, 2 * k + v + 1, projection="3d")
        R.surf(ax, full, o, 3.0, "#5d6f86", smooth=1.0)
        pod = car.full(half & car.region)
        R.surf(ax, pod, o, 3.0, "#d9452b", alpha=0.55, smooth=1.0)
        R.surf(ax, wheels, (xs[0] - .5, ys[0] - .5, zs[0] - .5), 1.0, "#d8c8a0", smooth=0)
        R.setup(ax, el, az)
        if v == 0:
            extra = "" if b is None else f" | T {b['T']:.4f} s | foam {b['foam_g']:.1f} g, lead {b['ballast_g']:.1f} g"
            ax.set_title(f"{title}: drag {D:.1f} mN{extra}", fontsize=8, loc="left")
fig.suptitle("Best design per run, first runs (cargo low, NOT milled). Red = what's in the sidepod region. Drag scaled so the original = 390 mN", fontsize=10)
fig.subplots_adjust(left=0, right=1, bottom=0, top=0.95, wspace=0, hspace=0.12)
fig.savefig(HERE / "results/early_designs.png", dpi=95)
