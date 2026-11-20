"""Render a millable design (zb, zt surfaces) as the milled car would be: grey = car without
sidepods, orange = the pod after the full manufacturability projection, blue = virtual cargo,
red plane = the 27.0 mm ceiling (the team's sidepod top). Top row: the team's sidepod.

    python topo/show_mill.py <case> [--npz cma_best.npz] [--out file.png]
"""
import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
import mill_topo as M  # noqa: E402
import render as RD  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case"); ap.add_argument("--npz", default="cma_best.npz"); ap.add_argument("--out")
    ap.add_argument("--title", default="optimiser")
    a = ap.parse_args()
    case = Path(a.case)
    import mill_cma as C
    x, r, (zb, zt, B, rep), cols, P = C.best_legal(case)          # built once from its own variables
    car = cols.car
    print("design: J", r["J"], "gen", r["gen"])
    pod = B & cols.reg & ~car.cargo
    team = car.body0 & car.region & ~car.cargo
    lean = cols.lean & ~car.cargo
    origin = (car.xs[0], car.ys[0], car.zs[0])
    fig = plt.figure(figsize=(15, 8.5))
    views = [(20, -60), (88, -90), (0, -90)]
    for r, (title, p) in enumerate([("team's sidepod", team), (a.title, pod)]):
        for c, (el, az) in enumerate(views):
            ax = fig.add_subplot(2, 3, 3 * r + c + 1, projection="3d")
            RD.surf(ax, lean, origin, car.h, "#9aa0a6", 1.0)
            RD.surf(ax, p, origin, car.h, "#f08a24", 1.0)
            RD.surf(ax, car.cargo, origin, car.h, "#1f6feb", 1.0)
            if c == 2:                                               # side view: the ceiling
                ax.plot([40, 175], [0, 0], [M.Z_CEIL_MM] * 2, color="red", lw=1.5)
            ax.set_xlim(40, 175); ax.set_ylim(-42, 42); ax.set_zlim(0, 45)
            ax.set_box_aspect((135, 84, 45), zoom=1.3); ax.view_init(el, az); ax.set_axis_off()
            if c == 0:
                ax.set_title(f"{title}: {p.sum() * car.h ** 3 / 1e3:.1f} cm3 (both sides)", fontsize=11)
    top = car.zs[np.nonzero(pod.any(axis=(0, 1)))[0]].max() + 0.5 * car.h if pod.any() else 0
    fig.suptitle(f"grey = car without sidepods, orange = pod as milled (top/bottom, 3.175 mm ball, 3 mm walls), "
                 f"blue = cargo, red line = 27.0 mm ceiling; pod top = {top:.1f} mm; rules ok = {car.check(B)['ok']}",
                 fontsize=10)
    out = Path(a.out) if a.out else case / "best.png"
    fig.savefig(out, dpi=105, bbox_inches="tight")
    print(out, "pod top mm", top, "check", car.check(B))


if __name__ == "__main__":
    main()
