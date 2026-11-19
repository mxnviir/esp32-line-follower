"""Adjoint option: density-based topology optimisation with a differentiable tunnel (JAX).

The same D3Q19 regularized-BGK + Smagorinsky tunnel as lbm3d.py, written in JAX so reverse-mode
AD gives the exact gradient of the discrete solver (a discrete adjoint by construction).
Fixed solids (kept body, cargo, wheels + plinths) use bounce-back as in lbm3d. Design cells
carry a solid fraction rho in [0, 1] and act by partial bounce-back (Walsh et al. 2009):
    f_out = (1 - g) * f_collided + g * f_bounced,  g = rho^p   (p = 2: grey is penalised)
rho comes from a level field theta through a smoothing filter and a sigmoid (organic shapes,
no cell-sized noise). The objective is RACE TIME: drag and lift from the run, foam mass and
COM from rho, ballast to 48.2 g, all through Part 2's race model (also JAX). So the gradient
is d(race time)/d(theta) with every exchange rate exact.

Cost accounting: one gradient = forward + reverse through the run, ~3-4 forward runs on this
machine; a production adjoint (OpenFOAM/DAFoam) costs ~1-2. The comparison charges 2 runs
per gradient step (what it would cost in practice) and reports the real wall time too.
"""
from __future__ import annotations
import numpy as np
import jax
import jax.numpy as jnp
from functools import partial
import lbm3d as L


C = jnp.asarray(L.C); Wt = jnp.asarray(L.W, jnp.float32)
OPP = np.asarray(L.OPP); FY = np.asarray(L.FY); FZ = np.asarray(L.FZ)
Cn = np.asarray(L.C)


def feq(rho, ux, uy, uz):
    cu = 3.0 * (C[:, 0, None, None, None] * ux + C[:, 1, None, None, None] * uy + C[:, 2, None, None, None] * uz)
    usq = ux * ux + uy * uy + uz * uz
    return Wt[:, None, None, None] * rho * (1.0 + cu + 0.5 * cu * cu - 1.5 * usq)


def make_step(solid, uf, U, tau0, cs2):
    """solid: fixed bounce-back cells (bool numpy). Returns step(f, gam) -> (f_new, force_fixed, force_design)."""
    nx, ny, nz = solid.shape
    solid_j = jnp.asarray(solid)
    src_solid = [jnp.asarray(np.roll(solid, tuple(Cn[i]), (0, 1, 2))) for i in range(19)]
    uf_j = jnp.asarray(uf, jnp.float32)
    fluid = ~solid_j
    feq_in = feq(jnp.float32(1.0), jnp.float32(U), jnp.float32(0.0), jnp.float32(0.0))[:, 0, 0, 0]

    def stream(fp):
        out = []
        for i in range(19):
            cx, cy, cz = (int(v) for v in Cn[i])
            g = jnp.roll(fp[i], (cx, cy, cz), (0, 1, 2))
            # y = 0 symmetry / y = ny-1 free slip: specular from the same row
            if cy != 0:
                j = int(FY[i])
                refl = jnp.roll(fp[j], (cx, 0, cz), (0, 1, 2))
                row = 0 if cy > 0 else ny - 1
                g = g.at[:, row, :].set(refl[:, row, :])
            if cz < 0:                                      # top free slip
                j = int(FZ[i])
                refl = jnp.roll(fp[j], (cx, cy, 0), (0, 1, 2))
                g = g.at[:, :, nz - 1].set(refl[:, :, nz - 1])
            # fixed solids: bounce-back (walls held still)
            g = jnp.where(src_solid[i], fp[int(OPP[i])], g)
            if cz > 0:                                      # road (moving at uf)
                bb = fp[int(OPP[i])][:, :, 0] + 6.0 * Wt[i] * cx * uf_j
                g = g.at[:, :, 0].set(bb)
            if cx > 0:                                      # inlet
                g = g.at[0].set(feq_in[i])
            if cx < 0:                                      # outlet: copy
                g = g.at[nx - 1].set(g[nx - 2])
            out.append(g)
        return jnp.stack(out)

    def fixed_force(fp, fin):
        """Momentum exchange on the fixed solids (x and z), from every bounced link."""
        fx = 0.0; fz = 0.0
        for i in range(19):
            s = jnp.where(src_solid[i] & fluid, fp[int(OPP[i])] + fin[i], 0.0).sum()
            fx = fx - Cn[i, 0] * s; fz = fz - Cn[i, 2] * s
        return fx, fz

    def step(fp, gam):
        fin = stream(fp)
        rho = fin.sum(0)
        ux = (fin * C[:, 0, None, None, None]).sum(0) / rho
        uy = (fin * C[:, 1, None, None, None]).sum(0) / rho
        uz = (fin * C[:, 2, None, None, None]).sum(0) / rho
        fe = feq(rho, ux, uy, uz)
        d = fin - fe
        cc = lambda a, b: (C[:, a] * C[:, b]).astype(jnp.float32)[:, None, None, None]
        pxx, pyy, pzz = (cc(0, 0) * d).sum(0), (cc(1, 1) * d).sum(0), (cc(2, 2) * d).sum(0)
        pxy, pxz, pyz = (cc(0, 1) * d).sum(0), (cc(0, 2) * d).sum(0), (cc(1, 2) * d).sum(0)
        q = jnp.sqrt(pxx ** 2 + pyy ** 2 + pzz ** 2 + 2 * (pxy ** 2 + pxz ** 2 + pyz ** 2) + 1e-20)
        tau = 0.5 * (tau0 + jnp.sqrt(tau0 * tau0 + 18.0 * 1.41421356 * cs2 * q / rho))
        om = 1.0 / tau
        qq = ((cc(0, 0) - 1 / 3) * pxx + (cc(1, 1) - 1 / 3) * pyy + (cc(2, 2) - 1 / 3) * pzz
              + 2 * (cc(0, 1) * pxy + cc(0, 2) * pxz + cc(1, 2) * pyz))
        fc = fe + (1.0 - om) * 4.5 * Wt[:, None, None, None] * qq
        fb = fin[OPP]                                        # on-node bounce-back
        fn = (1.0 - gam) * fc + gam * fb
        fn = jnp.where(solid_j, fp, fn)
        # force on the porous cells = momentum they remove
        dm = jnp.where(solid_j, 0.0, fin - fn)
        fdx = (dm * C[:, 0, None, None, None]).sum() ; fdz = (dm * C[:, 2, None, None, None]).sum()
        ffx, ffz = fixed_force(fp, fin)
        return fn.astype(fp.dtype), jnp.stack([ffx + fdx, ffz + fdz]).astype(fp.dtype)

    return step


def run_forces(step, f0, gam, steps, avg_from, seg=50):
    """Time-averaged (drag, lift) over [avg_from, steps), checkpointed in segments of `seg`."""
    nseg = steps // seg

    @jax.checkpoint
    def segment(carry, k):
        f, acc = carry

        def body(c, t):
            f, acc = c
            f2, F = step(f, gam)
            w = jnp.where(k * seg + t >= avg_from, 1.0, 0.0).astype(f.dtype)
            return (f2, acc + w * F), None
        (f, acc), _ = jax.lax.scan(body, (f, acc), jnp.arange(seg))
        return (f, acc), None
    (f, acc), _ = jax.lax.scan(segment, (f0, jnp.zeros(2, f0.dtype)), jnp.arange(nseg))
    return acc / (steps - avg_from), f
