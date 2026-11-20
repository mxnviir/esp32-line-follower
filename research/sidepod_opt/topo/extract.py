"""Turn a topology result into a real car and time it with body-fitted CFD.

The porous design field (beta: 0 = air, 1 = solid) is sampled on the 1 mm voxel grid of the sidepod
region, then sent through the same pipeline as every other design:
finish -> mill -> 3 mm minimum wall -> rule checks -> mass -> exact watertight export.
Optionally it is timed with Part 2's ordinary OpenFOAM solve, at the same resolution as the
lean and original cars, so the porous model's verdict is checked on a real wall.

    python topo/extract.py <case> [--time latest] [--cfd] [--res coarse]
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parent
SP = HERE.parent
sys.path.insert(0, str(SP)); sys.path.insert(0, str(SP.parents[1] / "part2-simulation"))
from geometry import Car  # noqa: E402

BASHRC = "/usr/lib/openfoam/openfoam2412/etc/bashrc"


def foam_scalar_field(p: Path) -> np.ndarray:
    t = p.read_text()
    m = re.search(r"internalField\s+nonuniform\s+List<scalar>\s*(\d+)\s*\(", t)
    if m:
        n = int(m.group(1))
        return np.array(t[m.end():].split(")", 1)[0].split()[:n], float)
    u = re.search(r"internalField\s+uniform\s+([-+\deE.]+)", t)
    return None if u is None else float(u.group(1))


def foam_vector_field(p: Path) -> np.ndarray:
    t = p.read_text()
    m = re.search(r"internalField\s+nonuniform\s+List<vector>\s*(\d+)\s*\(", t)
    n = int(m.group(1))
    return np.array([list(map(float, s.split())) for s in re.findall(r"\(([^()]+)\)", t[m.end():])[:n]])


def latest_time(case: Path) -> str:
    ts = [p.name for p in case.iterdir() if p.is_dir() and re.fullmatch(r"[\d.]+", p.name) and p.name != "0"]
    return max(ts, key=float)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case")
    ap.add_argument("--time", default="latest")
    ap.add_argument("--field", default="beta")
    ap.add_argument("--cfd", action="store_true")
    ap.add_argument("--res", default="coarse")
    a = ap.parse_args()
    case = Path(a.case).resolve()
    t = latest_time(case) if a.time == "latest" else a.time
    if not (case / "0" / "C").exists():
        subprocess.run(["bash", "-c", f"source {BASHRC} && postProcess -func writeCellCentres -time 0"],
                       cwd=case, check=True, capture_output=True)
    C = foam_vector_field(case / "0" / "C")
    beta = foam_scalar_field(case / t / a.field)
    car = Car()
    s = car.s
    # voxel centres of the region -> CFD frame -> nearest cell's beta
    idx = np.argwhere(car.region)
    X, Y, Z = car.xs[idx[:, 0]], car.ys[idx[:, 1]], car.zs[idx[:, 2]]
    P = np.c_[(s.x_nose_mm - X) * 1e-3, np.abs(Y) * 1e-3, Z * 1e-3]
    d, i = cKDTree(C).query(P)
    vb = beta[i]
    field = np.full(car.body0.shape, -1.0)
    field[idx[:, 0], idx[:, 1], idx[:, 2]] = vb - 0.5          # solid where beta > 0.5
    b = car.build(field)
    out = case / f"car_t{t}"
    rep = {"time": t, "region_voxels": int(len(idx)), "solid_voxels_beta>0.5": int((vb > 0.5).sum()),
           "beta_mean_in_region": float(vb.mean()), "check": b["check"], "mill": b["mill"]}
    if b["check"]["ok"]:
        car.export_car_folder(b["mesh"], out, f"topo_t{t}")
        rep["mass"] = b["mass"]; rep["folder"] = str(out)
        if a.cfd:
            import gate
            half, health, secs = gate.solve(out, 4, 2000, extra={"resolution": a.res})
            rep["cfd"] = {"D20_half_N": float(half.D20), "wall_s": secs, "converged": bool(health.converged)}
    (case / f"extract_t{t}.json").write_text(json.dumps(rep, indent=1, default=float))
    print(json.dumps(rep, default=float)[:1500])


if __name__ == "__main__":
    main()
