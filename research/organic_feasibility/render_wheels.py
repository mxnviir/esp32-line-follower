"""Render organic bodies with the wheels in place (body = Part 1 milled body only)."""
import os, sys, random
os.environ["SMOOTH"] = "1"
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import geom3d as G
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from skimage import measure
from scipy import ndimage

cfg = G.config(); random.seed(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
B = G.base(); r = B["g"].region
x0, y0, z0 = (np.array(r.origin_m) * 1e3)
fig = plt.figure(figsize=(14, 8))
for k in range(4):
    g = G.fresh(cfg, k)
    for _ in range(10 * k):
        g.mutate(cfg.genome_config)
    solid, rep = G.body(G.cppn_field(g, cfg), True)       # with the 6.35 mm ball-end milling
    pad = 8
    S = np.pad(solid, ((0, 0), (pad, pad), (0, 0)))
    nx, ny, nz = S.shape
    X, Y, Z = np.meshgrid(x0 + np.arange(nx), y0 - pad + np.arange(ny), z0 + np.arange(nz), indexing="ij")
    W = np.zeros_like(S)
    for xa, yi, yo in ((46.0, 23.25, 36.5), (166.3, 16.25, 33.5)):
        W |= ((X - xa) ** 2 + (Z - 14.13) ** 2 <= 14.13 ** 2) & (np.abs(Y) >= yi) & (np.abs(Y) <= yo)
    ax = fig.add_subplot(2, 2, k + 1, projection="3d")
    for M, col in ((S, "#7aa6c2"), (W, "#222222")):
        v, f, *_ = measure.marching_cubes(ndimage.gaussian_filter(M.astype(float), 0.7), 0.5)
        ax.plot_trisurf(v[:, 0], v[:, 1], f, v[:, 2], color=col, lw=0)
    ax.view_init(25, -55); ax.set_box_aspect((nx, ny, nz)); ax.set_axis_off()
    ax.set_title(f"random organic body {k}: {rep.get('body_g')} g foam, milled", fontsize=9)
out = os.path.join(os.path.dirname(__file__), "results3d", "with_wheels.png")
fig.savefig(out, dpi=110, bbox_inches="tight"); print(out)
