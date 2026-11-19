"""Optimiser shoot-out on a stand-in for the car problem. No CFD.

Why a stand-in: one fine CFD run costs ~4.5 h, so comparing seven optimisers on the real car
would cost thousands of CPU-hours. This bench answers the narrower question "how many CFD runs
does each method need, given OUR noise, OUR fidelity link and OUR flow-state jumps?". The
numbers it is tuned to come from the repo's own PROOF.md files:

  noise of one timing          0.3 ms   (part2 PROOF: 0.09-0.36 ms depending on set-up)
  two flow states              1.3 ms   (part2 PROOF: frozen reference states A/B differ 1.3-1.4 ms)
  medium vs fine ranking       Spearman ~0.96 (part2 PROOF: 0.963-0.973)
  cost of fine vs medium       6 : 1    (fine ~4.5 h, medium ~45 min on 2 cores)
  spread start car -> best     ~20-40 ms (typical first steps move 1-3 ms)
  continuous adjoint quality   r ~0.55 against the true gradient (part3 PROOF: r 0.42-0.70)

Two scenarios:
  A  26 part + layout settings (wings, supports, nose, tunnel, W, x_front, d_halo)
  B  120 body-shape modes (the carving/compass problem)

Every method gets the same budget in FINE-RUN EQUIVALENTS (a medium run costs 1/6). It is scored
on the TRUE (noise-free, fine) time of the car it would hand over at the end, not on its luckiest
measurement. Legality is free (geometry checks need no CFD), so illegal cars are never run.

    python bench.py                 # both scenarios, 8 seeds each
    python bench.py A 12            # one scenario, 12 seeds
"""
from __future__ import annotations

import sys
import time
import warnings
from multiprocessing import Pool

import numpy as np
from scipy.stats import norm, spearmanr
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel as C, Matern, WhiteKernel

warnings.filterwarnings("ignore")

SIGMA_FINE = 0.3          # ms
SIGMA_MED = 0.3           # ms
COST_MED = 1 / 6          # of one fine run
STATE_JUMP = 1.3          # ms


# --------------------------------------------------------------------------------------------
# The stand-in problem
# --------------------------------------------------------------------------------------------
class Problem:
    def __init__(self, d: int, seed: int, kind: str):
        r = np.random.default_rng(seed)
        self.d, self.kind = d, kind
        if kind == "A":
            # a few settings matter a lot, most a little (wings and wheel gap vs strip width)
            self.a = r.permutation(np.geomspace(10.0, 0.05, d))
            self.c = r.uniform(-0.15, 1.15, d)                  # some optima sit on a bound (rule-limited)
            pairs = r.choice(d, size=(6, 2), replace=False) if d >= 12 else np.zeros((0, 2), int)
            self.pairs = [(int(i), int(j), r.uniform(-4, 4)) for i, j in pairs]
            self.rip = r.choice(d, 3, replace=False)
            self.rip_ph = r.uniform(0, 2 * np.pi, 3)
            self.rot = None
        else:
            # many shape modes, smooth, correlated through a low-rank block (neighbouring bumps)
            self.a = r.permutation(np.geomspace(3.0, 0.02, d))
            self.c = r.uniform(0.0, 1.0, d)
            k = 20
            Q, _ = np.linalg.qr(r.normal(size=(d, k)))
            self.rot = (Q, r.uniform(1.0, 6.0, k))
            self.pairs, self.rip = [], np.array([], int)
        self.w_state = r.normal(size=d) / np.sqrt(d)
        self.t_state = float(self.w_state @ np.full(d, 0.5)) + 0.05
        self.legal_w = np.zeros(d)
        self.legal_w[r.choice(d, 3, replace=False)] = 1.0
        # medium mesh: same physics, smooth bias of its own
        self.b_dims = r.choice(d, min(8, d), replace=False)
        self.b_amp = r.uniform(0.5, 1.6, len(self.b_dims))
        self.b_f = r.uniform(0.6, 1.4, len(self.b_dims))
        self.b_ph = r.uniform(0, 2 * np.pi, len(self.b_dims))
        self.x0 = np.full(d, 0.5)

    def legal(self, x):
        x = np.atleast_2d(x)
        return (x @ self.legal_w <= 2.2) & np.all((x >= 0) & (x <= 1), axis=1)

    def smooth(self, x):
        x = np.atleast_2d(x)
        u = x - self.c
        f = (self.a * u ** 2 / 0.25).sum(1)
        for i, j, b in self.pairs:
            f += b * u[:, i] * u[:, j]
        for k, i in enumerate(self.rip):
            f += 0.8 * np.sin(6 * np.pi * x[:, i] + self.rip_ph[k])
        if self.rot is not None:
            Q, s = self.rot
            f += ((u @ Q) ** 2 @ s)
        return f

    def true(self, x):
        x = np.atleast_2d(x)
        state = (x @ self.w_state > self.t_state).astype(float)
        return self.smooth(x) + STATE_JUMP * state

    def grad_smooth(self, x, h=1e-5):
        E = np.eye(self.d) * h
        return np.array([(self.smooth(x + e)[0] - self.smooth(x - e)[0]) / (2 * h) for e in E])

    def fine(self, x, rng):
        return self.true(x) + rng.normal(0, SIGMA_FINE, len(np.atleast_2d(x)))

    def medium(self, x, rng):
        x = np.atleast_2d(x)
        bias = (self.b_amp * np.sin(2 * np.pi * self.b_f * x[:, self.b_dims] + self.b_ph)).sum(1)
        return 0.9 * self.true(x) + bias + rng.normal(0, SIGMA_MED, len(x))


class Meter:
    """Counts the budget and remembers every fine result."""

    def __init__(self, p: Problem, budget: float, seed: int):
        self.p, self.budget, self.spent = p, budget, 0.0
        self.rng = np.random.default_rng(seed + 999)

    def left(self):
        return self.budget - self.spent

    def fine(self, X):
        X = np.atleast_2d(X)
        self.spent += len(X)
        return self.p.fine(X, self.rng)

    def medium(self, X):
        X = np.atleast_2d(X)
        self.spent += COST_MED * len(X)
        return self.p.medium(X, self.rng)


def legal_sample(p, n, rng, centre=None, half=None):
    out = []
    while len(out) < n:
        if centre is None:
            X = rng.uniform(0, 1, (4 * n, p.d))
        else:
            X = np.clip(centre + rng.uniform(-1, 1, (4 * n, p.d)) * half, 0, 1)
        out.extend(X[p.legal(X)])
    return np.array(out[:n])


def lhs(p, n, rng):
    X = (rng.permuted(np.tile(np.arange(n), (p.d, 1)), axis=1).T + rng.uniform(size=(n, p.d))) / n
    bad = ~p.legal(X)
    if bad.any():
        X[bad] = legal_sample(p, int(bad.sum()), rng)
    return X


# --------------------------------------------------------------------------------------------
# Gaussian-process helpers
# --------------------------------------------------------------------------------------------
def gp_fit(X, y, noise=SIGMA_FINE ** 2):
    d = X.shape[1]
    k = C(np.var(y) + 1e-6, (1e-3, 1e5)) * Matern(np.full(d, 0.5), (1e-2, 1e2), nu=2.5) \
        + WhiteKernel(noise / max(np.var(y), 1e-9), (1e-6, 1.0))
    g = GaussianProcessRegressor(k, normalize_y=True, n_restarts_optimizer=1, random_state=0)
    g.fit(X, y)
    return g


def ei(mu, sd, best):
    sd = np.maximum(sd, 1e-9)
    z = (best - mu) / sd
    return (best - mu) * norm.cdf(z) + sd * norm.pdf(z)


def propose(p, rng, predict, best, X_known, q, around):
    """q points by EI with a kriging-believer batch; candidates: global + local around the best."""
    picks = []
    Xk = X_known.copy()
    for _ in range(q):
        cand = np.vstack([legal_sample(p, 1500, rng),
                          legal_sample(p, 1500, rng, around, 0.05),
                          legal_sample(p, 500, rng, around, 0.15)])
        mu, sd = predict(cand)
        if picks:   # crude believer: discourage points next to ones already picked
            dmin = np.min(np.linalg.norm(cand[:, None, :] - np.array(picks)[None], axis=2), 1)
            sd = sd * np.minimum(1, dmin / 0.05)
        a = ei(mu, sd, best)
        picks.append(cand[int(np.argmax(a))])
    return np.array(picks)


# --------------------------------------------------------------------------------------------
# The methods. Each returns the car it hands over.
# --------------------------------------------------------------------------------------------
def m_random(p, M, rng):
    X, y = [p.x0], list(M.fine(p.x0))
    while M.left() >= 1:
        x = legal_sample(p, 1, rng)[0]
        X.append(x)
        y.append(M.fine(x)[0])
    return X[int(np.argmin(y))]


def m_measured_map(p, M, rng, h=0.06):
    """The repo's current method: central-difference slopes of every setting (2d runs), then
    one candidate per step size along the slope; keep the best only if it beats the current car."""
    x = p.x0.copy()
    fx = M.fine(x)[0]
    scale = 0.15
    while M.left() >= 2 * p.d + 4:
        g = np.zeros(p.d)
        for i in range(p.d):
            e = np.zeros(p.d)
            e[i] = h
            xp, xm = np.clip(x + e, 0, 1), np.clip(x - e, 0, 1)
            g[i] = (M.fine(xp)[0] - M.fine(xm)[0]) / max(xp[i] - xm[i], 1e-9)
        dvec = -g / (np.linalg.norm(g) + 1e-12)
        cands = [np.clip(x + s * scale * dvec, 0, 1) for s in (0.25, 0.5, 1, 2)]
        cands = [c for c in cands if p.legal(c)[0]] or [x]
        ys = M.fine(np.array(cands))
        j = int(np.argmin(ys))
        if ys[j] < fx - 2 * SIGMA_FINE * np.sqrt(2):
            x, fx = cands[j], ys[j]
            scale *= 2 if j == 3 else 1
        else:
            scale /= 2
    return x


def m_adjoint(p, M, rng, r_corr):
    """Gradient from one primal + one adjoint (2 fine runs) with correlation r_corr to the true
    smooth gradient; then a 3-point line search. The adjoint cannot see the flow-state jump."""
    x = p.x0.copy()
    fx = M.fine(x)[0]
    scale = 0.15
    while M.left() >= 5:
        M.spent += 1                                     # the adjoint solve (primal counted in fx)
        g = p.grad_smooth(x)
        gn = np.linalg.norm(g) + 1e-12
        u = g / gn
        n = rng.normal(size=p.d)
        n -= (n @ u) * u
        n /= np.linalg.norm(n) + 1e-12
        gh = r_corr * u + np.sqrt(max(0, 1 - r_corr ** 2)) * n
        cands = [np.clip(x - s * scale * gh, 0, 1) for s in (0.5, 1, 2)]
        cands = [c for c in cands if p.legal(c)[0]] or [x]
        ys = M.fine(np.array(cands))
        j = int(np.argmin(ys))
        if ys[j] < fx - SIGMA_FINE:
            x, fx = cands[j], M.fine(cands[j])[0]        # fresh primal at the new car (+ re-time)
            scale *= 1.5 if j == len(cands) - 1 else 1
        else:
            scale /= 2
            fx = min(fx, M.fine(x)[0]) if M.left() >= 6 else fx
    return x


def m_cmaes(p, M, rng):
    import cma
    es = cma.CMAEvolutionStrategy(p.x0, 0.2, {"bounds": [0, 1], "seed": int(rng.integers(1e9)),
                                              "verbose": -9})
    while M.left() >= es.popsize:
        sols = []
        while len(sols) < es.popsize:
            s = es.ask(1)[0]
            if p.legal(s)[0]:
                sols.append(s)
        es.tell(sols, list(M.fine(np.array(sols))))
    return np.clip(es.mean, 0, 1) if p.legal(es.mean)[0] else np.clip(es.result.xbest, 0, 1)


def m_ga(p, M, rng, pop=16):
    """Evolution that merges cars by performance: tournament parents, blend crossover, mutation."""
    P = np.vstack([p.x0, legal_sample(p, pop - 1, rng)])
    F = M.fine(P)
    while M.left() >= pop:
        kids = []
        while len(kids) < pop:
            i, j = rng.choice(pop, 2, replace=False), rng.choice(pop, 2, replace=False)
            a = P[i[np.argmin(F[i])]]
            b = P[j[np.argmin(F[j])]]
            w = rng.uniform(-0.25, 1.25, p.d)
            k = np.clip(a + w * (b - a) + rng.normal(0, 0.03, p.d) * (rng.uniform(size=p.d) < 0.2), 0, 1)
            if p.legal(k)[0]:
                kids.append(k)
        K = np.array(kids)
        FK = M.fine(K)
        allX, allF = np.vstack([P, K]), np.r_[F, FK]
        keep = np.argsort(allF)[:pop]
        P, F = allX[keep], allF[keep]
    return P[int(np.argmin(F))]


def m_bo(p, M, rng, q=4, n0=None):
    """Kriging + expected improvement, batches of q (parallel GitHub jobs)."""
    n0 = n0 or min(2 * p.d, int(M.budget // 3))
    X = np.vstack([p.x0, lhs(p, n0 - 1, rng)])
    y = M.fine(X)
    while M.left() >= q:
        g = gp_fit(X, y)
        mu_k = g.predict(X)
        best_i = int(np.argmin(mu_k))
        pred = lambda Z: g.predict(Z, return_std=True)
        Xn = propose(p, rng, pred, mu_k[best_i], X, q, X[best_i])
        X, y = np.vstack([X, Xn]), np.r_[y, M.fine(Xn)]
    g = gp_fit(X, y)
    return X[int(np.argmin(g.predict(X)))]


def m_turbo(p, M, rng, q=4):
    """Trust-region BO (TuRBO-1 style): a local GP box that grows on success, shrinks on failure."""
    n0 = min(2 * p.d, int(M.budget // 3))
    X = np.vstack([p.x0, lhs(p, n0 - 1, rng)])
    y = M.fine(X)
    L, succ, fail = 0.4, 0, 0
    while M.left() >= q:
        g = gp_fit(X, y)
        mu_k = g.predict(X)
        bi = int(np.argmin(mu_k))
        centre = X[bi]
        ls = g.kernel_.k1.k2.length_scale
        half = L * ls / np.exp(np.mean(np.log(ls))) / 2
        cand = legal_sample(p, 3000, rng, centre, half)
        # Thompson sampling on a random subset for the batch
        sub = cand[rng.choice(len(cand), min(800, len(cand)), replace=False)]
        S = g.sample_y(sub, q, random_state=int(rng.integers(1e9)))
        Xn = sub[np.argmin(S, axis=0)]
        yn = M.fine(Xn)
        if yn.min() < mu_k[bi] - 1e-3 * abs(mu_k[bi]) - SIGMA_FINE:
            succ, fail = succ + 1, 0
        else:
            succ, fail = 0, fail + 1
        if succ >= 3:
            L, succ = min(2 * L, 1.6), 0
        if fail >= max(4, p.d // q):
            L, fail = L / 2, 0
        if L < 0.01:
            L = 0.4
        X, y = np.vstack([X, Xn]), np.r_[y, yn]
    g = gp_fit(X, y)
    return X[int(np.argmin(g.predict(X)))]


def m_mf_cokriging(p, M, rng, q_med=6):
    """Co-Kriging (Kennedy-O'Hagan AR1): fine = rho * medium + delta. Many medium runs, few fine.
    Each round: q_med medium runs at the top EI points of the fine-level prediction, then ONE fine
    run at the best of them (by the updated fine prediction)."""
    n_med0 = min(4 * p.d, int(M.budget * 0.35 / COST_MED))
    Xm = np.vstack([p.x0, lhs(p, n_med0 - 1, rng)])
    ym = M.medium(Xm)
    n_f0 = max(6, p.d // 3)
    Xf = Xm[np.r_[0, rng.choice(np.arange(1, len(Xm)), n_f0 - 1, replace=False)]]
    yf = M.fine(Xf)

    def fit():
        gm = gp_fit(Xm, ym, SIGMA_MED ** 2)
        mf = gm.predict(Xf)
        A = np.c_[mf, np.ones_like(mf)]
        rho, c0 = np.linalg.lstsq(A, yf, rcond=None)[0]
        gd = gp_fit(Xf, yf - rho * mf)

        def pred(Z):
            m1, s1 = gm.predict(Z, return_std=True)
            m2, s2 = gd.predict(Z, return_std=True)
            return rho * m1 + m2, np.sqrt((rho * s1) ** 2 + s2 ** 2)
        return pred

    while M.left() >= q_med * COST_MED + 1:
        pred = fit()
        mu_f = pred(Xf)[0]
        bi = int(np.argmin(mu_f))
        Xn = propose(p, rng, pred, mu_f[bi], Xm, q_med, Xf[bi])
        Xm, ym = np.vstack([Xm, Xn]), np.r_[ym, M.medium(Xn)]
        pred = fit()
        mu, sd = pred(Xn)
        xf = Xn[int(np.argmin(mu - 0.5 * sd))]
        Xf, yf = np.vstack([Xf, xf]), np.r_[yf, M.fine(xf)]
    pred = fit()
    return Xf[int(np.argmin(pred(Xf)[0]))]


METHODS = {
    "random search": m_random,
    "measured map (current)": m_measured_map,
    "adjoint r=0.55 (as tested)": lambda p, M, r: m_adjoint(p, M, r, 0.55),
    "adjoint r=0.97 (discrete)": lambda p, M, r: m_adjoint(p, M, r, 0.97),
    "CMA-ES": m_cmaes,
    "GA (merge by performance)": m_ga,
    "Bayesian opt (Kriging+EI)": m_bo,
    "TuRBO (trust-region BO)": m_turbo,
    "multi-fidelity co-Kriging": m_mf_cokriging,
}
SCEN = {"A": dict(d=26, budget=120), "B": dict(d=120, budget=300)}
SKIP = {"B": {"Bayesian opt (Kriging+EI)", "multi-fidelity co-Kriging"}}   # too slow at 120-D here; see README


def true_best(p, rng):
    """Best legal car found by a long local polish from many starts on the TRUE function."""
    from scipy.optimize import minimize
    best = (np.inf, None)
    for x in np.vstack([p.x0, legal_sample(p, 30, rng)]):
        r = minimize(lambda z: p.smooth(z)[0] + 50 * max(0, z @ p.legal_w - 2.2) ** 2, x,
                     method="L-BFGS-B", bounds=[(0, 1)] * p.d)
        z = r.x if p.legal(r.x)[0] else x
        v = p.true(z)[0]
        if v < best[0]:
            best = (v, z)
    return best[0]


def one(args):
    scen, seed, name = args
    cfg = SCEN[scen]
    p = Problem(cfg["d"], seed, scen)
    M = Meter(p, cfg["budget"], seed)
    rng = np.random.default_rng(seed * 7 + list(METHODS).index(name))
    t = time.time()
    x = METHODS[name](p, M, rng)
    return scen, seed, name, float(p.true(x)[0]), float(p.true(p.x0)[0]), M.spent, time.time() - t


def main():
    scens = [sys.argv[1]] if len(sys.argv) > 1 else ["A", "B"]
    seeds = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    for s in scens:
        p = Problem(SCEN[s]["d"], 0, s)
        rr = np.random.default_rng(1)
        Z = legal_sample(p, 200, rr)
        rho = spearmanr(p.true(Z), p.medium(Z, rr) / 0.9)[0]
        print(f"scenario {s}: d={p.d}, budget={SCEN[s]['budget']} fine-run equivalents, "
              f"medium-vs-fine Spearman on random cars {rho:.3f}")
    jobs = [(s, k, n) for s in scens for k in range(seeds) for n in METHODS if n not in SKIP.get(s, ())]
    with Pool(4) as pool:
        res = pool.map(one, jobs, chunksize=1)
    for s in scens:
        opt = {}
        for k in range(seeds):
            p = Problem(SCEN[s]["d"], k, s)
            opt[k] = true_best(p, np.random.default_rng(k))
        print(f"\n=== scenario {s} ===  (ms above the best legal car; start car shown for scale)")
        rows = [r for r in res if r[0] == s]
        start = np.mean([r[4] - opt[r[1]] for r in rows])
        print(f"{'start car':32s} {start:8.2f}")
        table = []
        for n in METHODS:
            g = np.array([r[3] - opt[r[1]] for r in rows if r[2] == n])
            if len(g) == 0:
                continue
            closed = np.array([(r[4] - r[3]) / (r[4] - opt[r[1]]) for r in rows if r[2] == n])
            table.append((np.median(g), n, g, closed,
                          np.mean([r[6] for r in rows if r[2] == n])))
        print(f"{'method':32s} {'median gap':>10s} {'worst':>8s} {'% of gain won':>14s} {'cpu s':>7s}")
        for med, n, g, closed, t in sorted(table):
            print(f"{n:32s} {med:10.2f} {g.max():8.2f} {100 * np.median(closed):13.0f}% {t:7.1f}")


if __name__ == "__main__":
    main()
