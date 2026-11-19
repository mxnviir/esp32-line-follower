"""Old designs with the halo/cockpit zone put back exactly as drawn, re-measured (same tunnel
protocol as the search: state A, 1200 steps, last 700 averaged), and rendered with the STEP's
own 1 mm body everywhere outside the sidepod region."""
import json, numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
import region as RG, render as R, milling as ML
from tunnel import CarTunnel
from score import Scorer
import run_one
HERE = Path(__file__).resolve().parent
OLD = HERE / "results/old_cargo_low"
car = RG.Car(); tun = CarTunnel(car)
A = np.load(HERE / "results/state_A.npy")
NAMES = {"random": "Random", "cma": "CMA-ES", "bo": "Bayesian opt.", "sail": "SAIL", "spsa": "Level set (SPSA)",
         "topo": "Adjoint topology opt."}
items = [("Original (trial car)", car.original.copy())]
items.append(("Cargo only (reference)", np.load(HERE / "results/ref_lean.npy")))
for p in sorted((OLD / "runs").glob("*_best.npy")):
    tag = p.stem.replace("_best", ""); m, s = tag.rsplit("_s", 1)
    items.append((f"{NAMES[m]} (seed {s})", np.load(p)))
rows = []
r0 = None
for title, half in items:
    half = np.where(car.spine_zone, car.original, half)            # put the halo/cockpit zone back
    r = tun.measure(half, run_one.STEPS, run_one.AVG_FROM, warm=A)
    if r0 is None:
        r0 = r; sc = Scorer(car, r0["drag"], r0["lift"])
    m = sc.mass(half)
    T, D, Lf, _ = sc.race(r["drag"], r["lift"], m)
    rows.append(dict(name=title, D_mN=D * 1e3, T=T, foam_g=m["foam_g"], lead_g=m["ballast_g"], total_g=m["total_g"], half=half))
    print(f"{title:28s} drag {D*1e3:6.1f} mN  T {T:.4f} s  foam {m['foam_g']:.1f} g  lead {m['ballast_g']:.1f} g  car {m['total_g']:.1f} g", flush=True)
json.dump([{k: v for k, v in r.items() if k != "half"} for r in rows], open(HERE / "results/old_fixed.json", "w"), indent=1)

# render: STEP body outside the region (1 mm, exact) + the design inside it (smoothed to 1 mm)
xs, ys, zs = ML.xs, ML.ys, ML.zs
o1 = (xs[0] - .5, ys[0] - .5, zs[0] - .5)
n = len(rows)
fig = plt.figure(figsize=(15, 3.1 * ((n + 1) // 2) + 1))
for k, r in enumerate(rows):
    pod = ML.smooth_1mm(car, r["half"]) & ML.REGION | (ML.CARGO & False)
    pod |= ML.BODY1 & ML.REGION & False
    lowcargo = ML.smooth_1mm(car, r["half"] & car.must) & ~ML.SPINE_ZONE
    kept = ML.KEEP
    for v, (el, az) in enumerate([(28, 52), (90, -90)]):
        ax = fig.add_subplot((n + 1) // 2, 4, 2 * k + v + 1, projection="3d")
        R.surf(ax, kept, o1, 1.0, "#5d6f86", smooth=0.5)
        R.surf(ax, pod | lowcargo, o1, 1.0, "#d9452b", smooth=0.7)
        R.surf(ax, ML.WHEELS1, o1, 1.0, "#d8c8a0", smooth=0)
        R.setup(ax, el, az)
        if v == 0:
            ax.set_title(f"{r['name']}: drag {r['D_mN']:.1f} mN | T {r['T']:.4f} s | foam {r['foam_g']:.1f} g, lead {r['lead_g']:.1f} g",
                         fontsize=8, loc="left")
fig.suptitle("Best design per run with the halo/cockpit zone exactly as drawn. Grey = your STEP (unchanged), red = sidepod region as designed (not milled; cargo low as in these runs)", fontsize=10)
fig.subplots_adjust(left=0, right=1, bottom=0, top=0.95, wspace=0, hspace=0.12)
fig.savefig(HERE / "results/early_designs_fixed.png", dpi=95)
