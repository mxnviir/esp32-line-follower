"""Puts a half car (3 mm grid from region.Car) into the lattice-Boltzmann tunnel and measures
time-averaged drag and lift (lattice units, whole half car: body + wheels)."""
from __future__ import annotations
import numpy as np
import lbm3d as L
from scipy import ndimage
from region import Car, R_WHEEL, X_FRONT_AXLE, X_REAR_AXLE

UP, DOWN, NY, NZ = 20, 50, 36, 32
U = 0.08


class CarTunnel:
    def __init__(self, car: Car, tau0=0.52, cs=0.14):
        self.car = car
        nxc, nyc, nzc = car.body.shape
        self.nx = UP + nxc + DOWN
        self.shape = (self.nx, NY, NZ)
        self.tau0, self.cs = tau0, cs
        # wheels: solid + rotating surface velocity
        w = self._place(car.wheels)
        # contact plinth: wherever the wheel is within 3 cells (9 mm) of the road, fill the gap
        # (the wheel/road wedge is pumped by both moving walls and is unresolvable at 3 mm)
        anyw = w.any(2)
        zlow = np.where(anyw, np.argmax(w, axis=2), 99)
        for (i, j) in zip(*np.where(zlow <= 3)):
            w[i, j, :zlow[i, j]] = True
        self.wheels = w
        uw = np.zeros(self.shape + (3,))
        Xl = np.arange(self.nx)[:, None, None] * np.ones(self.shape)
        Zl = np.arange(NZ)[None, None, :] * np.ones(self.shape)
        Om = U / (R_WHEEL / 3.0)
        for xa in (X_FRONT_AXLE, X_REAR_AXLE):
            xc = self._lx(xa); zc = R_WHEEL / 3.0 - 0.5
            m = self.wheels & (np.abs(Xl - xc) <= R_WHEEL / 3.0 + 1)
            uw[m, 0] = -Om * (Zl[m] - zc)
            uw[m, 2] = Om * (Xl[m] - xc)
        self.uw = uw * 0.0                               # wheels held still (see below)
        # road: moves at U, except a still patch round each contact (8 cells either side): a
        # moving road running into a still wheel/plinth pumps mass at 3 mm and drifts
        uf = np.full(self.shape[:2], U)
        foot = w[:, :, :3].any(2)
        uf[ndimage.binary_dilation(foot, iterations=8)] = 0.0
        self.uf = uf
        self.base_state = None

    def _lx(self, x_step):
        """STEP x (mm) -> lattice X index (flow goes +X, i.e. nose first)."""
        i = (x_step - self.car.xs[0]) / 3.0
        return UP + (len(self.car.xs) - 1 - i)

    def _place(self, half):
        g = np.zeros(self.shape, bool)
        nxc, nyc, nzc = half.shape
        g[UP:UP + nxc, :nyc, :nzc] = half[::-1]
        return g

    def measure(self, body_half, steps, avg_from, warm=None):
        solid = seal(self._place(body_half) | self.wheels)
        label = np.zeros(self.shape, np.int64); label[self.wheels] = 1
        T = L.Tunnel(solid, label, self.uw, U=U, tau0=self.tau0, cs=self.cs, uf=self.uf)
        if warm is not None:
            T.f[:] = warm
            fresh = ~solid & self._was_solid(warm)
            for i in range(19):
                T.f[i][fresh] = L.W[i]                     # rest, rho = 1
            T.g[:] = T.f
        F, hist = T.run(steps, avg_from)
        return dict(drag=F[0] + F[3], lift=F[2] + F[5], drag_body=F[0], drag_wheels=F[3],
                    hist=hist, state=T.f)

    @staticmethod
    def _was_solid(state):
        return np.zeros(state.shape[1:], bool) if state is None else (np.abs(state.sum(0)) < 1e-9)


def seal(solid):
    """Fill fluid cells boxed in on 4+ of 6 faces (road counts as solid): one-cell slots
    between a moving wall and a solid are unresolvable at 3 mm and go unstable."""
    s = solid.copy()
    for _ in range(4):
        p = np.pad(s, 1, constant_values=False)
        p[:, :, 0] = True                                # the road
        p[:, 0, :] = False                               # symmetry plane: open
        n = (p[2:, 1:-1, 1:-1].astype(np.int8) + p[:-2, 1:-1, 1:-1] + p[1:-1, 2:, 1:-1]
             + p[1:-1, :-2, 1:-1] + p[1:-1, 1:-1, 2:] + p[1:-1, 1:-1, :-2])
        add = ~s & (n >= 4)
        if not add.any():
            break
        s |= add
    return s
