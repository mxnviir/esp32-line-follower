"""run_car --carve-json: the body is carve.save on the recipe's layout and edits, the same field byte
for byte, and the recipe's layout sets W, x_front and d_halo."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import paths  # noqa: F401,E402

import numpy as np  # noqa: E402

LAYOUT = {"W": 126.0, "x_front": 48.0, "d_halo": 50.0}
EDITS = [{"bumps": [{"c_mm": [120.0, 10.0, 20.0], "amp_mm": -1.0, "sigma_mm": 10.0}], "unit": False}]


def _sha(p):
    return hashlib.sha256(np.ascontiguousarray(np.load(p)).tobytes()).hexdigest()


def test_carve_json_is_carve_save(tmp_path, monkeypatch):
    import carve
    import run_car
    real = carve.save
    a = argparse.Namespace(carve_json=json.dumps({"layout": LAYOUT, "edits": EDITS}), phi_npy=None,
                           W=120.3, x_front=46.0, d_halo=43.72, cfd_mm=2.0)   # 2 mm: quick; the car's grid is used
    p = run_car.carve_recipe(a, tmp_path)
    assert a.phi_npy == str(p) and (a.W, a.x_front, a.d_halo) == (126.0, 48.0, 50.0)
    real(LAYOUT, EDITS, tmp_path / "direct.npy", spacing_mm=2.0)
    assert _sha(p) == _sha(tmp_path / "direct.npy")


def test_carve_json_and_phi_npy_together_is_refused(tmp_path):
    import pytest
    import run_car
    a = argparse.Namespace(carve_json=json.dumps({"layout": LAYOUT, "edits": []}), phi_npy="x.npy")
    with pytest.raises(SystemExit):
        run_car.carve_recipe(a, tmp_path)
