"""Race time of a car with a given sidepod, through Part 2's race model.

  drag, lift  tunnel values scaled to the real car: D = D_REF * D_lbm / D_lbm(original)
  mass        T3.6 floor + 0.2 g margin = 48.2 g, held by lead ballast in the halo
              container (T1.22); the foam of the design decides how much lead is needed
              (none needed -> car is heavier than 48.2 g; more than the container holds ->
              underweight -> illegal)
  COM         exact: original 1 mm body + the design's change + fixed parts + ballast

ASSUMPTIONS (the STEP has no parts list or masses): non-body parts weigh 48.2 g minus the
original body's foam (the trial car as drawn is the 48.2 g no-ballast car), with their COM
mid-wheelbase at z = 16 mm; foam 0.163 g/cm3; lead 11.34 g/cm3 in the 1.39 cm3 container
under the halo at x = 130, z = 21 mm; thrust line z = 30 mm, cartridge rear centre 13 mm
behind the tail (no bore in the STEP); guides 5 mm outside each axle, line at 6 mm.
D_REF = 0.39 N (the repo's medium-mesh carved car); the race model then divides by its own
CFD drag bias as usual.
"""
from __future__ import annotations
import sys
import numpy as np
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "part2-simulation"))
import race_objective as R                                      # noqa: E402
from pitch_balance import CarGeometry                          # noqa: E402
from region import load_1mm, X_FRONT_AXLE, X_REAR_AXLE, FOAM_G_CM3  # noqa: E402

D_REF = 0.39
TARGET_G = 48.2
LEAD_CAP_G = 1.39 * 11.34
BALLAST_XZ = (130.0, 21.0)
X_NOSE = 228.625
TAIL_X = -28.5
THRUST_Z = 30.0


def nose(x):
    return (X_NOSE - x) / 1e3


class Scorer:
    def __init__(self, car, d_lbm_base, l_lbm_base=0.0):
        self.car = car
        xs, ys, zs, body, _ = load_1mm()
        X, _Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
        v1 = body.sum() * 1e-3                                       # cm3
        self.body0_g = v1 * FOAM_G_CM3
        self.body0_xz = (X[body].mean(), Z[body].mean())
        self.cells0 = car.original.sum()
        self.other_g = TARGET_G - self.body0_g
        self.other_xz = (0.5 * (X_FRONT_AXLE + X_REAR_AXLE), 16.0)
        self.cell_g = 2 * 27e-3 * FOAM_G_CM3                         # one half-grid cell, both sides
        self.d0, self.l0 = d_lbm_base, l_lbm_base
        x_thrust = TAIL_X - 13.0
        geo = CarGeometry(x_front_axle_m=nose(X_FRONT_AXLE), wheelbase_m=(X_FRONT_AXLE - X_REAR_AXLE) / 1e3,
                          x_thrust_m=nose(x_thrust), z_thrust_m=THRUST_Z / 1e3,
                          x_guide_front_m=nose(X_FRONT_AXLE + 5), x_guide_rear_m=nose(X_REAR_AXLE - 5),
                          z_guide_m=0.006)
        sheet = HERE.parents[1] / "part2-simulation/co2_thrust_data.csv"
        self.model = R.build_smooth_sheet_model(sheet)._replace(
            geometry=geo, gas_xz_m=(nose(x_thrust) - 0.0325, THRUST_Z / 1e3))
        self._cache = {}
        import jax
        model = self.model
        # jit with the model as a closure constant: no re-trace per call (race_objective notes a
        # JIT-mapping leak that kills a process after ~20 un-jitted calls), 44x faster
        self._vg = jax.jit(lambda pv: jax.value_and_grad(R.race_time_seconds)(pv, model))

    def mass(self, body_half):
        """Body foam, ballast, total mass (g) and COM (STEP x, z mm) of the whole car."""
        c = self.car
        add = body_half & ~c.original
        rem = c.original & ~body_half
        dg_add, dg_rem = add.sum() * self.cell_g, rem.sum() * self.cell_g
        foam = self.body0_g + dg_add - dg_rem
        mx = self.body0_g * self.body0_xz[0] + dg_add * (c.X[add].mean() if add.any() else 0) - dg_rem * (c.X[rem].mean() if rem.any() else 0)
        mz = self.body0_g * self.body0_xz[1] + dg_add * (c.Z[add].mean() if add.any() else 0) - dg_rem * (c.Z[rem].mean() if rem.any() else 0)
        ballast = max(0.0, TARGET_G - self.other_g - foam)
        legal = ballast <= LEAD_CAP_G
        tot = foam + self.other_g + ballast
        mx += self.other_g * self.other_xz[0] + ballast * BALLAST_XZ[0]
        mz += self.other_g * self.other_xz[1] + ballast * BALLAST_XZ[1]
        return dict(foam_g=foam, ballast_g=ballast, total_g=tot, com_x=mx / tot, com_z=mz / tot, mass_legal=legal)

    def race(self, drag_lbm, lift_lbm, m):
        D = D_REF * drag_lbm / self.d0
        Lf = D_REF * (lift_lbm - self.l0) / self.d0      # change from the original only (the
        # tunnel lift carries a constant pressure offset on the wheel plinths)
        p = R.make_param_vector(drag_20_n=D, car_weight_g=m["total_g"], mu=0.010, wheel_moi_g_mm2=139.0,
                                com_height_mm=m["com_z"], lift_20_n=Lf, com_x_mm=(X_NOSE - m["com_x"]))
        import jax.numpy as jnp
        T, gv = self._vg(jnp.asarray(p, dtype=jnp.float64))
        g = {n: float(gv[i]) for i, n in enumerate(R.PARAM_NAMES)}
        return float(T), D, Lf, g
