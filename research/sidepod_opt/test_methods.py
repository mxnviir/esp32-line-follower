"""Regression test for the ask/tell bookkeeping (run: python test_methods.py). SPSA with several
pairs per batch and an illegal half told before its partner; CMA handed out in batches smaller than
a generation; both pickled between calls, as the campaign does."""
import sys, pickle; from pathlib import Path; sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, methods as MT
class Rep:
    def x0(self, s): return np.zeros(6)
f = lambda x: float(((np.asarray(x) - 1.0) ** 2).sum())
# SPSA: batch 6 (3 pairs), one illegal half told first, its partner later
m = MT.make("spsa", Rep(), "o", np.random.default_rng(0), c=0.3, a=0.5)
for it in range(60):
    xs = m.ask(6)
    m.tell([xs[0]], [None])                                 # illegal, told at once
    m.tell(xs[1:], [f(x) for x in xs[1:]])
    assert not m.pending, "pairs left pending"
    m = pickle.loads(pickle.dumps(m))
print("spsa f", round(f(m.x), 4), "from", f(np.zeros(6)))
# CMA: popsize 8 handed out in batches of 3, pickled between, an older-gen result ignored
m = MT.make("cma", Rep(), "o", np.random.default_rng(0), popsize=8, sigma=0.5)
gens = 0
for it in range(120):
    xs = m.ask(3)
    assert xs, "empty ask"
    g0 = m.es.countiter
    m.tell(xs, [None if k == 0 and it % 5 == 0 else f(x) for k, x in enumerate(xs)])
    m = pickle.loads(pickle.dumps(m))
    gens += m.es.countiter > g0
print("cma generations", gens, "best", round(min(m.Y), 4))
assert f(MT.make("spsa", Rep(), "o", np.random.default_rng(0)).x0) == 6.0
