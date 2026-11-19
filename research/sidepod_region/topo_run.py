"""python topo_run.py <seed> <budget_run_equivalents>

Density-based topology optimisation of the sidepod with the differentiable tunnel. Each
iteration: race time and its gradient wrt every region cell (charged as 2 runs, an adjoint's
cost), a normalised descent step on the level field, smoothing. Every few iterations the
thresholded, finished design is scored in the same tunnel as every other method (1 run)."""
import sys, json, time, numpy as np
from pathlib import Path
import jax, jax.numpy as jnp
from scipy import ndimage
import topo_jax as TJ
import run_one
from tunnel import seal, U, UP as UPX
from score import Scorer, D_REF, TARGET_G, LEAD_CAP_G, BALLAST_XZ, X_NOSE
import race_objective as R

HERE = Path(__file__).resolve().parent
seed, budget = int(sys.argv[1]), int(sys.argv[2])
STEPS, AVG = run_one.STEPS, run_one.AVG_FROM
P = run_one.setup(HERE / f"results/runs/topo_s{seed}.jsonl", budget)
(HERE / f"results/runs/topo_s{seed}.jsonl").write_text("")
car, tun, sc = P.car, P.tunnel, P.scorer
rng = np.random.default_rng(seed)

fixed_lat = seal(tun._place(car.fixed | car.must) | tun.wheels)
reg_lat = tun._place(car.region & ~car.must) & ~fixed_lat
step = TJ.make_step(fixed_lat, tun.uf, U, tun.tau0, tun.cs ** 2)
f0 = jnp.asarray(np.load(HERE / "results/state_A.npy"))
reg_lat_j = jnp.asarray(reg_lat)

# geometry for exact mass/COM of a grey design (lattice frame -> STEP frame)
regmask = car.region & ~car.must
orig_in_reg = (car.original & regmask).astype(np.float32)
Xr, Zr = car.X.astype(np.float32), car.Z.astype(np.float32)
cell_g = sc.cell_g


def to_lat(a_half):
    g = jnp.zeros(fixed_lat.shape, a_half.dtype)
    nxc, nyc, nzc = a_half.shape
    return g.at[UPX:UPX + nxc, :nyc, :nzc].set(a_half[::-1])


def density(theta):
    th = jnp.asarray(theta)
    # smoothing filter (separable 1-2-1, twice): organic, no checkerboards
    k = jnp.array([0.25, 0.5, 0.25])
    for ax in range(3):
        for _ in range(2):
            th = (jnp.roll(th, 1, ax) * k[0] + th * k[1] + jnp.roll(th, -1, ax) * k[2])
    return jax.nn.sigmoid(1.5 * th) * regmask


def objective(theta, beta_p=2.0):
    rho = density(theta)                                   # half grid, STEP frame
    gam = (to_lat(rho) ** beta_p).astype(jnp.float32)
    gam = jnp.where(reg_lat_j, gam, 0.0)
    F, _ = TJ.run_forces(step, f0, gam, STEPS, AVG, seg=40)
    drag, lift = F[0], F[1]
    D = D_REF * drag / d0_jax; Lf = D_REF * (lift - l0_jax) / d0_jax
    dfoam = (rho - orig_in_reg) * cell_g
    foam = sc.body0_g + dfoam.sum()
    mx = sc.body0_g * sc.body0_xz[0] + (dfoam * Xr).sum()
    mz = sc.body0_g * sc.body0_xz[1] + (dfoam * Zr).sum()
    ballast = jnp.maximum(TARGET_G - sc.other_g - foam, 0.0)
    tot = foam + sc.other_g + ballast
    mx = mx + sc.other_g * sc.other_xz[0] + ballast * BALLAST_XZ[0]
    mz = mz + sc.other_g * sc.other_xz[1] + ballast * BALLAST_XZ[1]
    mx = mx / tot; mz = mz / tot
    over = jnp.maximum(TARGET_G - sc.other_g - foam - LEAD_CAP_G, 0.0)     # container full: barrier
    p = jnp.stack([D, tot / 1e3, 0.010, 1.39e-7, 1.0, mz / 1e3 * 1.0, Lf, (X_NOSE - mx) / 1e3])
    T = R.race_time_seconds(p.astype(jnp.float64), sc.model) + 0.05 * over
    return T.astype(jnp.float32), (D, Lf, foam, ballast)


# scale: the porous model's own drag of the starting design (smoothed original)
theta0 = (np.where(car.original, 4.0, -4.0).astype(np.float32) * regmask).astype(np.float32)
rho_s = density(theta0)
Fo, _ = jax.jit(lambda g: TJ.run_forces(step, f0, g, STEPS, AVG, seg=40))(
    jnp.where(reg_lat_j, to_lat(rho_s) ** 2.0, 0.0).astype(jnp.float32))
d0_jax, l0_jax = float(Fo[0]), float(Fo[1])
print("porous-model start drag", d0_jax, "lift", l0_jax, "(numba original", sc.d0, ")", flush=True)

vg = jax.jit(jax.value_and_grad(objective, has_aux=True))
theta = jnp.asarray(theta0 + rng.normal(0, 0.3, theta0.shape).astype(np.float32) * regmask)
hist = []
t0 = time.time(); it = 0; charged = 0
while charged + 2 <= budget:
    it += 1
    (T, aux), g = vg(theta)
    charged += 2
    g = np.asarray(g) * regmask
    gmax = np.abs(g).max() + 1e-12
    lr = 1.5 / (1 + 0.15 * it)
    theta = theta - lr * g / gmax * 1.0
    rec = dict(it=it, T_model=float(T), D=float(aux[0]), L=float(aux[1]), foam_g=float(aux[2]),
               ballast_g=float(aux[3]), charged=charged, wall_s=round(time.time() - t0, 1))
    if it % 3 == 0 or charged + 2 > budget:
        rho = np.asarray(density(theta))
        if charged + 1 <= budget:
            Ts, body = P.evaluate(np.where(rho > 0.5, 1.0, -1.0) * 1.0, "topo")
            P.used = charged = charged + 1 if Ts is not None else charged   # charge the scoring run
            rec["T_scored"] = Ts
            np.save(HERE / f"results/runs/topo_s{seed}_rho_it{it}.npy", rho)
    hist.append(rec); print(json.dumps(rec), flush=True)
np.save(HERE / f"results/runs/topo_s{seed}_best.npy", P.best[1])
(HERE / f"results/runs/topo_s{seed}_iters.json").write_text(json.dumps(hist, indent=1))
print("topo best scored T", P.best[0], flush=True)
