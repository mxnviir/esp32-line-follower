"""Zero-CFD check: what do organically grown (CPPN) bodies look like after Part 1's real pipeline?

A CPPN is evaluated on every cell of the car's 1 mm grid, its output becomes the body field,
and Part 1's param_body.build(field_mm=...) applies every rule mask, symmetry, the joins, island
removal and (optionally) the 6.35 mm ball-end milling. We record whether each body survives,
how much the pipeline had to change it, how different the bodies are from each other, and how
much a single mutation changes a body (heritability). Pictures go to results3d/.

    python geom3d.py sample  <n_per_level> [machinable 0|1]
    python geom3d.py herit   <n_parents>
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
P1 = HERE.parents[1] / "part1-simulation"
sys.path.insert(0, str(P1))
import coarse  # noqa: E402

coarse.use_spacing(1.0)
import param_body as pb  # noqa: E402
import unified_phi as up  # noqa: E402
from scipy import ndimage  # noqa: E402

OUT = HERE / "results3d"
LAYOUT = (120.3, 46.0, 43.72)
ACT = {
    "sigmoid": lambda z: 1 / (1 + np.exp(-np.clip(5 * z, -60, 60))),
    "tanh": lambda z: np.tanh(np.clip(2.5 * z, -60, 60)),
    "sin": lambda z: np.sin(np.clip(5 * z, -60, 60)),
    "gauss": lambda z: np.exp(-5 * np.clip(z, -3.4, 3.4) ** 2),
    "abs": np.abs,
    "identity": lambda z: z,
}


def fresh(cfg, k):
    import neat
    if not hasattr(cfg, "_pool") or not cfg._pool:
        cfg._pool = list(neat.Population(cfg).population.values())
    return cfg._pool.pop()


def config():
    import neat
    sys.path.insert(0, str(HERE))
    import evolve2d
    p = OUT / "neat3d.cfg"
    evolve2d.neat_config(p)
    txt = p.read_text().replace("num_inputs            = 5", "num_inputs            = 7")
    p.write_text(txt)
    return neat.Config(neat.DefaultGenome, neat.DefaultReproduction, neat.DefaultSpeciesSet,
                       neat.DefaultStagnation, str(p))


_BASE = {}


def base():
    if not _BASE:
        g = up.build_unified_geometry(*LAYOUT, init_mode="full")
        r, d = g.region, up.GRID_SPACING_M
        xs = (r.origin_m[0] + np.arange(r.shape[0]) * d) * 1e3
        ys = (r.origin_m[1] + np.arange(r.shape[1]) * d) * 1e3
        zs = (r.origin_m[2] + np.arange(r.shape[2]) * d) * 1e3
        X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
        hs, ha = g.phi.hard_mask_solid, g.phi.hard_mask_air
        d_s = ndimage.distance_transform_edt(~hs)
        d_a = ndimage.distance_transform_edt(~ha)
        L = g.landmarks
        inputs = np.stack([
            (X - 0.5 * (xs[0] + xs[-1])) / 110.0,
            np.abs(Y) / 32.0,
            (Z - 25.0) / 25.0,
            d_s / 20.0,
            d_a / 20.0,
            (X - L["front_axle_m"] * 1e3) / 60.0,
            (X - L["rear_axle_m"] * 1e3) / 60.0,
        ], -1)
        _BASE.update(g=g, X=X, Y=Y, Z=Z, inputs=inputs, hs=hs, ha=ha)
    return _BASE


def cppn_field(genome, cfg):
    """Vectorised CPPN on the whole grid. Returns field in mm, negative inside (Part 1's sign)."""
    import neat
    genome.nodes[cfg.genome_config.output_keys[0]].activation = "tanh"   # output in [-1, 1]
    net = neat.nn.FeedForwardNetwork.create(genome, cfg)
    I = base()["inputs"]
    vals = {k: I[..., i] for i, k in enumerate(cfg.genome_config.input_keys)}
    for node, _act, _agg, bias, resp, links in net.node_evals:
        s = np.full(I.shape[:-1], bias, dtype=np.float64)
        for i, w in links:
            s = s + w * vals[i]
        vals[node] = ACT[genome.nodes[node].activation](resp * s)
    out = vals[cfg.genome_config.output_keys[0]]
    return -8.0 * out            # positive CPPN output = solid; ~mm scale before reinitialisation


def body(field_mm, machinable):
    t = time.time()
    try:
        g = pb.build(*LAYOUT, pb.BodyParams(), skin_offset_mm=0.0, machinable=machinable, field_mm=field_mm)
    except Exception as e:                                       # a crash is a finding
        return None, {"error": repr(e)[:300], "s": time.time() - t}
    solid = g.phi.grid < 0
    lab, n = ndimage.label(solid)
    rep = {k: (float(v) if isinstance(v, (int, float, np.floating, np.integer)) else str(v))
           for k, v in g.build_report.items()}
    mass = sum(c.mass_kg for c in up.compute_mass_com(g))
    rep.update(pieces=int(n), cells=int(solid.sum()), body_g=round(mass * 1e3, 2), s=round(time.time() - t, 1))
    return solid, rep


def iou(a, b):
    return float((a & b).sum() / max((a | b).sum(), 1))


def render(solid, path, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from skimage import measure
    B = base()
    fig = plt.figure(figsize=(13, 3.6))
    ax = fig.add_subplot(1, 4, 1, projection="3d")
    s = ndimage.gaussian_filter(solid.astype(float), 0.7)
    try:
        v, f, *_ = measure.marching_cubes(s, 0.5)
        ax.plot_trisurf(v[:, 0], v[:, 1] - solid.shape[1] / 2, f, v[:, 2], color="#7aa6c2", lw=0, alpha=1)
    except Exception:
        pass
    ax.view_init(22, -60)
    ax.set_box_aspect((solid.shape[0], solid.shape[1], solid.shape[2]))
    ax.set_axis_off()
    for k, (axis, name) in enumerate([(2, "top"), (1, "side"), (0, "front")]):
        a2 = fig.add_subplot(1, 4, k + 2)
        a2.imshow(solid.any(axis=axis).T if axis != 0 else solid.any(axis=0).T, origin="lower", cmap="Greys")
        a2.set_title(name, fontsize=8)
        a2.set_xticks([])
        a2.set_yticks([])
    fig.suptitle(title, fontsize=9)
    fig.savefig(path, dpi=90, bbox_inches="tight")
    plt.close(fig)


def sample(n, machinable):
    import random
    OUT.mkdir(exist_ok=True)
    cfg = config()
    random.seed(0)
    rows, bodies = [], []
    base()
    for level in (0, 10, 40):                   # structural mutations applied: grows the network
        for i in range(n):
            g = fresh(cfg, i)
            for _ in range(level):
                g.mutate(cfg.genome_config)
            f = cppn_field(g, cfg)
            raw_solid = (f < 0) & ~base()["ha"]
            sb, rep = body(f, machinable)
            rep.update(level=level, i=i, nodes=len(g.nodes), conns=len(g.connections),
                       raw_cells=int(raw_solid.sum()))
            if sb is not None:
                rep["iou_raw_vs_finished"] = iou(raw_solid | base()["hs"], sb)
                bodies.append((level, i, sb))
                render(sb, OUT / f"body_L{level}_{i}_m{int(machinable)}.png",
                       f"level {level} #{i}: nodes {len(g.nodes)}, {rep['body_g']} g, pieces {rep['pieces']}")
            rows.append(rep)
            print(json.dumps(rep), flush=True)
    div = [iou(a[2], b[2]) for k, a in enumerate(bodies) for b in bodies[k + 1:]]
    summary = {"n": len(rows), "built": len(bodies), "crashed": sum("error" in r for r in rows),
               "median_pairwise_iou": float(np.median(div)) if div else None,
               "median_iou_raw_vs_finished": float(np.median([r["iou_raw_vs_finished"] for r in rows
                                                              if "iou_raw_vs_finished" in r]))}
    (OUT / f"sample_m{int(machinable)}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    print("SUMMARY", summary)


def herit(n):
    """Parents at level 6; each gets 4 single-mutation children (weights only) and 4 with one
    structural mutation. Heritability = IoU(parent body, child body)."""
    import copy
    import random
    OUT.mkdir(exist_ok=True)
    cfg = config()
    random.seed(1)
    res = []
    for p in range(n):
        g = fresh(cfg, p)
        for _ in range(6):
            g.mutate(cfg.genome_config)
        pb_, _ = body(cppn_field(g, cfg), False)
        if pb_ is None:
            continue
        for kind in ("weights", "structural"):
            for c in range(4):
                ch = copy.deepcopy(g)
                if kind == "weights":
                    for cg in ch.connections.values():
                        cg.weight += random.gauss(0, 0.15)
                else:
                    ch.mutate_add_node(cfg.genome_config) if random.random() < 0.5 else ch.mutate_add_connection(cfg.genome_config)
                cb, _ = body(cppn_field(ch, cfg), False)
                if cb is not None:
                    res.append({"parent": p, "kind": kind, "iou": iou(pb_, cb)})
                    print(json.dumps(res[-1]), flush=True)
    for kind in ("weights", "structural"):
        v = [r["iou"] for r in res if r["kind"] == kind]
        print("HERIT", kind, "n", len(v), "median IoU", np.median(v) if v else None,
              "10th pct", np.percentile(v, 10) if v else None)
    (OUT / "herit.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    if sys.argv[1] == "sample":
        sample(int(sys.argv[2]), bool(int(sys.argv[3])) if len(sys.argv) > 3 else False)
    else:
        herit(int(sys.argv[2]))
