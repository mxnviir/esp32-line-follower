"""Can organic evolution find good shapes in a CFD-sized budget? A 2-D test on real fluid flow.

The scene is a side view of a car-like problem in the lattice-Boltzmann tunnel (lbm2d.py):
two fixed wheels on a rolling road; a body that MUST contain a low "cargo" block between the
wheels and a high "chamber" block at the back above the rear wheel, MUST stay clear of the
wheels and the road, and must be one piece that a 4-cell tool can make (no slivers, no notches).
Everything else is free. Score = drag of everything (body + wheels): lower is better.

Every method gets the same number of CFD runs. Shapes that come out illegal cost nothing (as
the real referee costs no CFD) but are capped so a method can't spin forever.

Methods
  cppn-neat   organic: a CPPN evolved by NEAT (network grows), field = sign of its output
  lattice     free-form: an 18 x 6 grid of field values, smoothed, searched by CMA-ES
  param       designer-style: top and bottom profile curves (12 numbers), CMA-ES
  random      random CPPNs from the same starting distribution as NEAT (no evolution)

    python evolve2d.py run <method> <seed> <budget>
    python evolve2d.py refs
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lbm2d as L  # noqa: E402

OUT = Path(__file__).resolve().parent / "results"
STEPS, AVG_FROM = 9000, 4500
X, Y = np.meshgrid(np.arange(L.NX), np.arange(L.NY), indexing="ij")

WHEELS = [(70, 9, 9), (170, 9, 9)]


def _wheel(cx, cy, r):
    return ((X - cx) ** 2 + (Y - cy) ** 2 <= r * r) | ((np.abs(X - cx) <= 4) & (Y <= 3))


WHEEL_SOLID = _wheel(*WHEELS[0]) | _wheel(*WHEELS[1])
WHEEL_AIR = np.zeros_like(WHEEL_SOLID)
for cx, cy, r in WHEELS:
    WHEEL_AIR |= (X - cx) ** 2 + (Y - cy) ** 2 <= (r + 3) ** 2
CARGO = (X >= 95) & (X <= 140) & (Y >= 8) & (Y <= 15)
CHAMBER = (X >= 168) & (X <= 196) & (Y >= 22) & (Y <= 31)
MUST = CARGO | CHAMBER
DESIGN = (X >= 35) & (X <= 205) & (Y >= 2) & (Y <= 40)       # where the body may be
FORBID = ~DESIGN | WHEEL_AIR
TOOL = 2                                                     # opening/closing radius, cells


def disk(r):
    a = np.arange(-r, r + 1)
    return a[:, None] ** 2 + a[None, :] ** 2 <= r * r


def finish(raw: np.ndarray):
    """Field (positive = solid) -> legal body, or None. Like Part 1: rules forced, made
    machinable, holes filled, one piece holding every required block."""
    s = (raw > 0) & ~FORBID
    s |= MUST
    s = ndimage.binary_closing(s, disk(TOOL))
    s = ndimage.binary_opening(s, disk(TOOL))
    s = ndimage.binary_fill_holes(s)
    s &= ~FORBID
    s |= MUST
    lab, n = ndimage.label(s)
    ids = set(np.unique(lab[MUST])) - {0}
    if len(ids) != 1:
        return None
    return lab == ids.pop()


def score(body):
    return float(L.run((body | WHEEL_SOLID).astype(np.bool_), STEPS, AVG_FROM, L.U0, L.TAU)[0])


# ---------------- representations ----------------
def cppn_inputs():
    xn = (X - 120) / 85.0
    yn = (Y - 20) / 20.0
    dfw = np.sqrt((X - 70) ** 2 + (Y - 9) ** 2) / 50.0
    drw = np.sqrt((X - 170) ** 2 + (Y - 9) ** 2) / 50.0
    dmust = ndimage.distance_transform_edt(~MUST) / 30.0
    return np.stack([xn, yn, dfw, drw, dmust], -1).reshape(-1, 5)


INPUTS = cppn_inputs()


def neat_config(path: Path):
    path.write_text(f"""
[NEAT]
fitness_criterion     = max
fitness_threshold     = 1e9
pop_size              = 20
reset_on_extinction   = True
no_fitness_termination = True

[DefaultGenome]
num_inputs            = 5
num_hidden            = 0
num_outputs           = 1
initial_connection    = full_direct
feed_forward          = True
activation_default    = random
activation_mutate_rate = 0.2
activation_options    = sigmoid tanh sin gauss abs identity
aggregation_default   = sum
aggregation_mutate_rate = 0.0
aggregation_options   = sum
bias_init_mean        = 0.3
bias_init_stdev       = 1.0
bias_max_value        = 5.0
bias_min_value        = -5.0
bias_mutate_power     = 0.4
bias_mutate_rate      = 0.7
bias_replace_rate     = 0.05
response_init_mean    = 1.0
response_init_stdev   = 0.0
response_max_value    = 5.0
response_min_value    = -5.0
response_mutate_power = 0.0
response_mutate_rate  = 0.0
response_replace_rate = 0.0
weight_init_mean      = 0.0
weight_init_stdev     = 1.5
weight_max_value      = 6
weight_min_value      = -6
weight_mutate_power   = 0.4
weight_mutate_rate    = 0.8
weight_replace_rate   = 0.05
enabled_default       = True
enabled_mutate_rate   = 0.02
node_add_prob         = 0.15
node_delete_prob      = 0.05
conn_add_prob         = 0.3
conn_delete_prob      = 0.1
compatibility_disjoint_coefficient = 1.0
compatibility_weight_coefficient   = 0.5
single_structural_mutation = False
structural_mutation_surer  = default

[DefaultSpeciesSet]
compatibility_threshold = 2.5

[DefaultStagnation]
species_fitness_func = max
max_stagnation       = 8
species_elitism      = 2

[DefaultReproduction]
elitism            = 2
survival_threshold = 0.3
min_species_size   = 2
""")


def cppn_field(genome, config):
    import neat
    net = neat.nn.FeedForwardNetwork.create(genome, config)
    out = np.array([net.activate(v)[0] for v in INPUTS[::1]])
    return out.reshape(X.shape)


def lattice_field(z):
    g = np.asarray(z).reshape(18, 6)
    f = ndimage.zoom(g, (L.NX / 18, L.NY / 6), order=3)
    return f[: L.NX, : L.NY]


def param_field(z):
    """Designer body: between a bottom and a top curve over [x0, x1]. z in [-1, 1]^12."""
    z = np.clip(z, -1, 1)
    x0 = 40 + 30 * (z[0] + 1) / 2          # nose 40..70
    x1 = 196 + 9 * (z[1] + 1) / 2          # tail 196..205
    top = 18 + 22 * (np.asarray(z[2:7]) + 1) / 2          # 5 top heights 18..40
    bot = 2 + 12 * (np.asarray(z[7:12]) + 1) / 2          # 5 bottom heights 2..14
    xs = np.linspace(x0, x1, 5)
    t = np.interp(X[:, 0], xs, top)
    b = np.interp(X[:, 0], xs, bot)
    t = ndimage.gaussian_filter1d(t, 6)
    b = ndimage.gaussian_filter1d(b, 6)
    inside_x = (X[:, 0] >= x0) & (X[:, 0] <= x1)
    f = np.minimum(t[:, None] - Y, Y - b[:, None])
    f[~inside_x] = -1
    return f


# ---------------- the methods ----------------
class Budget:
    def __init__(self, n, log):
        self.n, self.used, self.illegal, self.log, self.best = n, 0, 0, log, (np.inf, None)
        self.t0 = time.time()

    def eval(self, field, tag=""):
        body = finish(field)
        if body is None:
            self.illegal += 1
            return None
        if self.used >= self.n:
            return None
        d = score(body)
        self.used += 1
        if d < self.best[0]:
            self.best = (d, body)
        self.log.append({"i": self.used, "d": d, "best": self.best[0], "illegal": self.illegal,
                         "t": round(time.time() - self.t0, 1), "tag": tag})
        return d

    def done(self):
        return self.used >= self.n or self.illegal > 20 * self.n


def run_neat(seed, n, log, random_only=False):
    import random

    import neat
    random.seed(seed)
    np.random.seed(seed)
    cfgp = OUT / f"neat_{seed}.cfg"
    neat_config(cfgp)
    config = neat.Config(neat.DefaultGenome, neat.DefaultReproduction, neat.DefaultSpeciesSet,
                         neat.DefaultStagnation, str(cfgp))
    B = Budget(n, log)
    if random_only:
        while not B.done():
            pop = neat.Population(config)
            for gid, g in pop.population.items():
                if B.done():
                    break
                B.eval(cppn_field(g, config), "random")
        return B
    pop = neat.Population(config)

    def fitness(genomes, config):
        for gid, g in genomes:
            if B.done():
                g.fitness = -1e6
                continue
            d = B.eval(cppn_field(g, config), "neat")
            g.fitness = -1e3 if d is None else -d
    while not B.done():
        pop.run(fitness, 1)
    return B


def run_cma(seed, n, log, kind):
    import cma
    dim = 108 if kind == "lattice" else 12
    fieldf = lattice_field if kind == "lattice" else param_field
    x0 = np.zeros(dim) if kind == "param" else np.full(dim, -0.2)
    es = cma.CMAEvolutionStrategy(x0, 0.5, {"seed": seed + 1, "verbose": -9,
                                            "bounds": [-1, 1] if kind == "param" else [None, None]})
    B = Budget(n, log)
    while not B.done():
        sols, fits = [], []
        while len(sols) < es.popsize and not B.done():
            s = es.ask(1)[0]
            d = B.eval(fieldf(s), kind)
            if d is None:
                # illegal: penalise by distance from feasibility, no CFD
                sols.append(s)
                fits.append(1e3 + np.sum(np.abs(s)))
            else:
                sols.append(s)
                fits.append(d)
        if len(sols) == es.popsize:
            es.tell(sols, fits)
    return B


def run(method, seed, n):
    OUT.mkdir(exist_ok=True)
    log = []
    if method == "cppn-neat":
        B = run_neat(seed, n, log)
    elif method == "random":
        B = run_neat(seed, n, log, random_only=True)
    else:
        B = run_cma(seed, n, log, method)
    tag = f"{method}_s{seed}"
    (OUT / f"{tag}.json").write_text(json.dumps({"method": method, "seed": seed, "log": log,
                                                 "best": B.best[0], "illegal": B.illegal}))
    if B.best[1] is not None:
        np.save(OUT / f"{tag}_best.npy", B.best[1])
    print(tag, "best", B.best[0], "used", B.used, "illegal", B.illegal, flush=True)


def refs():
    """Hand references: wheels alone, the smallest legal body, and a designer teardrop."""
    OUT.mkdir(exist_ok=True)
    out = {"wheels_only": score(np.zeros_like(MUST))}
    minimal = finish(np.where(((X >= 95) & (X <= 196) & (Y >= 15) & (Y <= 31)) | MUST, 1.0, -1.0))
    tear = finish(np.where((((X - 125) / 85.0) ** 2 + ((Y - 19) / 14.0) ** 2 <= 1), 1.0, -1.0))
    for k, b in (("minimal_bridge", minimal), ("designer_teardrop", tear)):
        out[k] = None if b is None else score(b)
        if b is not None:
            np.save(OUT / f"ref_{k}.npy", b)
    (OUT / "refs.json").write_text(json.dumps(out, indent=1))
    print(out)


if __name__ == "__main__":
    if sys.argv[1] == "refs":
        refs()
    else:
        run(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
