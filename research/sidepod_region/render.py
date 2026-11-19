"""Pictures: the sidepod region on the car, and any finished design."""
from __future__ import annotations
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from scipy import ndimage
from skimage import measure
import region as RG

LIGHT = np.array([0.4, -0.6, 0.7]); LIGHT /= np.linalg.norm(LIGHT)


def surf(ax, mask, origin, h, color, alpha=1.0, smooth=0.8):
    m = np.pad(mask.astype(float), 1)
    if smooth:
        m = ndimage.gaussian_filter(m, smooth)
    try:
        v, f, n, _ = measure.marching_cubes(m, 0.5)
    except (ValueError, RuntimeError):
        return
    v = (v - 1) * h + np.asarray(origin)
    tri = v[f]
    nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12
    shade = 0.35 + 0.65 * np.clip(np.abs(nrm @ LIGHT), 0, 1)
    col = np.array(matplotlib.colors.to_rgb(color))[None] * shade[:, None]
    pc = Poly3DCollection(tri, facecolors=np.c_[col, np.full(len(col), alpha)], linewidths=0)
    ax.add_collection3d(pc)


def setup(ax, elev, azim):
    ax.set_xlim(-30, 230); ax.set_ylim(-45, 45); ax.set_zlim(0, 45)
    ax.set_box_aspect((260, 90, 45), zoom=1.25); ax.view_init(elev, azim); ax.set_axis_off()


def region_masks_1mm():
    xs, ys, zs, body, wheels = RG.load_1mm()
    X, Y, Z = np.meshgrid(xs, np.abs(ys), zs, indexing="ij")
    box = ((X >= RG.REGION_X[0]) & (X <= RG.REGION_X[1]) & (Y <= RG.REGION_YMAX)
           & (Z >= RG.REGION_Z[0]) & (Z <= RG.REGION_Z[1]))
    dy = np.clip(Y - RG.FRONT_INNER_Y, 0, None)
    t792 = (Y >= RG.FRONT_INNER_Y) & (X >= RG.X_FRONT_AXLE - RG.R_WHEEL - (15 + dy / np.tan(np.radians(60)))) & (X <= RG.X_FRONT_AXLE)
    dy = np.clip(Y - RG.REAR_INNER_Y, 0, None)
    t793 = (Y >= RG.REAR_INNER_Y) & (X <= RG.X_REAR_AXLE + RG.R_WHEEL + 5 + dy) & (X >= RG.X_REAR_AXLE)
    spine = (Y <= RG.SPINE_Y) & (Z >= RG.SPINE_Z)
    hw = 5.0 + (X - RG.CARGO_X[0]) / (RG.CARGO_X[1] - RG.CARGO_X[0]) * 22.5
    cargo = (X >= RG.CARGO_X[0]) & (X <= RG.CARGO_X[1]) & (Y <= hw) & (Z >= RG.CARGO_Z[0]) & (Z <= RG.CARGO_Z[1])
    halo = (X >= RG.HALO_X[0]) & (Z > RG.HALO_ZMIN)
    region = box & ~t792 & ~t793 & ~spine & ~halo
    zones = (t792 | t793) & (Z <= 40)
    o = (xs[0] - 0.5, ys[0] - 0.5, zs[0] - 0.5)
    return dict(origin=o, body=body, wheels=wheels, region=region, cargo=cargo, zones=zones,
                kept=body & ~box | (body & spine))


def region_figure(path):
    M = region_masks_1mm()
    fig = plt.figure(figsize=(16, 9))
    views = [(28, 52, "3/4 front (like your sketch)"), (22, 130, "3/4 rear"),
             (90, -90, "top"), (0, -90, "side (left)")]
    for k, (el, az, title) in enumerate(views):
        ax = fig.add_subplot(2, 2, k + 1, projection="3d")
        surf(ax, M["kept"], M["origin"], 1.0, "#555b66")
        surf(ax, M["wheels"], M["origin"], 1.0, "#d8c8a0")
        surf(ax, M["region"], M["origin"], 1.0, "#e0312b", alpha=0.35, smooth=0.6)
        surf(ax, M["cargo"], M["origin"], 1.0, "#2f6fd6", alpha=0.9, smooth=0.4)
        surf(ax, M["zones"], M["origin"], 1.0, "#f2a516", alpha=0.18, smooth=0.4)
        setup(ax, el, az); ax.set_title(title, fontsize=10)
    fig.suptitle("Sidepod design region (red, both sides) | kept body (grey) | T4.2 cargo, must stay solid (blue) | "
                 "T7.9.2/T7.9.3 keep-clear wedges, must stay air (orange)", fontsize=11)
    fig.subplots_adjust(left=0, right=1, bottom=0, top=0.93, wspace=0, hspace=0)
    fig.savefig(path, dpi=110); plt.close(fig)


def design_figure(path, designs, car):
    """designs: list of (title, half_body_3mm)."""
    xs, ys, zs, _body, wheels = RG.load_1mm()
    n = len(designs)
    fig = plt.figure(figsize=(5.2 * min(n, 3), 4.0 * ((n + 2) // 3)))
    for k, (title, half) in enumerate(designs):
        ax = fig.add_subplot((n + 2) // 3, min(n, 3), k + 1, projection="3d")
        full = car.full(half)
        o = (car.xs[0] - 1.5, -car.ys[-1] - 1.5, car.zs[0] - 1.5)
        surf(ax, full, o, 3.0, "#5d6f86", smooth=1.0)
        surf(ax, wheels, (xs[0] - .5, ys[0] - .5, zs[0] - .5), 1.0, "#d8c8a0")
        setup(ax, 28, 52); ax.set_title(title, fontsize=9)
    fig.subplots_adjust(left=0, right=1, bottom=0, top=0.95, wspace=0, hspace=0.05)
    fig.savefig(path, dpi=100); plt.close(fig)


if __name__ == "__main__":
    region_figure(RG.HERE / "results/region.png")
