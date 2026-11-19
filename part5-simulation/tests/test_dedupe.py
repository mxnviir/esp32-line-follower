import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import dedupe


def test_identical_cars_are_timed_once_and_share_the_time():
    a, b = np.array([1.0, 2.0]), np.array([1.0, 2.0 + 1e-12])
    need = {"c1": (a, "cur"), "c2": (a.copy(), "conf"), "c3": (b, "cand")}
    todo = dedupe.plan(need, {}, set())
    assert todo == ["c1", "c3"]            # a tiny difference is a different car
    res = {"c1": 1.5, "c3": 1.6}
    assert dedupe.fill(need, res) == 1 and res["c2"] == 1.5


def test_running_cars_are_not_dispatched_again():
    a = np.zeros(3)
    need = {"c1": (a, "cur"), "c2": (a, "conf")}
    assert dedupe.plan(need, {}, {"c1"}) == []
