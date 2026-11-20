"""Render a topology result next to the team's sidepod: grey = the car without sidepods (kept CAD),
orange = sidepod material (team's design / the optimiser's beta > 0.5, mirrored to both sides).

    python topo/show.py <case> [--time latest] [--out topo/<case>_tN.png]
"""
import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy.spatial import cKDTree  # noqa: E402

HERE = Path(__file__).resolve().parent
SP = HERE.parent
sys.path.insert(0, str(SP)); sys.path.insert(0, str(HERE))
import render as RD  # noqa: E402
from extract import foam_scalar_field, foam_vector_field, latest_time  # noqa: E402
from geometry import Car  # noqa: E402


def topo_mask(car, case, t):
    C = foam_vector_field(case / "0" / "C")
    beta = foam_scalar_field(case / t / "beta")
    idx = np.argwhere(car.region)
    s = car.s
    P = np.c_[(s.x_nose_mm - car.xs[idx[:, 0]]) * 1e-3, np.abs(car.ys[idx[:, 1]]) * 1e-3, car.zs[idx[:, 2]] * 1e-3]
    _, i = cKDTree(C).query(P)
    m = np.zeros(car.region.shape, bool)
    m[idx[:, 0], idx[:, 1], idx[:, 2]] = beta[i] > 0.5
    return m, beta[i]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case"); ap.add_argument("--time", default="latest"); ap.add_argument("--out")
    a = ap.parse_args()
    case = Path(a.case).resolve()
    t = latest_time(case) if a.time == "latest" else a.time
    if not (case / "0" / "C").exists():
        import subprocess
        subprocess.run(["bash", "-c", "source /usr/lib/openfoam/openfoam2412/etc/bashrc >/dev/null 2>&1; "
                        "postProcess -func writeCellCentres -time 0"], cwd=case, check=True, capture_output=True)
    car = Car()
    lean = car.body0 & ~car.region | car.cargo
    team = car.body0 & car.region
    mine, b = topo_mask(car, case, t)
    origin = (car.xs[0], car.ys[0], car.zs[0])
    fig = plt.figure(figsize=(14, 7.5))
    rows = [("team's sidepod", team), (f"topology, cycle {t} (beta > 0.5)", mine)]
    views = [(18, -60), (65, -90)]
    for r, (title, pod) in enumerate(rows):
        for c, (el, az) in enumerate(views):
            ax = fig.add_subplot(2, 2, 2 * r + c + 1, projection="3d")
            RD.surf(ax, lean, origin, car.h, "#9aa0a6", 1.0)
            RD.surf(ax, pod, origin, car.h, "#f08a24", 1.0)
            ax.set_xlim(40, 175); ax.set_ylim(-42, 42); ax.set_zlim(0, 45)
            ax.set_box_aspect((135, 84, 45), zoom=1.3); ax.view_init(el, az); ax.set_axis_off()
            if c == 0:
                ax.set_title(f"{title}: {pod.sum() * car.h ** 3 / 1e3:.1f} cm3", fontsize=11)
    fig.suptitle("Sidepod region: grey = car without sidepods, orange = sidepod material (nose at +x)", fontsize=12)
    out = Path(a.out) if a.out else HERE / f"{case.name}_t{t}.png"
    fig.savefig(out, dpi=110, bbox_inches="tight")
    print(out, "solid cm3 (both sides):", round(mine.sum() * car.h ** 3 / 1e3, 1),
          "grey share 0.1<beta<0.9:", round(float(((b > 0.1) & (b < 0.9)).mean()), 3))


if __name__ == "__main__":
    main()
