"""A small 2-D lattice-Boltzmann wind tunnel with a moving ground, for testing search methods.

Not the car's physics (2-D, Re ~ 500, laminar). It is real fluid dynamics, cheap enough to run
thousands of shapes, so it can answer one question: does a search method find good shapes in
a CFD-sized budget, and what do those shapes look like?

Set-up (lattice units): flow left to right at U0; the floor moves at U0 (a rolling road, as in
Part 2); top is free slip; outlet copies the last column. Solids use half-way bounce-back.
Drag = time-averaged momentum exchange on every solid link, over the second half of the run.
"""
from __future__ import annotations

import numpy as np
from numba import njit

NX, NY = 260, 70
U0 = 0.08
NU = 0.03                    # Re on a 110-cell body ~ 290
TAU = 3 * NU + 0.5
STEPS = 7000
AVG_FROM = 3500

CX = np.array([0, 1, 0, -1, 0, 1, -1, -1, 1])
CY = np.array([0, 0, 1, 0, -1, 1, 1, -1, -1])
W = np.array([4 / 9, 1 / 9, 1 / 9, 1 / 9, 1 / 9, 1 / 36, 1 / 36, 1 / 36, 1 / 36])
OPP = np.array([0, 3, 4, 1, 2, 7, 8, 5, 6])


@njit(cache=True)
def _feq(rho, ux, uy, f):
    for i in range(9):
        cu = 3.0 * (CX_[i] * ux + CY_[i] * uy)
        f[i] = W_[i] * rho * (1.0 + cu + 0.5 * cu * cu - 1.5 * (ux * ux + uy * uy))


CX_, CY_, W_, OPP_ = CX.astype(np.float64), CY.astype(np.float64), W, OPP


@njit(cache=True)
def run(solid, steps, avg_from, u0, tau):
    nx, ny = solid.shape
    f = np.zeros((9, nx, ny))
    ftmp = np.zeros((9, nx, ny))
    feq = np.zeros(9)
    for x in range(nx):
        for y in range(ny):
            _feq(1.0, u0, 0.0, feq)
            for i in range(9):
                f[i, x, y] = feq[i]
    drag_sum = 0.0
    lift_sum = 0.0
    n_avg = 0
    om = 1.0 / tau
    for t in range(steps):
        # collide
        for x in range(nx):
            for y in range(ny):
                if solid[x, y]:
                    continue
                rho = 0.0
                ux = 0.0
                uy = 0.0
                for i in range(9):
                    rho += f[i, x, y]
                    ux += f[i, x, y] * CX_[i]
                    uy += f[i, x, y] * CY_[i]
                ux /= rho
                uy /= rho
                _feq(rho, ux, uy, feq)
                for i in range(9):
                    f[i, x, y] += om * (feq[i] - f[i, x, y])
        # stream with bounce-back on solids; measure the force
        fx = 0.0
        fy = 0.0
        for x in range(nx):
            for y in range(ny):
                if solid[x, y]:
                    continue
                for i in range(9):
                    xn = x + int(CX_[i])
                    yn = y + int(CY_[i])
                    if xn < 0 or xn >= nx:
                        continue                      # inlet / outlet set below
                    if yn >= ny:                      # free-slip top: mirror
                        j = 4 if i == 2 else (8 if i == 5 else (7 if i == 6 else i))
                        ftmp[j, x, y] = f[i, x, y]
                        continue
                    if yn < 0:                        # moving floor at u0: bounce back with wall momentum
                        j = OPP_[i]
                        ftmp[j, x, y] = f[i, x, y] - 6.0 * W_[i] * CX_[i] * u0
                        continue
                    if solid[xn, yn]:
                        j = OPP_[i]
                        ftmp[j, x, y] = f[i, x, y]
                        fx += 2.0 * f[i, x, y] * CX_[i]
                        fy += 2.0 * f[i, x, y] * CY_[i]
                        continue
                    ftmp[i, xn, yn] = f[i, x, y]
        # inlet: equilibrium at u0; outlet: copy
        for y in range(ny):
            _feq(1.0, u0, 0.0, feq)
            for i in range(9):
                ftmp[i, 0, y] = feq[i]
                ftmp[i, nx - 1, y] = ftmp[i, nx - 2, y]
        f, ftmp = ftmp, f
        if t >= avg_from:
            drag_sum += fx
            lift_sum += fy
            n_avg += 1
        if not np.isfinite(fx):
            return 1e9, 0.0
    return drag_sum / n_avg, lift_sum / n_avg


def drag(solid: np.ndarray, steps: int = STEPS, avg_from: int = AVG_FROM) -> tuple[float, float]:
    """Time-averaged drag and lift of every solid cell in `solid` (bool, NX x NY)."""
    return run(solid.astype(np.bool_), steps, avg_from, U0, TAU)
