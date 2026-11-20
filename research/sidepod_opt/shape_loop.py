"""Free-form sidepod search: level-set shape optimisation driven by the DAFoam adjoint, real walls.

Route A of ROUTES.md. Objective: half-car drag D20 (car + wheels), nothing else.

One iteration, design field f (mm, + = foam, the 1 mm grid of geometry.Car):
  1. f -> Car.build: finish (rules, cargo, symmetric) -> mill (3-axis) -> min wall -> check -> exact mesh
  2. export the car folder; coarse real-wall solve (fresh snappy mesh, warm-started from the last
     accepted iterate) with the steady scheme (CFD_DIV_U, default first-order upwind U: the
     production linearUpwind wake never settles and its adjoint stalls, ROUTES.md 2026-11-20)
  3. if drag went UP against the current design: reject, halve the step, retry from the current one
  4. else accept; DAFoam Krylov adjoint on that solve -> dD/dXs per surface point
  5. dD/dn per point (outward normal of the exported STL) -> 1 mm grid cells (and their mirrors),
     inside the region only -> Gaussian smoothing (the surface moves smoothly; a crude Sobolev step)
  6. f <- sdf(milled body) - step * g / max|g|   (sdf re-initialisation folds every rule into f)
The level set can merge and split pods (tunnels can close, or form where two parts meet); it does
not open a hole in solid on its own, so start from several seeds (`seeds()`).

    python shape_loop.py init  runs/A --seed original      # seeds: original lean blend block channel
    python shape_loop.py run   runs/A --iters 10 [--hours 6]
    python shape_loop.py show  runs/A                      # history table
Every iteration is saved (it_NNN/: field.npz, car folder, cfd.json, sens), log.jsonl is the history.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from scipy import ndimage

HERE = Path(__file__).resolve().parent
P2 = HERE.parents[1] / "part2-simulation"
sys.path.insert(0, str(P2)); sys.path.insert(0, str(HERE))

STEADY_DIV_U = "bounded Gauss upwind"
DOMAIN = None            # set from gate.DOMAIN at import time below (same domain as every gate run)


# ------------------------------------------------------------------ seeds
def seeds(car) -> dict:
    """Starting fields (mm, + = foam). The level set never opens holes in solid, so tunnel-like
    topologies get their own seed and the search decides whether they survive."""
    out = {"original": car.sdf_original.astype(float),
           "lean": car.sdf_lean.astype(float),
           "blend": 0.5 * (car.sdf_original + car.sdf_lean).astype(float)}
    # block: the whole region foam (the mill and rules cut it back to something buildable)
    reg_sdf = (ndimage.distance_transform_edt(car.region) - ndimage.distance_transform_edt(~car.region)) * car.h
    out["block"] = np.maximum(car.sdf_original, reg_sdf).astype(float)
    # channel: the team's pod with a lengthwise groove, low and open outboard. An ENCLOSED tunnel
    # cannot be made: the 3-axis mill (top, bottom, left, right set-ups) cannot reach a hole running
    # along x, and fills it (tested 2026-11-20: a 5 mm bore came back 98.5 % solid). Open grooves can.
    s = car.s
    Ycen = 0.8 * s.region_ymax
    Zcen = s.region_z[0] + 0.35 * (min(s.region_z[1], s.ceiling_mm or 1e9) - s.region_z[0])
    r = 4.0                                   # 8 mm groove: the 6.35 mm ball must fit
    d_axis = np.sqrt((np.abs(car.Y) - Ycen) ** 2 + (car.Z - Zcen) ** 2)
    d_slot = np.where(np.abs(car.Y) >= Ycen, np.abs(car.Z - Zcen), d_axis)    # the bore, opened to the side
    out["channel"] = np.minimum(car.sdf_original, d_slot - r).astype(float)
    return out


# ------------------------------------------------------------------ CFD pieces
def solve(folder: Path, iters: int, warm_from: str | None, n_sub: int) -> tuple[dict, str]:
    """Coarse real-wall half-car solve of a car folder, steady scheme; returns (record, kept run dir)."""
    import stopwatch as SW
    from cfd_wrapper import run_half_car_cfd
    from evaluators import _latest_run_dir
    os.environ.setdefault("CFD_DIV_U", STEADY_DIV_U)
    body = SW.body_stl(folder / "car_half.stl", folder / "_body_half.stl")
    kw = dict(SW.SEARCH, domain_reference_bounds=DOMAIN, resolution="coarse", max_iterations=int(iters))
    if warm_from:
        kw["warm_from"] = warm_from
    t = time.time()
    half, health = run_half_car_cfd(str(body), n_subdomains=n_sub, extra_surfaces=SW.extra_surfaces(folder),
                                    keep_run_dir=True, **kw)
    run = str(_latest_run_dir())
    return ({"D20_half_N": float(half.D20), "L20_half_N": float(half.L), "converged": bool(health.converged),
             "residual_p": health.residual_final, "force_osc": health.force_oscillation,
             "wall_s": round(time.time() - t, 1), "div_U": os.environ["CFD_DIV_U"]}, run)


def adjoint(run_dir: str, case: Path, n_proc: int, env: dict) -> dict:
    """DAFoam Krylov adjoint on a converged run: dD_half/dXs per surface point of patch `car`."""
    subprocess.run([sys.executable, str(HERE / "dafoam" / "make_case.py"), "--src", run_dir, "--out", str(case),
                    "--iters", "300"], check=True, stdout=subprocess.DEVNULL)
    e = dict(os.environ, DAF_ADJ="Krylov", DAF_PC_FILL="0", DAF_PC_LEVEL="1", DAF_GMRES_ITERS="2000",
             DAF_GMRES_RESTART="200", DAF_GMRES_TOL="1e-4", **env)
    t = time.time()
    with open(case.parent / "dafoam.out", "w") as f:
        subprocess.run(["bash", str(HERE / "dafoam" / "run_docker.sh"), str(case), str(n_proc)], env=e,
                       stdout=f, stderr=subprocess.STDOUT, check=False)
    sens = case / "dafoam_sens.npz"
    if not sens.exists():
        raise RuntimeError(f"DAFoam wrote no gradient; see {case.parent / 'dafoam.out'}")
    shutil.copy(sens, case.parent / "dafoam_sens.npz")
    S = np.load(sens)
    return {"Xs": S["Xs"], "dD_dXs": S["dD_dXs"], "D_half_dafoam_N": float(S["D_N"]), "adjoint_wall_s": round(time.time() - t, 1)}


# ------------------------------------------------------------------ gradient on the design grid
def grid_gradient(car, folder: Path, Xs: np.ndarray, dD_dXs: np.ndarray, sigma_mm: float) -> tuple[np.ndarray, dict]:
    """Half-car dD (N) per mm of outward surface move, summed per 1 mm cell, mirrored, region only,
    smoothed. Normals: nearest vertex normal of the exported half-car STL (the body DAFoam meshed)."""
    import trimesh
    from scipy.spatial import cKDTree
    m = trimesh.load(folder / "_body_half.stl", process=True)
    _, idx = cKDTree(m.vertices).query(Xs)
    n = m.vertex_normals[idx]
    dDdn = (dD_dXs * n).sum(1) * 1e-3                                  # N per mm of outward move
    s = car.s
    X, Y, Z = s.x_nose_mm - Xs[:, 0] * 1e3, Xs[:, 1] * 1e3, Xs[:, 2] * 1e3
    h = car.h
    i = np.clip(np.round((X - car.xs[0]) / h).astype(int), 0, len(car.xs) - 1)
    k = np.clip(np.round((Z - car.zs[0]) / h).astype(int), 0, len(car.zs) - 1)
    g = np.zeros(car.body0.shape)
    for yy in (Y, -Y):
        j = np.clip(np.round((yy - car.ys[0]) / h).astype(int), 0, len(car.ys) - 1)
        np.add.at(g, (i, j, k), dDdn)
    in_reg = car.region[i, np.clip(np.round((Y - car.ys[0]) / h).astype(int), 0, len(car.ys) - 1), k]
    raw = g * car.region
    gs = ndimage.gaussian_filter(raw, sigma_mm / h) * car.region if sigma_mm > 0 else raw
    info = {"points": int(len(Xs)), "points_in_region": int(in_reg.sum()),
            "dD_dn_region_sum_mN_per_mm": float(dDdn[in_reg].sum() * 1e3),
            "dD_dn_region_absmax_mN_per_mm": float(np.abs(dDdn[in_reg]).max() * 1e3) if in_reg.any() else 0.0}
    return gs, info


def sdf_of(car, B: np.ndarray) -> np.ndarray:
    return (ndimage.distance_transform_edt(B) - ndimage.distance_transform_edt(~B)) * car.h


# ------------------------------------------------------------------ driver
def load_car():
    from geometry import Car
    return Car(h=1.0)


def build_and_export(car, f, out: Path, label: str):
    b = car.build(f)
    if not b["check"]["ok"]:
        return b, None
    car.export_car_folder(b["mesh"], out / "car", label)
    return b, out / "car"


def cmd_init(a):
    run = Path(a.run)
    run.mkdir(parents=True, exist_ok=True)
    car = load_car()
    f = seeds(car)[a.seed]
    np.savez_compressed(run / "current.npz", f=f)
    cfg = {"seed": a.seed, "step_mm": a.step_mm, "step_min_mm": a.step_min_mm, "sigma_mm": a.sigma_mm,
           "iters_cold": a.iters_cold, "iters_warm": a.iters_warm, "np": a.np, "div_U": os.environ.get("CFD_DIV_U", STEADY_DIV_U)}
    (run / "config.json").write_text(json.dumps(cfg, indent=1))
    (run / "state.json").write_text(json.dumps({"it": 0, "step_mm": a.step_mm, "D_current": None, "run_current": None,
                                                "grad_ready": False}, indent=1))
    b = car.build(f)
    print(json.dumps({"seed": a.seed, "check": b["check"], "pod_cm3": float((b["voxels"] & car.region).sum() * car.h ** 3 * 1e-3),
                      "mass": b["mass"]}, default=float)[:1500])


def log(run: Path, rec: dict):
    with open(run / "log.jsonl", "a") as fh:
        fh.write(json.dumps(rec, default=float) + "\n")
    print(json.dumps(rec, default=float), flush=True)


def cmd_run(a):
    global DOMAIN
    import gate
    DOMAIN = gate.DOMAIN
    run = Path(a.run)
    cfg = json.loads((run / "config.json").read_text())
    os.environ.setdefault("CFD_DIV_U", cfg["div_U"])
    st = json.loads((run / "state.json").read_text())
    car = load_car()
    f_cur = np.load(run / "current.npz")["f"]
    t_end = time.time() + a.hours * 3600 if a.hours else None
    # an accepted design whose adjoint failed (crash, OOM): redo the adjoint before any step, so we
    # never step along a stale gradient (or a missing one). Old state files have no flag: trusted.
    if st["D_current"] is not None and not st.get("grad_ready", True):
        if not (st["run_current"] and Path(st["run_current"]).exists()):
            raise RuntimeError("accepted design has no gradient and its CFD run is gone; re-init this seed")
        d = run / "adjoint_retry"
        shutil.rmtree(d, ignore_errors=True); d.mkdir()
        A = adjoint(st["run_current"], d / "dafoam_case", cfg["np"], {})
        g, ginfo = grid_gradient(car, run / "best_car", A["Xs"], A["dD_dXs"], cfg["sigma_mm"])
        np.savez_compressed(run / "grad_current.npz", g=g)
        shutil.rmtree(d / "dafoam_case", ignore_errors=True)
        st["grad_ready"] = True
        (run / "state.json").write_text(json.dumps(st, indent=1, default=str))
        log(run, {"it": st["it"], "step_mm": st["step_mm"], "adjoint_retry": True,
                  **{k: v for k, v in A.items() if k not in ("Xs", "dD_dXs")}, **ginfo})
    done = 0
    while done < a.iters and (not t_end or time.time() < t_end):
        it = st["it"]
        d = run / f"it_{it:03d}"
        if d.exists():
            shutil.rmtree(d)
        d.mkdir()
        # ---- candidate: the current design itself (first time), or a step from it along the gradient
        if st["D_current"] is None:
            f_try = f_cur
        else:
            g = np.load(run / "grad_current.npz")["g"]
            gmax = np.abs(g).max()
            f_try = f_cur - st["step_mm"] * g / gmax if gmax > 0 else f_cur
        b, folder = build_and_export(car, f_try, d, f"{run.name}_it{it:03d}")
        np.savez_compressed(d / "field.npz", f=f_try)
        rec = {"it": it, "step_mm": st["step_mm"], "check_ok": b["check"]["ok"],
               "pod_cm3": float((b["voxels"] & car.region).sum() * car.h ** 3 * 1e-3),
               "mass_g": (b["mass"] or {}).get("race_mass_g")}
        if folder is None:                                          # illegal design: shorter step
            rec.update(accepted=False, why="check failed: " + json.dumps(b["check"], default=str)[:300])
            st["step_mm"] *= 0.5
        else:
            try:
                cfd, rdir = solve(folder, cfg["iters_warm"] if st["run_current"] else cfg["iters_cold"],
                                  st["run_current"], cfg["np"])
            except Exception as e:                                  # a failed solve is a rejected step
                cfd, rdir = {"error": repr(e)[:300]}, None
            (d / "cfd.json").write_text(json.dumps(cfd, indent=1, default=float))
            rec.update(cfd)
            D = cfd.get("D20_half_N")
            if D is None or (st["D_current"] is not None and D >= st["D_current"]):
                rec.update(accepted=False, why="drag not lower" if D is not None else "solve failed",
                           dD_mN=(D - st["D_current"]) * 1e3 if (D is not None and st["D_current"] is not None) else None)
                st["step_mm"] *= 0.5
                if rdir:
                    shutil.rmtree(rdir, ignore_errors=True)
            else:
                rec.update(accepted=True, dD_mN=(D - st["D_current"]) * 1e3 if st["D_current"] is not None else None)
                # re-initialise: the field is the signed distance of what will actually be milled
                f_cur = np.where(car.region, sdf_of(car, b["voxels"]), f_try)
                np.savez_compressed(run / "current.npz", f=f_cur)
                if st["run_current"] and Path(st["run_current"]).exists():
                    shutil.rmtree(st["run_current"], ignore_errors=True)
                st.update(D_current=D, run_current=rdir, best_it=it, grad_ready=False)
                shutil.copytree(folder, run / "best_car", dirs_exist_ok=True)
                try:
                    A = adjoint(rdir, d / "dafoam_case", cfg["np"], {})
                    g, ginfo = grid_gradient(car, folder, A["Xs"], A["dD_dXs"], cfg["sigma_mm"])
                    np.savez_compressed(run / "grad_current.npz", g=g)
                    st["grad_ready"] = True
                    rec.update({k: v for k, v in A.items() if k not in ("Xs", "dD_dXs")}, **ginfo)
                    shutil.rmtree(d / "dafoam_case", ignore_errors=True)
                except Exception as e:                              # next start redoes the adjoint
                    rec.update(adjoint_error=repr(e)[:300])
                    st["it"] = it + 1                               # keep it_NNN (its car is best_car)
                    log(run, rec); (run / "state.json").write_text(json.dumps(st, indent=1, default=str))
                    raise
        st["it"] = it + 1
        log(run, rec)
        (run / "state.json").write_text(json.dumps(st, indent=1, default=str))
        done += 1
        if st["step_mm"] < cfg["step_min_mm"]:
            print("step below minimum: converged (or stuck)", flush=True)
            break


def cmd_show(a):
    for line in (Path(a.run) / "log.jsonl").read_text().splitlines():
        r = json.loads(line)
        print(f"it {r['it']:3d}  step {r['step_mm']:.2f} mm  "
              f"D {1e3 * r['D20_half_N']:.2f} mN" if r.get("D20_half_N") else f"it {r['it']:3d}  (no drag)",
              f"dD {r.get('dD_mN')}", "ACCEPT" if r.get("accepted") else f"reject ({r.get('why')})",
              f"pod {r.get('pod_cm3', 0):.1f} cm3")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["init", "run", "show"]); ap.add_argument("run")
    ap.add_argument("--seed", default="original", choices=["original", "lean", "blend", "block", "channel"])
    ap.add_argument("--step_mm", type=float, default=1.5)
    ap.add_argument("--step_min_mm", type=float, default=0.2)
    ap.add_argument("--sigma_mm", type=float, default=2.0)
    ap.add_argument("--iters_cold", type=int, default=2500)
    ap.add_argument("--iters_warm", type=int, default=1200)
    ap.add_argument("--np", type=int, default=4)
    ap.add_argument("--iters", type=int, default=10)
    ap.add_argument("--hours", type=float, default=None)
    a = ap.parse_args()
    {"init": cmd_init, "run": cmd_run, "show": cmd_show}[a.cmd](a)


if __name__ == "__main__":
    main()
