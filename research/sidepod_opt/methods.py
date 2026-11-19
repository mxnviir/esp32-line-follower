"""Search methods as batch ask/tell, so any evaluator (local, Actions matrix, SimScale) can run
them in parallel and a campaign can stop and resume.

    m = make(name, rep, start, rng, **opts)
    xs = m.ask(n)                 -> list of parameter vectors (np.ndarray)
    m.tell(xs, values, info)      values: race time (s) or None for an illegal design (no CFD)

Multi-fidelity (BO, SAIL): m.add_prior(xs, values, fidelity) feeds cheaper results (OpenFOAM medium under fine)
into the surrogate as a second fidelity (GP on [x, s], s = 0 cheap, 1 target): an auto-regressive
co-kriging stand-in that learns how the cheap ranking maps onto the expensive one.
"""
from __future__ import annotations

import numpy as np


class Method:
    def __init__(self, rep, start, rng, **o):
        self.rep, self.rng, self.o = rep, rng, o
        self.x0 = rep.x0(start)
        self.X, self.Y = [], []                 # target-fidelity observations
        self.prior = []                         # (x, y, s)

    def best(self):
        if not self.Y:
            return None, np.inf
        i = int(np.argmin(self.Y)); return self.X[i], self.Y[i]

    def add_prior(self, xs, ys, s=0.0):
        self.prior += [(np.asarray(x), y, s) for x, y in zip(xs, ys) if y is not None]

    def tell(self, xs, ys, info=None):
        for x, y in zip(xs, ys):
            if y is not None:
                self.X.append(np.asarray(x)); self.Y.append(float(y))


class CMA(Method):
    def __init__(self, rep, start, rng, **o):
        super().__init__(rep, start, rng, **o)
        import cma
        self.es = cma.CMAEvolutionStrategy(self.x0, o.get("sigma", 1.0),
                                           {"seed": int(rng.integers(1, 1 << 30)), "verbose": -9,
                                            "popsize": o.get("popsize", 12)})
        self._asked = []

    def ask(self, n):
        xs = self.es.ask(n)
        self._asked += xs
        return xs

    def tell(self, xs, ys, info=None):
        super().tell(xs, ys)
        worst = max([y for y in ys if y is not None], default=1.0)
        self._buf = getattr(self, "_buf", []) + [(x, (y if y is not None else worst + 0.05)) for x, y in zip(xs, ys)]
        while len(self._buf) >= self.es.popsize:
            chunk, self._buf = self._buf[: self.es.popsize], self._buf[self.es.popsize:]
            self.es.tell([c[0] for c in chunk], [c[1] for c in chunk])


def _gp_fit(X, y):
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
    d = X.shape[1]
    k = ConstantKernel(1.0) * Matern(length_scale=np.full(d, 2.0), length_scale_bounds=(0.05, 100), nu=2.5) \
        + WhiteKernel(1e-3, (1e-6, 1e-1))
    mu, sd = y.mean(), y.std() + 1e-12
    gp = GaussianProcessRegressor(k, n_restarts_optimizer=2, normalize_y=False).fit(X, (y - mu) / sd)
    def predict(Z):
        m, s = gp.predict(Z, return_std=True)
        return m * sd + mu, s * sd
    return predict


class _Surrogate(Method):
    """GP over x (+ a fidelity column when there is prior data)."""

    def _data(self):
        X = [np.r_[x, 1.0] for x in self.X] + [np.r_[x, s] for x, _y, s in self.prior]
        Y = list(self.Y) + [y for _x, y, _s in self.prior]
        return np.array(X), np.array(Y)

    def _model(self):
        X, Y = self._data()
        if len(Y) < 3:
            return None
        return _gp_fit(X, Y)

    def _target(self, Z):
        return np.c_[Z, np.ones(len(Z))]


class TuRBO(_Surrogate):
    """GP + expected improvement inside a trust region around the best target-fidelity point."""

    def __init__(self, rep, start, rng, **o):
        super().__init__(rep, start, rng, **o)
        self.L, self.succ, self.fail = o.get("L0", 1.0), 0, 0
        self.n_init = o.get("n_init", 10)

    def ask(self, n):
        d = self.x0.size
        if len(self.Y) + len(self.prior) < self.n_init:
            return [self.x0 + self.rng.uniform(-1.5, 1.5, d) for _ in range(n)]
        f = self._model()
        c = self.best()[0] if self.Y else min(self.prior, key=lambda p: p[1])[0]
        cand = c + self.rng.uniform(-self.L, self.L, (4000, d))
        from scipy.stats import norm
        m, s = f(self._target(cand))
        best = min(self.Y) if self.Y else min(p[1] for p in self.prior)
        z = (best - m) / (s + 1e-12)
        ei = (best - m) * norm.cdf(z) + s * norm.pdf(z)
        idx = np.argsort(-ei)[: n]
        return [cand[i] for i in idx]

    def tell(self, xs, ys, info=None):
        before = min(self.Y) if self.Y else np.inf
        super().tell(xs, ys)
        after = min(self.Y) if self.Y else np.inf
        if after < before - 1e-5:
            self.succ, self.fail = self.succ + 1, 0
        else:
            self.succ, self.fail = 0, self.fail + 1
        if self.succ >= 3:
            self.L, self.succ = min(2 * self.L, 4.0), 0
        if self.fail >= max(4, len(xs)):
            self.L, self.fail = self.L / 2, 0
        if self.L < 0.05:
            self.L = 1.0


class SAIL(_Surrogate):
    """MAP-Elites on the GP's optimistic estimate; descriptors from the built body (foam mass,
    pod height). Returns the archive's most promising, mutually different designs."""

    def __init__(self, rep, start, rng, descriptor=None, bins=(8, 6), **o):
        super().__init__(rep, start, rng, **o)
        self.descriptor, self.bins = descriptor, bins
        self.n_init = o.get("n_init", 10)
        self.D = {}

    def ask(self, n):
        d = self.x0.size
        if len(self.Y) + len(self.prior) < self.n_init:
            return [self.x0 + self.rng.uniform(-1.5, 1.5, d) for _ in range(n)]
        f = self._model()
        pts = [x for x in self.X] + [p[0] for p in self.prior]
        desc = [self.descriptor(x) for x in pts]
        D = np.array([q for q in desc if q is not None])
        lo, hi = D.min(0), D.max(0)
        span = (hi - lo) + 1e-9
        lo, hi = lo - 0.2 * span, hi + 0.2 * span
        arch = {}

        def offer(x):
            q = self.descriptor(x)
            if q is None:
                return
            m, s = f(self._target(np.asarray(x)[None]))
            acq = -m[0] + self.o.get("kappa", 1.0) * s[0]
            cell = tuple(np.clip(((np.asarray(q) - lo) / (hi - lo) * self.bins).astype(int), 0, np.array(self.bins) - 1))
            if cell not in arch or acq > arch[cell][0]:
                arch[cell] = (acq, np.asarray(x))
        for x in pts:
            offer(x)
        for _ in range(self.o.get("illum_steps", 400)):
            keys = list(arch)
            p = arch[keys[self.rng.integers(len(keys))]][1]
            offer(p + self.rng.normal(0, self.o.get("mut", 0.4), d))
        return [a[1] for a in sorted(arch.values(), key=lambda a: -a[0])[:n]]


class SPSA(Method):
    """Gradient by simultaneous perturbation: 2 runs per step whatever the dimension."""

    def __init__(self, rep, start, rng, **o):
        super().__init__(rep, start, rng, **o)
        self.x = self.x0.copy(); self.k = 0; self.pending = None

    def ask(self, n):
        out = []
        for _ in range(max(1, n // 2)):
            self.k += 1
            delta = self.rng.choice([-1.0, 1.0], self.x.size)
            if hasattr(self.rep, "cshape"):                     # level set: smooth sign patterns
                from scipy import ndimage
                delta = np.sign(ndimage.gaussian_filter(self.rng.normal(0, 1, self.rep.cshape), 2.0)).ravel()
            ck = self.o.get("c", 1.0) * (self.o.get("c_mm", 1.0) if hasattr(self.rep, "cshape") else 1.0) / self.k ** 0.101
            self.pending = (delta, ck)
            out += [self.x + ck * delta, self.x - ck * delta]
        return out

    def tell(self, xs, ys, info=None):
        super().tell(xs, ys)
        for i in range(0, len(xs) - 1, 2):
            yp, ym = ys[i], ys[i + 1]
            if yp is None or ym is None:
                continue
            delta, ck = self.pending
            g = (yp - ym) / (2 * ck) * delta
            a = self.o.get("a", 1.5) / (self.k + 2) ** 0.602
            self.x = self.x - a * g / (np.abs(g).max() + 1e-12)


class GradientDescent(Method):
    """For an evaluator that returns a race-time gradient on the design field (adjoint): the
    representation chains it to x; normalised steps with a shrinking trust size."""

    def __init__(self, rep, start, rng, **o):
        super().__init__(rep, start, rng, **o)
        self.x = self.x0.copy(); self.step = o.get("step", 2.0); self.last = None

    def ask(self, n):
        return [self.x.copy()]

    def tell(self, xs, ys, info=None):
        super().tell(xs, ys)
        g_field = (info or [{}])[0].get("grad_field")
        y = ys[0]
        if y is None or g_field is None:
            self.step /= 2; return
        if self.last is not None and y > self.last[1]:
            self.x, self.step = self.last[0], self.step / 2     # overshoot: go back, smaller step
            return
        g = self.rep.field_grad_to_x(g_field)
        self.last = (self.x.copy(), y)
        self.x = self.x - self.step * g / (np.abs(g).max() + 1e-12)


class NEAT(Method):
    """CPPN-NEAT over generations; x is the genome object (not a vector)."""

    def __init__(self, rep, start, rng, cfg_path=None, seeds=None, **o):
        import random
        import neat
        random.seed(int(rng.integers(1 << 30)))
        self.rep, self.rng, self.o = rep, rng, o
        self.cfg = neat.Config(neat.DefaultGenome, neat.DefaultReproduction, neat.DefaultSpeciesSet,
                               neat.DefaultStagnation, str(cfg_path))
        self.pop = neat.Population(self.cfg)
        for g, s in zip(self.pop.population.values(), seeds or []):
            s(g, self.cfg)
        self.queue = list(self.pop.population.items())
        self.scored = {}
        self.X, self.Y, self.prior = [], [], []

    def ask(self, n):
        out = []
        while self.queue and len(out) < n:
            out.append(self.queue.pop(0))
        return out

    def tell(self, xs, ys, info=None):
        for (gid, g), y in zip(xs, ys):
            g.fitness = -10.0 if y is None else -float(y)
            self.scored[gid] = g
            if y is not None:
                self.X.append((gid, g)); self.Y.append(float(y))
        if not self.queue and len(self.scored) >= len(self.pop.population):
            p = self.pop
            p.reporters.start_generation(p.generation)
            p.population = p.reproduction.reproduce(p.config, p.species, p.config.pop_size, p.generation)
            p.species.speciate(p.config, p.population, p.generation)
            p.generation += 1
            self.queue = list(p.population.items()); self.scored = {}


MAKERS = {"cma": CMA, "bo": TuRBO, "sail": SAIL, "spsa": SPSA, "adjoint": GradientDescent, "neat": NEAT}


def make(name, rep, start, rng, **o):
    return MAKERS[name](rep, start, rng, **o)
