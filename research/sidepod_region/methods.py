"""Organic sidepod search methods, all on one footing.

Every method proposes a design FIELD over the 3 mm half grid (positive = solid). The same
`finish` turns it into a legal, millable, one-piece body (rule zones, cargo, joins). Illegal
designs cost no tunnel run (like the real referee) but are capped. Each method gets the same
number of tunnel runs; its score is the race time of the best design it found.

Shapes are always organic: no method has hand-chosen variables.
  random     random smooth fields around the original (the bar to beat)
  cma        CMA-ES on a 8 x 3 x 4 control lattice added to the original's signed distance
  neat       CPPN-NEAT (network grows), seeded with hand networks: original, lean, pods
  bo         Bayesian optimisation (GP + expected improvement) in a trust region (TuRBO-style)
             on the same lattice
  sail       surrogate-assisted illumination: MAP-Elites on the GP (descriptors: foam volume
             and pod height); the tunnel only checks the archive's most promising cells
  spsa       level-set descent on EVERY cell of the region, gradient by simultaneous
             perturbation (2 runs per step, any number of cells): the no-adjoint gradient
"""
from __future__ import annotations
import json, time
import numpy as np
from scipy import ndimage

LAT = (8, 3, 4)


class Problem:
    """Wraps finish -> mass -> tunnel -> race time, with the run budget and a log."""

    def __init__(self, car, tunnel, scorer, warm, steps, avg_from, budget, log_path):
        self.car, self.tunnel, self.scorer = car, tunnel, scorer
        self.warm, self.steps, self.avg_from = warm, steps, avg_from
        self.budget, self.used, self.illegal = budget, 0, 0
        self.log, self.log_path = [], log_path
        self.best = (np.inf, None, None)
        self.t0 = time.time()
        sd_in = ndimage.distance_transform_edt(car.original)
        sd_out = ndimage.distance_transform_edt(~car.original)
        self.base_field = np.where(car.original, sd_in - 0.5, -(sd_out - 0.5))      # cells
        # region bounding box (for lattices)
        w = np.argwhere(car.region)
        self.lo, self.hi = w.min(0), w.max(0) + 1
        self.cache = {}

    def done(self):
        return self.used >= self.budget or self.illegal > 30 * self.budget

    def lattice_field(self, z, amp=3.0):
        g = np.asarray(z, float).reshape(LAT)
        n = self.hi - self.lo
        up = ndimage.zoom(g, n / np.array(LAT), order=3, mode="nearest")[: n[0], : n[1], : n[2]]
        f = self.base_field.copy()
        f[self.lo[0]:self.hi[0], self.lo[1]:self.hi[1], self.lo[2]:self.hi[2]] += amp * up
        return f

    def evaluate(self, field, tag=""):
        """Race time (s) of the design AS MILLED, or None if illegal (no tunnel run)."""
        import milling as ML
        body = self.car.finish(field)
        if body is None:
            self.illegal += 1
            return None, None
        B1, _rep = ML.mill(self.car, body)                     # what the CNC leaves
        m = ML.mass_1mm(B1, self.scorer)
        body = ML.to_half3(self.car, B1)
        if not m["mass_legal"]:
            self.illegal += 1
            return None, body
        key = np.packbits(body).tobytes()
        if key in self.cache:                      # same body as before: no new run
            return self.cache[key], body
        if self.used >= self.budget:
            return None, body
        r = self.tunnel.measure(body, self.steps, self.avg_from, warm=self.warm)
        self.used += 1
        T, D, Lf, _ = self.scorer.race(r["drag"], r["lift"], m)
        self.cache[key] = T
        if T < self.best[0]:
            self.best = (T, body, field)
        self.log.append(dict(i=self.used, T=T, D=D, L=Lf, drag_lbm=float(r["drag"]), lift_lbm=float(r["lift"]),
                             foam_g=m["foam_g"], ballast_g=m["ballast_g"], com_x=m["com_x"], com_z=m["com_z"],
                             best=self.best[0], illegal=self.illegal, t=round(time.time() - self.t0, 1), tag=tag))
        if self.log_path:
            with open(self.log_path, "a") as fh:
                fh.write(json.dumps(self.log[-1]) + "\n")
        return T, body

    def descriptors(self, body):
        m = self.scorer.mass(body)
        pod = body & self.car.region
        z = self.car.Z[pod].mean() if pod.any() else 0.0
        return m["foam_g"], z


# ------------------------------------------------------------------ random
def run_random(P, rng):
    while not P.done():
        P.evaluate(P.lattice_field(rng.normal(0, 1.0, int(np.prod(LAT)))), "random")


# ------------------------------------------------------------------ CMA-ES
def run_cma(P, rng):
    import cma
    es = cma.CMAEvolutionStrategy(np.zeros(int(np.prod(LAT))), 0.7,
                                  {"seed": int(rng.integers(1, 1 << 30)), "verbose": -9, "popsize": 10})
    while not P.done():
        sols, fits = [], []
        while len(sols) < es.popsize and not P.done():
            s = es.ask(1)[0]
            T, _ = P.evaluate(P.lattice_field(s), "cma")
            sols.append(s)
            fits.append(T if T is not None else 2.0 + 0.01 * np.abs(s).sum())   # illegal: worse than any car
        if len(sols) == es.popsize:
            es.tell(sols, fits)


# ------------------------------------------------------------------ GP helpers
def _gp(X, y):
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import Matern, WhiteKernel, ConstantKernel
    k = ConstantKernel(1.0) * Matern(length_scale=np.full(X.shape[1], 2.0), length_scale_bounds=(0.05, 50), nu=2.5) \
        + WhiteKernel(1e-3, (1e-6, 1e-1))
    mu, sd = y.mean(), y.std() + 1e-9
    gp = GaussianProcessRegressor(k, normalize_y=False, n_restarts_optimizer=2).fit(X, (y - mu) / sd)
    return gp, mu, sd


def _ei(gp, mu, sd, X, best):
    from scipy.stats import norm
    m, s = gp.predict(X, return_std=True)
    m = m * sd + mu; s = s * sd + 1e-12
    z = (best - m) / s
    return (best - m) * norm.cdf(z) + s * norm.pdf(z), m, s


def _legal_points(P, rng, center, radius, n):
    """Sample lattice vectors inside a box around center; keep those that finish legally."""
    out = []
    tries = 0
    while len(out) < n and tries < 40 * n:
        tries += 1
        z = center + rng.uniform(-radius, radius, center.size)
        body = P.car.finish(P.lattice_field(z))
        if body is not None and P.scorer.mass(body)["mass_legal"]:
            out.append(z)
    return np.array(out)


# ------------------------------------------------------------------ BO (trust region)
def run_bo(P, rng, n_init=12):
    d = int(np.prod(LAT))
    X, Y = [], []
    for z in _legal_points(P, rng, np.zeros(d), 1.5, n_init):
        T, _ = P.evaluate(P.lattice_field(z), "bo-init")
        if T is not None:
            X.append(z); Y.append(T)
    L, succ, fail = 1.0, 0, 0
    while not P.done():
        Xa, Ya = np.array(X), np.array(Y)
        gp, mu, sd = _gp(Xa, Ya)
        c = Xa[np.argmin(Ya)]
        cand = c + rng.uniform(-L, L, (3000, d))
        ei, _, _ = _ei(gp, mu, sd, cand, Ya.min())
        for k in np.argsort(-ei)[:40]:
            body = P.car.finish(P.lattice_field(cand[k]))
            if body is not None and P.scorer.mass(body)["mass_legal"]:
                break
        T, _ = P.evaluate(P.lattice_field(cand[k]), "bo")
        if T is None:
            fail += 1
            continue
        improved = T < Ya.min() - 1e-5
        X.append(cand[k]); Y.append(T)
        succ, fail = (succ + 1, 0) if improved else (0, fail + 1)
        if succ >= 3: L, succ = min(2 * L, 3.0), 0
        if fail >= 5: L, fail = L / 2, 0
        if L < 0.1: L = 1.0                                   # restart the region size


# ------------------------------------------------------------------ SAIL
def run_sail(P, rng, n_init=12, bins=(6, 5), batch=3):
    d = int(np.prod(LAT))
    X, Y, Dsc = [], [], []
    for z in _legal_points(P, rng, np.zeros(d), 1.5, n_init):
        T, body = P.evaluate(P.lattice_field(z), "sail-init")
        if T is not None:
            X.append(z); Y.append(T); Dsc.append(P.descriptors(body))
    while not P.done():
        Xa, Ya = np.array(X), np.array(Y)
        gp, mu, sd = _gp(Xa, Ya)
        D = np.array(Dsc)
        lo, hi = D.min(0) - 1e-6, D.max(0) + 1e-6
        lo -= 0.15 * (hi - lo); hi += 0.15 * (hi - lo)

        def cell(dsc):
            t = (np.asarray(dsc) - lo) / (hi - lo)
            return tuple(np.clip((t * bins).astype(int), 0, np.array(bins) - 1))
        archive = {}                                         # cell -> (acq, z)

        def offer(z):
            body = P.car.finish(P.lattice_field(z))
            if body is None or not P.scorer.mass(body)["mass_legal"]:
                return
            m, s = gp.predict(z[None], return_std=True)
            acq = -(m[0] * sd + mu) + 1.0 * s[0] * sd      # optimistic: low time, uncertain = good
            c = cell(P.descriptors(body))
            if c not in archive or acq > archive[c][0]:
                archive[c] = (acq, z)
        for z in Xa:
            offer(z)
        for _ in range(250):                                 # MAP-Elites on the surrogate (free)
            keys = list(archive)
            parent = archive[keys[rng.integers(len(keys))]][1]
            offer(parent + rng.normal(0, 0.4, d))
        picks = sorted(archive.values(), key=lambda a: -a[0])[:batch]
        for acq, z in picks:
            if P.done():
                break
            T, body = P.evaluate(P.lattice_field(z), "sail")
            if T is not None:
                X.append(z); Y.append(T); Dsc.append(P.descriptors(body))


# ------------------------------------------------------------------ SPSA level set
def run_spsa(P, rng, a0=1.2, c0=1.0):
    """Level-set descent on the whole region. Each step: one random smooth +/- perturbation of
    every cell (2 runs) gives a gradient estimate; the field moves against it."""
    f = P.base_field.copy()
    reg = P.car.region
    k = 0
    while not P.done():
        k += 1
        delta = ndimage.gaussian_filter(rng.normal(0, 1, f.shape), 1.5)
        delta = np.sign(delta) * reg                         # Rademacher-like, smooth sign pattern
        ck = c0 / k ** 0.101
        Tp, _ = P.evaluate(f + ck * delta, "spsa+")
        Tm, _ = P.evaluate(f - ck * delta, "spsa-")
        if Tp is None or Tm is None:
            continue
        g = (Tp - Tm) / (2 * ck) * delta                     # s per cell unit
        ak = a0 / (k + 2) ** 0.602
        step = ak * g / (np.abs(g).max() + 1e-12)            # at most ~a0 cells per step
        f = f - step * 1.0
        f = np.where(reg, ndimage.gaussian_filter(f, 0.6), f)


# ------------------------------------------------------------------ CPPN-NEAT (seeded)
NEAT_CFG = """
[NEAT]
fitness_criterion     = max
fitness_threshold     = 1e9
pop_size              = 10
reset_on_extinction   = True
no_fitness_termination = True

[DefaultGenome]
num_inputs            = 6
num_hidden            = 0
num_outputs           = 1
initial_connection    = full_direct
feed_forward          = True
activation_default    = tanh
activation_mutate_rate = 0.15
activation_options    = sigmoid tanh sin gauss abs identity
aggregation_default   = sum
aggregation_mutate_rate = 0.0
aggregation_options   = sum
bias_init_mean        = 0.0
bias_init_stdev       = 0.5
bias_max_value        = 5.0
bias_min_value        = -5.0
bias_mutate_power     = 0.3
bias_mutate_rate      = 0.7
bias_replace_rate     = 0.02
response_init_mean    = 1.0
response_init_stdev   = 0.0
response_max_value    = 5.0
response_min_value    = -5.0
response_mutate_power = 0.0
response_mutate_rate  = 0.0
response_replace_rate = 0.0
weight_init_mean      = 0.0
weight_init_stdev     = 0.5
weight_max_value      = 6
weight_min_value      = -6
weight_mutate_power   = 0.3
weight_mutate_rate    = 0.8
weight_replace_rate   = 0.02
enabled_default       = True
enabled_mutate_rate   = 0.02
node_add_prob         = 0.2
node_delete_prob      = 0.05
conn_add_prob         = 0.3
conn_delete_prob      = 0.1
compatibility_disjoint_coefficient = 1.0
compatibility_weight_coefficient   = 0.5
single_structural_mutation = False
structural_mutation_surer  = default

[DefaultSpeciesSet]
compatibility_threshold = 2.0

[DefaultStagnation]
species_fitness_func = max
max_stagnation       = 8
species_elitism      = 2

[DefaultReproduction]
elitism            = 2
survival_threshold = 0.3
min_species_size   = 2
"""

ACT = {"sigmoid": lambda z: 1 / (1 + np.exp(-np.clip(5 * z, -60, 60))), "tanh": lambda z: np.tanh(np.clip(2.5 * z, -60, 60)),
       "sin": lambda z: np.sin(np.clip(5 * z, -60, 60)), "gauss": lambda z: np.exp(-5 * np.clip(z, -3.4, 3.4) ** 2),
       "abs": np.abs, "identity": lambda z: z}


def cppn_inputs(P):
    c = P.car
    d_must = ndimage.distance_transform_edt(~c.must) / 6.0
    d_orig = P.base_field / 6.0                              # + inside the original body
    return np.stack([c.xn, c.yn, c.zn, d_must, d_orig, np.ones_like(c.xn)], -1)


def cppn_field(genome, cfg, I):
    import neat
    net = neat.nn.FeedForwardNetwork.create(genome, cfg)
    vals = {k: I[..., i] for i, k in enumerate(cfg.genome_config.input_keys)}
    for node, _a, _g, bias, resp, links in net.node_evals:
        s = np.full(I.shape[:-1], bias)
        for i, w in links:
            s = s + w * vals[i]
        vals[node] = ACT[genome.nodes[node].activation](resp * s)
    return vals[cfg.genome_config.output_keys[0]] * 4.0      # +-4 cells


def _seed(genome, cfg, out_bias, weights):
    """Rewire a fresh genome: output = tanh(bias + sum w_k * input_k)."""
    gc = cfg.genome_config
    out = gc.output_keys[0]
    for k in list(genome.connections):
        del genome.connections[k]
    genome.nodes[out].bias, genome.nodes[out].activation, genome.nodes[out].response = out_bias, "tanh", 1.0
    for i, w in weights.items():
        key = (gc.input_keys[i], out)
        cg = genome.create_connection(gc, *key, gc.innovation_tracker.get_innovation_number(*key, "add_connection")) \
            if hasattr(gc, "innovation_tracker") else genome.create_connection(gc, *key)
        cg.weight, cg.enabled = w, True
        genome.connections[key] = cg


def run_neat(P, rng, tmpdir):
    import random, neat
    from pathlib import Path
    random.seed(int(rng.integers(1 << 30)))
    p = Path(tmpdir) / "neat.cfg"; p.write_text(NEAT_CFG)
    cfg = neat.Config(neat.DefaultGenome, neat.DefaultReproduction, neat.DefaultSpeciesSet, neat.DefaultStagnation, str(p))
    I = cppn_inputs(P)
    pop = neat.Population(cfg)
    gs = list(pop.population.values())
    # inputs: 0 x, 1 y, 2 z, 3 dist to cargo, 4 inside-original distance, 5 one
    seeds = [(0.0, {4: 1.5}),                 # the original sidepod
             (-0.3, {3: -1.5}),               # lean: a skin round the cargo
             (-0.2, {3: -1.0, 2: -0.8, 1: 0.4}),   # low, wide pods
             (0.0, {4: 1.0, 0: -0.6}),        # original, tapering towards the tail
             (0.0, {4: 1.0, 2: -0.8})]        # original, lowered
    for g, (b, w) in zip(gs, seeds):
        _seed(g, cfg, b, w)

    def fitness(genomes, config):
        for _gid, g in genomes:
            if P.done():
                g.fitness = -10.0
                continue
            T, _ = P.evaluate(cppn_field(g, config, I), "neat")
            g.fitness = -10.0 if T is None else -T
    while not P.done():
        pop.run(fitness, 1)


METHODS = {"random": run_random, "cma": run_cma, "bo": run_bo, "sail": run_sail, "spsa": run_spsa, "neat": run_neat}
