"""run_car --stress-car SEED:I rebuilds carved stress car I of SEED from (seed, i) alone: the
same recipe every time, the carve as carve.carve edits (2026-11-16, 2,000-body queue jobs)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "checks"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "part1-simulation"))


def test_same_seed_same_recipe_and_it_is_the_stress_car():
    import random
    import stress_cars as sc
    a, b = sc.run_car_args(3, 7), sc.run_car_args(3, 7)
    assert a == b and a != sc.run_car_args(3, 8)
    rng = random.Random(3)
    for _ in range(8):
        c = sc.random_carve(rng)
    r = json.loads(a[a.index("--carve-json") + 1])
    assert r["edits"] == sc.carve_edits(c)
    assert set(r["layout"]) == {"W", "x_front", "d_halo"}
