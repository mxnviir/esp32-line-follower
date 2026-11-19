"""Campaign report: per-run table, convergence, renders of the best cars (the STEP exactly outside
the region, the milled design inside), and the best cars' STL folders copied for CAD/CNC."""
import json, shutil
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _body(c, cid):
    p = c.root / "cars" / cid / "body.npy"
    return np.unpackbits(np.load(p))[: c.car.body0.size].reshape(c.car.body0.shape).astype(bool)


def report(c, n_best=6):
    out = c.root / "report"; out.mkdir(exist_ok=True)
    ds = c.designs()
    ok = [d for d in ds if d.get("T") is not None]
    T0 = next((d["T"] for d in ok if d.get("method") == "reference"), None)
    lines = ["| stage | run | cars timed | illegal | best race time (s) | best D20 (mN) |", "|---|---|---|---|---|---|"]
    runs = {}
    for d in ds:
        if d.get("run"):
            runs.setdefault(d["run"], []).append(d)
    for run, rows in sorted(runs.items()):
        t = [r for r in rows if r.get("T") is not None]
        b = min(t, key=lambda r: r["T"]) if t else None
        lines.append(f"| {run.split(':')[0]} | {run} | {len(t)} | {sum(not r.get('legal', True) for r in rows)} | "
                     f"{b['T']:.4f} | {b['D20_N']*1e3:.1f} |" if b else f"| {run.split(':')[0]} | {run} | 0 | | | |")
    (out / "runs.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    # convergence
    fig, ax = plt.subplots(figsize=(9, 5))
    for k, (run, rows) in enumerate(sorted(runs.items())):
        t = [r["T"] for r in rows if r.get("T") is not None]
        if t:
            ax.plot(np.minimum.accumulate(t), label=run, lw=1.4)
    ax.set_xlabel("cars timed"); ax.set_ylabel("best race time so far (s)"); ax.legend(fontsize=6); fig.tight_layout()
    fig.savefig(out / "convergence.png", dpi=120); plt.close(fig)
    # best cars (highest fidelity stage that has results, then by T)
    best, seen = [], set()
    for d in sorted(ok, key=lambda d: d["T"]):
        src = d.get("parent") or d["id"]
        if src not in seen:
            seen.add(src); best.append(d)
        if len(best) == n_best:
            break
    sys_path = c.root.parents[0]
    from render import surf, setup
    car = c.car
    o = (car.xs[0] - car.h / 2, car.ys[0] - car.h / 2, car.zs[0] - car.h / 2)
    fig = plt.figure(figsize=(15, 3.2 * len(best)))
    for k, d in enumerate(best):
        src = d.get("parent") or d["id"]
        B = _body(c, src)
        for v, (el, az) in enumerate([(28, 52), (90, -90), (0, -90)]):
            ax = fig.add_subplot(len(best), 3, 3 * k + v + 1, projection="3d")
            surf(ax, car.keep, o, car.h, "#5d6f86", smooth=0.5)
            surf(ax, B & car.region, o, car.h, "#d9452b", smooth=0.6)
            surf(ax, car.wheels, o, car.h, "#d8c8a0", smooth=0)
            setup(ax, el, az)
            if v == 0:
                ax.set_title(f"{d['id']} ({d.get('stage')}, {d.get('method')}): T {d['T']:.4f} s, D20 {d['D20_N']*1e3:.1f} mN, "
                             f"foam {d['mass']['foam_g']:.1f} g, lead {d['mass']['lead_g']:.1f} g", fontsize=8, loc="left")
        dst = out / "best" / f"{k+1}_{src}"
        if not dst.exists():
            shutil.copytree(c.root / "cars" / src, dst)
    fig.subplots_adjust(left=0, right=1, bottom=0, top=0.97, wspace=0, hspace=0.1)
    fig.savefig(out / "best.png", dpi=95); plt.close(fig)
    (out / "summary.json").write_text(json.dumps({"best": best, "gates": c.state.get("gates"), "stopped": c.state.get("stopped")},
                                                 indent=1, default=float))
