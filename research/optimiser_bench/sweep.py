"""How many CFD runs do the search methods need, and does fresh-mesh noise break them?
No CFD: bench.py's stand-in problem (tuned to Part 2's measured numbers), swept over
  noise sigma   0.3 ms  (OpenFOAM, every car morphed from one frozen reference: Part 2 PROOF)
                8.6 ms  (fresh mesh per car: Part 2 stopwatch NOISE_S; SimScale is always this case)
                30 ms   (the same fresh-mesh noise against a problem 3.5x smaller: sidepod-sized gains)
  variables     3 (layout: halo, rear overhang, wheelbase), 20 (an organic shape in ~20 smooth
                modes), 120 (a fine organic shape)
  budget        50 and 150 runs
Scored on the TRUE value of the car each method hands over (not its luckiest measurement), as
'% of the possible gain won' and 'ms left on the table'.

    python sweep.py [seeds]
"""
import sys, time, json
import numpy as np
from multiprocessing import Pool
import bench as B

NOISES = (0.3, 8.6, 30.0)
DIMS = ((3, "A"), (20, "B"), (120, "B"))
BUDGETS = (50, 150)
METH = ("CMA-ES", "GA (merge by performance)", "Bayesian opt (Kriging+EI)", "TuRBO (trust-region BO)")


def one(a):
    noise, d, kind, budget, seed, name = a
    B.SIGMA_FINE = B.SIGMA_MED = noise
    B.gp_fit.__defaults__ = (noise ** 2,)
    p = B.Problem(d, seed, kind)
    M = B.Meter(p, budget, seed)
    rng = np.random.default_rng(seed * 7 + METH.index(name))
    t = time.time()
    x = B.METHODS[name](p, M, rng)
    return dict(noise=noise, d=d, budget=budget, seed=seed, method=name, got=float(p.true(x)[0]),
                start=float(p.true(p.x0)[0]), secs=time.time() - t)


if __name__ == "__main__":
    seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    jobs = [(n, d, k, b, s, m) for n in NOISES for d, k in DIMS for b in BUDGETS for s in range(seeds) for m in METH
            if not (m == "Bayesian opt (Kriging+EI)" and d > 20)]
    out = []
    with Pool(4) as pool:
        for r in pool.imap_unordered(one, jobs):
            out.append(r)
            if len(out) % 20 == 0:
                print(len(out), "/", len(jobs), flush=True)
    opt = {}
    for d, k in DIMS:
        for s in range(seeds):
            opt[(d, s)] = B.true_best(B.Problem(d, s, k), np.random.default_rng(s))
    for r in out:
        best = opt[(r["d"], r["seed"])]
        r["gap"] = r["got"] - best
        r["won"] = (r["start"] - r["got"]) / (r["start"] - best)
        r["start_gap"] = r["start"] - best
    json.dump(out, open("sweep_results.json", "w"), indent=1)
    print("\nnoise ms | vars | runs | method | ms left (median, worst) | % of gain won (median) | start gap ms")
    for n in NOISES:
        for d, _ in DIMS:
            for b in BUDGETS:
                for m in METH:
                    rr = [r for r in out if r["noise"] == n and r["d"] == d and r["budget"] == b and r["method"] == m]
                    if rr:
                        g = np.array([r["gap"] for r in rr]); w = np.array([r["won"] for r in rr])
                        print(f"{n:5.1f} | {d:4d} | {b:4d} | {m:28s} | {np.median(g):7.1f} {g.max():7.1f} | {100*np.median(w):6.0f}% | {np.mean([r['start_gap'] for r in rr]):.1f}")
