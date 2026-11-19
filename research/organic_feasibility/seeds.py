"""Hand-built starting networks (seeds) for organic evolution.

Random CPPNs fill the legal block (~48 g of foam) and leave the shape to the rule zones. These
seeds start lean: each is a small network whose output is positive (solid) only near the
car's required solids, plus an optional organic feature. Evolution then grows or trims them.

Inputs (geom3d.base): 0 x centred, 1 |y|/32, 2 (z-25)/25, 3 dist to required solid /20 mm,
4 dist to required air /20 mm, 5 (x - front axle)/60, 6 (x - rear axle)/60.
Output node: tanh(2.5 * sum); positive = solid.

    python seeds.py build        # build, mill, render every seed; save fields for run_car
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

os.environ.setdefault("SMOOTH", "0")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import geom3d as G  # noqa: E402

IN = {"x": -1, "y": -2, "z": -3, "ds": -4, "da": -5, "xf": -6, "xr": -7}

# name: (hidden nodes [(key, activation, bias, {input: weight})], output bias, {source: weight})
SEEDS = {
    # a 3 mm skin round every required solid: the leanest legal-looking body
    "skin3": ([], 0.15, {"ds": -1.0}),
    # a 6 mm skin: rounder, heavier
    "skin6": ([], 0.30, {"ds": -1.0}),
    # 3 mm skin plus a slim central fuselage: centred on y = 0, z ~ 18 mm, about 18 mm wide
    "fuselage": ([(1, "gauss", 0.0, {"y": 1.8}),
                  (2, "gauss", 0.55, {"z": 1.8})],
                 -1.15, {"ds": -1.0, 1: 0.7, 2: 0.7}),
    # 3 mm skin plus low side pods between the axles (|y| ~ 20 mm, z ~ 12 mm)
    "pods": ([(1, "gauss", -1.3, {"y": 2.2}),
              (2, "gauss", 1.0, {"z": 2.5}),
              (3, "gauss", 0.0, {"x": 2.2})],
             -1.6, {"ds": -1.0, 1: 0.6, 2: 0.6, 3: 0.6}),
    # 3 mm skin plus a body that rises smoothly towards the tail (a wedge)
    "wedge": ([(1, "sigmoid", 0.0, {"x": 1.2, "z": -1.5}),
               (2, "gauss", 0.0, {"y": 1.6})],
              -0.95, {"ds": -1.0, 1: 0.5, 2: 0.5}),
}


def genome(name, cfg):
    hidden, out_bias, links = SEEDS[name]
    g = G.fresh(cfg, 0)
    gc = cfg.genome_config
    out = gc.output_keys[0]
    for k in list(g.connections):
        del g.connections[k]
    g.nodes[out].bias = out_bias
    g.nodes[out].response = 1.0
    g.nodes[out].activation = "tanh"
    trk = gc.innovation_tracker

    def conn(i, o, w):
        c = g.create_connection(gc, i, o, trk.get_innovation_number(i, o, "add_connection"))
        c.weight, c.enabled = w, True
        g.connections[(i, o)] = c
    for key, act, bias, ins in hidden:
        nk = 1000 + key
        n = g.create_node(gc, nk)
        n.bias, n.response, n.activation = bias, 1.0, act
        g.nodes[nk] = n
        for src, w in ins.items():
            conn(IN[src], nk, w)
    for src, w in links.items():
        conn(IN[src] if isinstance(src, str) else 1000 + src, out, w)
    return g


def build():
    cfg = G.config()
    G.OUT.mkdir(exist_ok=True)
    rows = {}
    for name in SEEDS:
        g = genome(name, cfg)
        f = G.cppn_field(g, cfg)
        np.save(G.OUT / f"seed_{name}_field_m.npy", (f / 1e3).astype(np.float32))
        solid, rep = G.body(f, True)
        rows[name] = rep
        if solid is not None:
            G.render(solid, G.OUT / f"seed_{name}.png", f"seed {name}: {rep.get('body_g')} g foam, milled")
        print(name, json.dumps({k: rep.get(k) for k in ("body_g", "pieces", "s", "error")}), flush=True)
    (G.OUT / "seeds.json").write_text(json.dumps(rows, indent=1, default=str))


if __name__ == "__main__":
    build()
