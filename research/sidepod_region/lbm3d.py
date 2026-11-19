"""Cheap 3-D wind tunnel: D3Q19 lattice Boltzmann, BGK + Smagorinsky LES, numba.

Half car (symmetry plane at y = 0). Flow along +X at U. Floor moves at U (rolling road).
Wheels rotate (their surface moves so the contact patch matches the floor). Top and outer
side are free slip, outlet copies. Solids: half-way bounce-back with the wall's velocity;
force from momentum exchange, split into body / wheels by a per-cell label.

Not the car's Reynolds number (~2e3 here vs ~3e5): it ranks shapes cheaply and must be
checked against OpenFOAM before its winners are trusted.
"""
from __future__ import annotations
import numpy as np
from numba import njit, prange

C = np.array([[0,0,0],[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1],
              [1,1,0],[-1,-1,0],[1,-1,0],[-1,1,0],[1,0,1],[-1,0,-1],[1,0,-1],[-1,0,1],
              [0,1,1],[0,-1,-1],[0,1,-1],[0,-1,1]], dtype=np.int64)
W = np.array([1/3] + [1/18]*6 + [1/36]*12)
OPP = np.array([0,2,1,4,3,6,5,8,7,10,9,12,11,14,13,16,15,18,17], dtype=np.int64)


def _flip(axis):
    out = np.zeros(19, np.int64)
    for i in range(19):
        c = C[i].copy(); c[axis] = -c[axis]
        out[i] = [j for j in range(19) if (C[j] == c).all()][0]
    return out


FY, FZ = _flip(1), _flip(2)


@njit(inline="always")
def _feq(i, rho, ux, uy, uz, C, W):
    cu = 3.0 * (C[i, 0] * ux + C[i, 1] * uy + C[i, 2] * uz)
    return W[i] * rho * (1.0 + cu + 0.5 * cu * cu - 1.5 * (ux * ux + uy * uy + uz * uz))


@njit(parallel=True, fastmath=True, cache=True)
def step(fo, fn, solid, label, uw, uf, U, tau0, cs2, C, W, OPP, FY, FZ, forces):
    nx, ny, nz = solid.shape
    nthreads_force = forces.shape[0]
    for t in range(nthreads_force):
        for k in range(forces.shape[1]):
            forces[t, k] = 0.0
    for x in prange(nx):
        fin = np.empty(19)
        feq = np.empty(19)
        acc = np.zeros(forces.shape[1])
        for y in range(ny):
            for z in range(nz):
                if solid[x, y, z]:
                    continue
                r0 = 0.0
                for i in range(19):
                    r0 += fo[i, x, y, z]
                for i in range(19):
                    sx = x - C[i, 0]; sy = y - C[i, 1]; sz = z - C[i, 2]
                    if sz < 0:                                  # rolling road
                        j = OPP[i]
                        fin[i] = fo[j, x, y, z] + 6.0 * r0 * W[i] * C[i, 0] * uf[x, y]
                        continue
                    ii = i
                    if sy < 0 or sy >= ny:                      # symmetry / free slip
                        ii = FY[ii]; sy = y
                    if sz >= nz:
                        ii = FZ[ii]; sz = z
                    if sx < 0:
                        fin[i] = _feq(i, 1.0, U, 0.0, 0.0, C, W)
                        continue
                    if sx >= nx:
                        sx = nx - 1
                    if solid[sx, sy, sz]:                       # bounce-back off a (moving) solid
                        j = OPP[i]
                        cu = C[i, 0] * uw[sx, sy, sz, 0] + C[i, 1] * uw[sx, sy, sz, 1] + C[i, 2] * uw[sx, sy, sz, 2]
                        fin[i] = fo[j, x, y, z] + 6.0 * r0 * W[i] * cu
                        s = fo[j, x, y, z] + fin[i]
                        b = 3 * label[sx, sy, sz]
                        acc[b + 0] -= C[i, 0] * s
                        acc[b + 1] -= C[i, 1] * s
                        acc[b + 2] -= C[i, 2] * s
                        continue
                    fin[i] = fo[ii, sx, sy, sz]
                rho = 0.0; ux = 0.0; uy = 0.0; uz = 0.0
                for i in range(19):
                    rho += fin[i]; ux += fin[i] * C[i, 0]; uy += fin[i] * C[i, 1]; uz += fin[i] * C[i, 2]
                ux /= rho; uy /= rho; uz /= rho
                # Smagorinsky: local relaxation time from the non-equilibrium stress
                pxx = 0.0; pyy = 0.0; pzz = 0.0; pxy = 0.0; pxz = 0.0; pyz = 0.0
                for i in range(19):
                    feq[i] = _feq(i, rho, ux, uy, uz, C, W)
                    d = fin[i] - feq[i]
                    pxx += C[i, 0] * C[i, 0] * d; pyy += C[i, 1] * C[i, 1] * d; pzz += C[i, 2] * C[i, 2] * d
                    pxy += C[i, 0] * C[i, 1] * d; pxz += C[i, 0] * C[i, 2] * d; pyz += C[i, 1] * C[i, 2] * d
                q = np.sqrt(pxx * pxx + pyy * pyy + pzz * pzz + 2 * (pxy * pxy + pxz * pxz + pyz * pyz))
                tau = 0.5 * (tau0 + np.sqrt(tau0 * tau0 + 18.0 * 1.41421356 * cs2 * q / rho))
                om = 1.0 / tau
                # regularized BGK: keep only the second-order (stress) part of f - feq
                for i in range(19):
                    cx = C[i, 0]; cy = C[i, 1]; cz = C[i, 2]
                    qq = ((cx * cx - 1.0 / 3.0) * pxx + (cy * cy - 1.0 / 3.0) * pyy + (cz * cz - 1.0 / 3.0) * pzz
                          + 2.0 * (cx * cy * pxy + cx * cz * pxz + cy * cz * pyz))
                    fn[i, x, y, z] = feq[i] + (1.0 - om) * 4.5 * W[i] * qq
        forces[x] = acc  # one row per x slab (summed by the caller)
    return


class Tunnel:
    def __init__(self, solid, label, uw, U=0.08, tau0=0.51, cs=0.12, uf=None):
        self.solid = np.ascontiguousarray(solid)
        self.label = np.ascontiguousarray(label.astype(np.int64))
        self.uw = np.ascontiguousarray(uw.astype(np.float64))
        self.U, self.tau0, self.cs2 = U, tau0, cs * cs
        self.uf = np.full(solid.shape[:2], U) if uf is None else np.ascontiguousarray(uf, dtype=np.float64)
        nx, ny, nz = solid.shape
        self.nlab = int(self.label.max()) + 1
        self.forces = np.zeros((nx, 3 * self.nlab))
        self.f = np.zeros((19, nx, ny, nz), np.float32)
        for i in range(19):
            self.f[i] = _feq_np(i, U)
        self.g = self.f.copy()

    def run(self, steps, avg_from):
        acc = np.zeros(3 * self.nlab); n = 0; hist = []
        for t in range(steps):
            step(self.f, self.g, self.solid, self.label, self.uw, self.uf, self.U, self.tau0, self.cs2,
                 C, W, OPP, FY, FZ, self.forces)
            self.f, self.g = self.g, self.f
            if t >= avg_from:
                fs = self.forces.sum(0); acc += fs; n += 1
                if t % 50 == 0:
                    hist.append(fs.copy())
        return acc / max(n, 1), np.array(hist)


def _feq_np(i, U):
    cu = 3.0 * C[i, 0] * U
    return W[i] * (1.0 + cu + 0.5 * cu * cu - 1.5 * U * U)
