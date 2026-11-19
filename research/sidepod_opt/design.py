"""Representations: parameters -> design field over the region (mm, + = foam, full 1 mm grid).

Every representation can start from either seed shape, and steps are big enough to go from
one to the other (the first runs could not reach "no pods" from the box):
  seed "original"  the team's sidepod (signed distance of the drawn body)
  seed "lean"      no sidepod: only the T4.2 cargo
  seed "blend"     halfway (a free parameter t in [0, 1] mixes the two)

  Lattice(n)    a coarse control grid, cubic-interpolated, added to the seed     (CMA-ES, BO, SAIL, SPSA)
  CPPN          a NEAT network of (x, |y|, z, d_cargo, sdf_original, sdf_lean)  (NEAT)
  LevelSet(h)   the field itself on a 2 mm grid (every cell is a variable)      (adjoint, SPSA)
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage


class Lattice:
    def __init__(self, car, shape=(10, 4, 5), amp_mm=12.0, seed="blend"):
        self.car, self.shape, self.amp, self.seed = car, tuple(shape), amp_mm, seed
        self.dim = int(np.prod(shape)) + (1 if seed == "blend" else 0)

    def x0(self, start: str):
        x = np.zeros(self.dim)
        if self.seed == "blend":
            x[-1] = {"original": 3.0, "lean": -3.0}.get(start, 0.0)   # logit of the mix t
        return x

    def field(self, x):
        c = self.car
        x = np.asarray(x, float)
        if self.seed == "blend":
            t = 1.0 / (1.0 + np.exp(-x[-1]))
            base = t * c.sdf_original + (1 - t) * c.sdf_lean
            g = x[:-1]
        else:
            base = c.sdf_original if self.seed == "original" else c.sdf_lean
            g = x
        f = base.copy()
        # the lattice spans the +y half of the region; mirror to -y
        j0 = np.searchsorted(c.ys, 0.0)
        lo, hi = c.rlo.copy(), c.rhi.copy()
        lo[1] = max(lo[1], j0)
        n = hi - lo
        up = ndimage.zoom(g.reshape(self.shape), n / np.array(self.shape), order=3, mode="nearest")[: n[0], : n[1], : n[2]]
        add = np.zeros_like(f)
        add[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]] = self.amp * up
        add[:, :j0] = add[:, j0:][:, ::-1][:, : j0]
        return f + add


class LevelSet:
    """The field itself on a coarser grid (h_mm), every cell a variable; x is flattened."""

    def __init__(self, car, h_mm=2.0):
        self.car, self.k = car, max(1, int(round(h_mm / car.h)))
        j0 = np.searchsorted(car.ys, 0.0)
        self.sl = (slice(car.rlo[0], car.rhi[0]), slice(max(car.rlo[1], j0), car.rhi[1]), slice(car.rlo[2], car.rhi[2]))
        sub = car.region[self.sl]
        self.cshape = tuple(int(np.ceil(s / self.k)) for s in sub.shape)
        self.dim = int(np.prod(self.cshape))

    def x0(self, start):
        c = self.car
        base = c.sdf_original if start == "original" else c.sdf_lean
        sub = base[self.sl]
        return sub[:: self.k, :: self.k, :: self.k][: self.cshape[0], : self.cshape[1], : self.cshape[2]].ravel().astype(float)

    def field(self, x):
        c = self.car
        g = np.asarray(x, float).reshape(self.cshape)
        sub_shape = c.region[self.sl].shape
        up = ndimage.zoom(g, np.array(sub_shape) / np.array(self.cshape), order=1)[: sub_shape[0], : sub_shape[1], : sub_shape[2]]
        f = c.sdf_lean.copy()
        f[self.sl] = up
        j0 = np.searchsorted(c.ys, 0.0)
        f[:, :j0] = f[:, j0:][:, ::-1][:, : j0]
        return f

    def field_grad_to_x(self, gfield):
        """Chain a gradient w.r.t. the 1 mm field back to x (adjoint of field())."""
        sub = gfield[self.sl]
        k = self.k
        pad = [(0, s * k - sub.shape[i]) for i, s in enumerate(self.cshape)]
        sub = np.pad(sub, pad)
        return sub.reshape(self.cshape[0], k, self.cshape[1], k, self.cshape[2], k).sum((1, 3, 5)).ravel()


class CPPNInputs:
    def __init__(self, car):
        d_cargo = ndimage.distance_transform_edt(~car.cargo) * car.h
        self.I = np.concatenate([car.norm, (d_cargo / 20.0)[..., None], (car.sdf_original / 10.0)[..., None],
                                 (car.sdf_lean / 10.0)[..., None]], -1).astype(np.float32)


ACT = {"sigmoid": lambda z: 1 / (1 + np.exp(-np.clip(5 * z, -60, 60))), "tanh": lambda z: np.tanh(np.clip(2.5 * z, -60, 60)),
       "sin": lambda z: np.sin(np.clip(5 * z, -60, 60)), "gauss": lambda z: np.exp(-5 * np.clip(z, -3.4, 3.4) ** 2),
       "abs": np.abs, "identity": lambda z: z}


def cppn_field(genome, cfg, inputs: CPPNInputs, scale_mm=8.0):
    import neat
    net = neat.nn.FeedForwardNetwork.create(genome, cfg)
    I = inputs.I
    vals = {k: I[..., i] for i, k in enumerate(cfg.genome_config.input_keys)}
    for node, _a, _g, bias, resp, links in net.node_evals:
        s = np.full(I.shape[:-1], bias, np.float32)
        for i, w in links:
            s = s + w * vals[i]
        vals[node] = ACT[genome.nodes[node].activation](resp * s)
    return vals[cfg.genome_config.output_keys[0]] * scale_mm
