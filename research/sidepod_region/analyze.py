"""Re-score every run's best design honestly, plot convergence, render the winners.

Re-scoring (the 'step-up' check): the design each method handed over is re-run
  A_long : from state A, 3x longer, averaged over the last 2/3
  B      : from frozen state B (the other start state) with the normal length
A method whose best only looked good through the short, single-state measurement drops here.
"""
import json, glob, numpy as np
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from region import Car
from tunnel import CarTunnel
from score import Scorer
import run_one, render

HERE = Path(__file__).resolve().parent
RUNS = HERE / "results/runs"
car = Car(); tun = CarTunnel(car)
base = json.loads((HERE / "results/base.json").read_text())
sc = Scorer(car, base["drag_A"], base["lift_A"])
A, B = np.load(HERE / "results/state_A.npy"), np.load(HERE / "results/state_B.npy")
S, AV = run_one.STEPS, run_one.AVG_FROM
NAMES = {"random": "Random smooth shapes", "cma": "CMA-ES (lattice)", "neat": "CPPN-NEAT (seeded)",
         "bo": "Bayesian opt. (trust region)", "sail": "SAIL (surrogate + MAP-Elites)",
         "spsa": "Level set, SPSA gradient", "topo": "Topology opt., adjoint (JAX)"}


def rescore(body, cache={}):
    key = np.packbits(body).tobytes()
    if key in cache:
        return cache[key]
    m = sc.mass(body)
    out = dict(mass=m)
    for name, warm, st, av in (("A_long", A, 2 * S, S), ("B", B, S, AV)):
        r = tun.measure(body, st, av, warm=warm)
        T, D, Lf, _ = sc.race(r["drag"], r["lift"], m)
        out[name] = dict(T=T, D=D, L=Lf)
    cache[key] = out
    return out


def main():
    refs = {}
    for k in ("original", "lean", "hand", "whole"):
        p = HERE / f"results/ref_{k}.npy"
        if p.exists():
            refs[k] = np.load(p)
    rows, curves = [], {}
    for f in sorted(RUNS.glob("*_s*.jsonl")):
        tag = f.stem; method, seed = tag.rsplit("_s", 1)
        log = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
        if not log:
            continue
        bp = RUNS / f"{tag}_best.npy"
        if not bp.exists():
            continue
        best = np.load(bp, allow_pickle=True)
        if best.dtype == object:
            continue
        rs = rescore(best)
        # charged runs: topo charges 2 per gradient; its log has only scoring runs
        xs = [r["i"] for r in log]
        curves.setdefault(method, []).append((xs, [r["best"] for r in log]))
        rows.append(dict(method=method, seed=int(seed), T_search=min(r["T"] for r in log), runs=len(log),
                         illegal=log[-1]["illegal"], T_A_long=rs["A_long"]["T"], T_B=rs["B"]["T"],
                         D_A_long=rs["A_long"]["D"], foam_g=rs["mass"]["foam_g"], ballast_g=rs["mass"]["ballast_g"],
                         com_z=rs["mass"]["com_z"]))
        print(json.dumps(rows[-1]), flush=True)
    ref_rows = {}
    for k, body in refs.items():
        rs = rescore(body)
        ref_rows[k] = dict(T_A_long=rs["A_long"]["T"], T_B=rs["B"]["T"], D=rs["A_long"]["D"], **{kk: rs["mass"][kk] for kk in ("foam_g", "ballast_g", "com_z", "mass_legal")})
        print(k, json.dumps(ref_rows[k], default=float), flush=True)
    (HERE / "results/summary.json").write_text(json.dumps(dict(rows=rows, refs=ref_rows), indent=1, default=float))

    # convergence plot (best race time found vs tunnel runs)
    fig, ax = plt.subplots(figsize=(9, 5.5))
    t0 = ref_rows.get("original", {}).get("T_A_long")
    for k, (method, cs) in enumerate(sorted(curves.items())):
        for j, (x, y) in enumerate(cs):
            ax.plot(x, (np.array(y) - (t0 or 0)) * 1e3, color=f"C{k}", alpha=0.85, lw=1.6,
                    label=NAMES.get(method, method) if j == 0 else None)
    ax.axhline(0, color="k", lw=0.8, ls=":")
    ax.set_xlabel("tunnel runs used"); ax.set_ylabel("best race time found − original car (ms)")
    ax.set_title("Search progress (each line one seed; lower is faster)")
    ax.legend(fontsize=8); fig.tight_layout(); fig.savefig(HERE / "results/convergence.png", dpi=120); plt.close(fig)

    # winners: best of each method by honest (A_long) time
    best = {}
    for r in rows:
        if r["method"] not in best or r["T_A_long"] < best[r["method"]]["T_A_long"]:
            best[r["method"]] = r
    designs = [("original (trial car)", refs["original"])] if "original" in refs else []
    for m, r in sorted(best.items(), key=lambda kv: kv[1]["T_A_long"]):
        b = np.load(RUNS / f"{m}_s{r['seed']}_best.npy")
        dt = (r["T_A_long"] - t0) * 1e3 if t0 else 0
        designs.append((f"{NAMES.get(m, m)}: {dt:+.2f} ms, foam {r['foam_g']:.1f} g", b))
    render.design_figure(HERE / "results/winners.png", designs, car)


if __name__ == "__main__":
    main()
