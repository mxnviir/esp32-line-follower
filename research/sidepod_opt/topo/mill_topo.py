"""Millable topology optimisation of the sidepods: DRAG ONLY (test mode), built out from the body.

Design variable: h(x, z), how far the pod extends sideways (|y|) out from the body, on a 1 mm grid
of the region's side view (half car; the other side is its mirror). Material in a column fills
|y| in [inner(x,z), inner(x,z) + h(x,z)], where inner is the lean body's outer side at that column.
So every design is attached to the body, has no undercut seen from the side (the left/right mill
setups reach all of it), and any outline/steps/cut-outs in side view are possible.
Start: h = 0 (no sidepod). It BUILDS: each step moves the sharp outline out or in.

Per cycle: h -> porosity beta on the CFD cells (sharp edge, eps ~ half a cell) -> ESI
adjointOptimisationFoam, one cycle (warm primal + adjoint, topologySens written) -> dJ/dbeta per
cell (adjoint part + the objective's direct porous term) -> chain rule to dJ/dh per column ->
smoothed steepest-descent step on h.
Objective: total dissipated power (the drag proxy checked against body-fitted CFD: the team's
sidepod was worth -24.5 mN both ways). Nothing else: no lift, no mass, no race model.

    python topo/mill_topo.py init  <case>  [--base topo/car_coarse]
    python topo/mill_topo.py fdcheck <case>          # finite-difference check of dJ/dh
    python topo/mill_topo.py run   <case> --cycles 60
    python topo/mill_topo.py extract <case> [--cycle N]  # milled car + body-fitted drag
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from scipy import ndimage

HERE = Path(__file__).resolve().parent
SP = HERE.parent
sys.path.insert(0, str(SP)); sys.path.insert(0, str(HERE))
BASHRC = "/usr/lib/openfoam/openfoam2412/etc/bashrc"
BETA_MAX = 1.0e5
EPS_M = 0.0007                 # outline sharpness: half a design cell
NP = 4
FIELDS = ("U", "p", "k", "omega", "nut", "phi", "Ua", "pa", "ka", "wa", "phia")


def sh(cmd, cwd, log=None):
    out = subprocess.run(["bash", "-c", f"source {BASHRC} >/dev/null 2>&1; export OMPI_ALLOW_RUN_AS_ROOT=1 "
                          f"OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 OMPI_MCA_rmaps_base_oversubscribe=1; {cmd}"],
                         cwd=cwd, capture_output=True, text=True)
    if log:
        (Path(cwd) / log).write_text(out.stdout + out.stderr)
    if out.returncode:
        raise RuntimeError(f"{cmd} failed ({out.returncode}): {(out.stdout + out.stderr)[-800:]}")
    return out.stdout


def sfield(p):
    t = Path(p).read_text()
    m = re.search(r"internalField\s+nonuniform\s+List<scalar>\s*(\d+)\s*\(", t)
    if m:
        return np.array(t[m.end():].split(")", 1)[0].split()[: int(m.group(1))], float)
    return None


def vfield(p):
    t = Path(p).read_text()
    m = re.search(r"internalField\s+nonuniform\s+List<vector>\s*(\d+)\s*\(", t)
    n = int(m.group(1))
    return np.array([list(map(float, s.split())) for s in re.findall(r"\(([^()]+)\)", t[m.end():])[:n]])


# ---------------------------------------------------------------- geometry of the design
Z_CEIL_MM = 27.0               # the team's sidepod top face (flat, STEP): nothing may be above it
T_MIN_MM = 3.0                 # minimum foam thickness (team rule)


class Columns:
    """Plan-view (x, |y|) columns of the sidepod region on the car's 1 mm grid. Each column holds one
    solid interval [zb, zt] (bottom surface milled from below, top surface from above), or nothing.
    Linked to the CFD design cells (porosity) and to the milling pipeline (voxels)."""

    def __init__(self, case):
        import geometry as G
        from geometry import Car
        G.MC.DIRECTIONS = (("z", 2, True), ("z", 2, False))           # top and bottom set-ups only
        self.car = car = Car(h=1.0)
        s = car.s
        self.lean = car.finish(np.full(car.body0.shape, -1.0))         # keep | cargo: no sidepod
        reg = car.region & (car.zs[None, None, :] <= Z_CEIL_MM - 0.5 * car.h)
        # the pods must COVER the virtual cargo: a 3 mm foam wall around its sides, front and back (in plan),
        # wherever that is sidepod region under the ceiling; its top is the ceiling itself
        k = int(round(T_MIN_MM / car.h))
        disk = (np.arange(-k, k + 1)[:, None] ** 2 + np.arange(-k, k + 1)[None, :] ** 2) <= k * k
        cover = ndimage.binary_dilation(car.cargo, structure=disk[:, :, None]) & reg
        self.cargo_cover_mm3 = float((cover & ~self.lean).sum() * car.h ** 3)
        self.lean = self.lean | cover
        self.reg = reg
        self.ypos = np.nonzero(car.ys >= 0)[0]                          # the +y half of the grid
        R = reg[:, self.ypos, :]
        Zc = car.zs
        anyz = R.any(2)
        self.active = anyz
        self.zlo = np.where(anyz, Zc[np.argmax(R, 2)] - 0.5 * car.h, 0.0)
        self.zhi = np.where(anyz, Zc[R.shape[2] - 1 - np.argmax(R[:, :, ::-1], 2)] + 0.5 * car.h, 0.0)
        case = Path(case)
        C = vfield(case / "0" / "C")
        design = np.array((case / "constant/polyMesh/sets/designSpace").read_text().split("(", 1)[1].split(")")[0].split(), int)
        self.ncells, self.design = len(C), design
        X = s.x_nose_mm - C[design, 0] * 1e3
        AY = np.abs(C[design, 1]) * 1e3
        self.zc = C[design, 2] * 1e3
        ysp = car.ys[self.ypos]
        self.ix = np.clip(np.round((X - car.xs[0]) / car.h).astype(int), 0, reg.shape[0] - 1)
        self.iy = np.clip(np.round((AY - ysp[0]) / car.h).astype(int), 0, len(ysp) - 1)
        iz = np.clip(np.round((self.zc - Zc[0]) / car.h).astype(int), 0, reg.shape[2] - 1)
        self.cell_ok = R[self.ix, self.iy, iz]                          # in the region and under the ceiling

    # porosity of the CFD cells for surfaces (zb, zt) in mm: a sharp-edged interval per column
    def _ab(self, zb, zt):
        e = EPS_M * 1e3
        return (zt[self.ix, self.iy] - self.zc) / e, (self.zc - zb[self.ix, self.iy]) / e

    def beta(self, zb, zt):
        a, b = self._ab(zb, zt)
        bb = 0.25 * (1 + np.tanh(a)) * (1 + np.tanh(b)) * self.cell_ok
        full = np.zeros(self.ncells); full[self.design] = bb
        return full

    def grad(self, zb, zt, dJdbeta):
        e = EPS_M * 1e3
        a, b = self._ab(zb, zt)
        sa, sb = 0.5 * (1 + np.tanh(a)), 0.5 * (1 + np.tanh(b))
        da, db = 0.5 * (1 - np.tanh(a) ** 2) / e, 0.5 * (1 - np.tanh(b) ** 2) / e
        w = dJdbeta[self.design] * self.cell_ok
        gt = np.zeros_like(zt); gb = np.zeros_like(zb)
        np.add.at(gt, (self.ix, self.iy), w * da * sb)                  # dJ/dzt
        np.add.at(gb, (self.ix, self.iy), -w * sa * db)                 # dJ/dzb
        return gb, gt

    def voxels(self, zb, zt):
        """Pod voxels (whole car, mirrored) for surfaces (zb, zt)."""
        car = self.car
        Z = car.zs[None, None, :]
        half = (Z > zb[:, :, None]) & (Z < zt[:, :, None]) & self.reg[:, self.ypos, :]   # voxel centres strictly inside
        pod = np.zeros(car.body0.shape, bool)
        pod[:, self.ypos, :] = half
        pod |= pod[:, ::-1, :]                                          # symmetric car
        return pod & self.reg

    def project(self, zb, zt):
        """The manufacturable design nearest to (zb, zt): ceiling and region; thickness 0 or >= 3 mm;
        attached to the body (loose pieces deleted); milled from top and bottom with the 3.175 mm
        ball (unreachable air becomes foam); 3 mm minimum wall. Returns (zb, zt, B, report)."""
        car = self.car
        zb = np.clip(zb, self.zlo, self.zhi); zt = np.clip(zt, self.zlo, self.zhi)
        t = zt - zb
        thin = t < 0.5 * T_MIN_MM
        mid = 0.5 * (zt + zb)
        grow = (~thin) & (t < T_MIN_MM)
        zb = np.where(grow, mid - 0.5 * T_MIN_MM, zb); zt = np.where(grow, mid + 0.5 * T_MIN_MM, zt)
        zb = np.clip(zb, self.zlo, self.zhi); zt = np.clip(zt, self.zlo, self.zhi)
        zt = np.where(thin, zb, zt)
        pod = self.voxels(zb, zt)
        B = self.lean | pod
        lab, _ = ndimage.label(B)
        keep = np.unique(lab[self.lean]); keep = keep[keep > 0]
        loose = B & ~np.isin(lab, keep)
        B = B & ~loose
        B, rep = car.mill(B)
        B, rep["min_wall_passes"] = car.min_wall(B, rep)
        above = B & ~self.lean & (car.zs[None, None, :] > Z_CEIL_MM)    # the ceiling beats the mill fill
        rep["mill_fill_above_ceiling_removed_mm3"] = float(above.sum() * car.h ** 3)
        B = B & ~above
        lab, _ = ndimage.label(B)                                       # and nothing loose after that
        keep = np.unique(lab[self.lean]); keep = keep[keep > 0]
        loose2 = B & ~np.isin(lab, keep); B = B & ~loose2
        rep["loose_deleted_mm3"] = float((loose.sum() + loose2.sum()) * car.h ** 3)
        rep["above_ceiling_mm3"] = float((B & ~self.lean & (car.zs[None, None, :] > Z_CEIL_MM)).sum() * car.h ** 3)
        # back to column surfaces: the extent of the pod in each column
        P = (B & self.reg)[:, self.ypos, :]
        has = P.any(2)
        Zc = car.zs
        nzb = np.where(has, Zc[np.argmax(P, 2)] - 0.5 * car.h, zb)
        nzt = np.where(has, Zc[P.shape[2] - 1 - np.argmax(P[:, :, ::-1], 2)] + 0.5 * car.h, nzb)
        nzt = np.where(has, nzt, nzb)
        return nzb, nzt, B, rep


# ---------------------------------------------------------------- case set-up
def write_alpha(case, beta, patches):
    bf = "\n".join(f"    {n} {{ type {'symmetryPlane' if t == 'symmetryPlane' else 'zeroGradient'}; }}" for n, t in patches)
    (Path(case) / "0" / "alpha").write_text(
        "FoamFile { version 2.0; format ascii; class volScalarField; object alpha; }\n"
        f"dimensions [0 0 0 0 0 0 0];\ninternalField nonuniform List<scalar> {len(beta)}\n(\n"
        + "\n".join(f"{v:.6g}" for v in beta) + "\n);\nboundaryField\n{\n" + bf + "\n}\n")


def patches_of(case):
    t = (Path(case) / "constant/polyMesh/boundary").read_text()
    return re.findall(r"\n\s+(\w+)\s*\{\s*type\s+(\w+);", t)


def set_iters(case, primal, adjoint):
    od = (Path(case) / "system/optimisationDict").read_text()
    od = re.sub(r"nIters \d+;", "nIters @;", od)
    od = od.replace("nIters @;", f"nIters {primal};", 1).replace("nIters @;", f"nIters {adjoint};", 1)
    od = re.sub(r"nInitialIters \d+;", "nInitialIters @;", od)
    od = od.replace("nInitialIters @;", f"nInitialIters {primal};", 1).replace("nInitialIters @;", f"nInitialIters {adjoint};", 1)
    (Path(case) / "system/optimisationDict").write_text(od)


def cmd_init(a):
    base, case = Path(a.base), Path(a.case)
    if case.exists():
        shutil.rmtree(case)
    shutil.copytree(base, case, ignore=shutil.ignore_patterns("processor*", "log.*", "optimisation", "[1-9]*",
                                                              "car_t*", "extract_*", "logs"))
    if not (case / "0" / "C").exists():
        sh("postProcess -func writeCellCentres -time 0", case)
    from make_topo_case import write_cellset
    design = np.array((case / "constant/polyMesh/sets/designSpace").read_text().split("(", 1)[1].split(")")[0].split(), int)
    n = len(vfield(case / "0" / "C"))
    isd = np.zeros(n, bool); isd[design] = True
    write_cellset(case / "constant/polyMesh/sets/outside", np.nonzero(~isd)[0])
    sh("setsToZones -noFlipMap", case)
    od = (case / "system/optimisationDict").read_text()
    # drag only: dissipation, nothing else; no volume constraint
    od = re.sub(r"\n\s*solidVol\s*\{.*?\n            \}\n", "\n", od, count=1, flags=re.S)
    od = re.sub(r"optimisation\s*\{\s*designVariables.*$",
                "optimisation\n{\n    designVariables\n    {\n        type               topO;\n        sensitivityType    topO;\n"
                "        writeFieldSens     true;\n        adjointPorousZones   (designSpace);\n        fixedZeroPorousZones (outside);\n"
                "        regularisation\n        {\n            regularise     false;\n            growFromWalls  false;\n        }\n"
                f"        betaMax            {BETA_MAX};\n        maxInitChange      1e-6;\n    }}\n"
                "    updateMethod\n    {\n        method steepestDescent;\n    }\n}\n", od, flags=re.S)
    assert "solidVol" not in od and "writeFieldSens" in od and "powerDissipation" in od, "optimisationDict layout"
    (case / "system/optimisationDict").write_text(od)
    cd = (case / "system/controlDict").read_text()
    cd = re.sub(r"endTime\s+\d+;", "endTime         1;", cd)
    cd = re.sub(r"writeInterval\s+\d+;", "writeInterval   1;", cd)
    (case / "system/controlDict").write_text(cd)
    cols = Columns(case)
    if a.start_from:                                   # surfaces of another run (same 1 mm column grid)
        d = np.load(a.start_from); zb, zt = d["zb"], d["zt"]
    else:                                              # no sidepod: empty intervals at mid height
        zb = zt = 0.5 * (cols.zlo + cols.zhi)
    zb, zt, B, rep = cols.project(zb, zt)
    np.savez(case / "h_0000.npz", zb=zb, zt=zt)
    (case / "mill_log.jsonl").write_text("")
    print(json.dumps({"columns_active": int(cols.active.sum()), "design_cells": int(len(cols.design)),
                      "design_cells_under_ceiling": int(cols.cell_ok.sum()),
                      "pod_cm3_start": float(((B & cols.reg).sum()) * 1e-3), "project": rep}, default=float))


def one_cycle(case, cols, zb, zt, primal, adjoint, warm):
    case = Path(case)
    write_alpha(case, cols.beta(zb, zt), patches_of(case))
    set_iters(case, primal, adjoint)
    for d in list(case.glob("processor*")) + [d for d in case.glob("[1-9]*") if d.is_dir()]:
        shutil.rmtree(d)
    sh("decomposePar -force", case, "log.decomposePar")
    t0 = time.time()
    sh(f"mpirun -np {NP} adjointOptimisationFoam -parallel", case, "log.adjointOptimisationFoam")
    sh("reconstructPar -time 1", case, "log.reconstructPar")
    J = float((case / "optimisation/objective/0/dissipationadjS1").read_text().strip().splitlines()[-1].split()[1])
    sens = sfield(case / "1" / "topologySensadjS1")
    U = vfield(case / "1" / "U")
    if not (case / "0" / "V").exists():
        sh("postProcess -func writeCellVolumes -time 0", case)
    V = sfield(case / "0" / "V")
    # topologySens is a per-unit-volume density and already includes the objective's own porous
    # term (betaMax |U|^2, via topOSensMultiplier -> dJdb): per-cell derivative = sens * V.
    # (Before 2026-11-20 this used sens without V and added the direct term again: ~1e8 too large.)
    direct = BETA_MAX * (U ** 2).sum(1) * V                          # for the record only
    dJdb = sens * V
    if warm:                                                         # next cycle starts from this flow
        for f in FIELDS:
            if (case / "1" / f).exists():
                shutil.copy(case / "1" / f, case / "0" / f)
    shutil.rmtree(case / "optimisation", ignore_errors=True)
    return J, dJdb, sens, direct, time.time() - t0


def cmd_fdcheck(a):
    """Finite-difference check of dJ/d(surfaces): J at a reference design and with one surface moved
    on a patch of columns, against sum(dJ/dz * dz). No projection (raw surfaces) so dz is exact."""
    case = Path(a.case)
    cols = Columns(case)
    zb = cols.zlo.copy(); zt = np.minimum(cols.zlo + 12.0, cols.zhi)       # a 12 mm slab on the floor of the region
    zt = np.where(cols.active, zt, zb)
    J0, dJdb, sens, direct, s0 = one_cycle(case, cols, zb, zt, 1500, 1000, warm=True)
    gb, gt = cols.grad(zb, zt, dJdb)
    gba, gta = cols.grad(zb, zt, sens)
    out = {"J0": J0, "secs": s0, "direct_share": float(np.abs(direct).sum() / (np.abs(sens).sum() + np.abs(direct).sum()))}
    X = cols.car.xs; Y = cols.car.ys[cols.ypos]
    for name, (x0, x1, y0, y1) in {"front": (125, 150, 18, 32), "rear": (65, 90, 18, 32)}.items():
        m = cols.active & (X[:, None] >= x0) & (X[:, None] <= x1) & (Y[None, :] >= y0) & (Y[None, :] <= y1)
        for dz in (3.0, -3.0):
            zt1 = np.clip(zt + dz * m, zb, cols.zhi)
            J1, *_ = one_cycle(case, cols, zb, zt1, 800, 1, warm=False)
            out[f"{name}_top{dz:+.0f}mm"] = {"dJ_measured": J1 - J0, "dJ_predicted": float((gt * (zt1 - zt)).sum()),
                                             "dJ_pred_adjoint_only": float((gta * (zt1 - zt)).sum()), "columns": int(m.sum())}
            print(name, dz, out[f"{name}_top{dz:+.0f}mm"], flush=True)
    (case / "fdcheck.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


def cmd_run(a):
    case = Path(a.case)
    cols = Columns(case)
    hs = sorted(case.glob("h_*.npz"))
    d = np.load(hs[-1]); zb, zt = d["zb"], d["zt"]; c0 = int(hs[-1].stem[2:])
    step = a.step_mm
    t_end = time.time() + a.hours * 3600 if a.hours else None
    for c in range(c0 + 1, c0 + a.cycles + 1):
        if t_end and time.time() > t_end:
            print("time budget reached", flush=True); break
        first = (c == c0 + 1)
        J, dJdb, sens, direct, secs = one_cycle(case, cols, zb, zt, a.first_iters if first else a.iters,
                                                a.first_iters if first else a.iters, warm=True)
        gb, gt = cols.grad(zb, zt, dJdb)
        gb = ndimage.gaussian_filter(gb, a.smooth_mm) * cols.active
        gt = ndimage.gaussian_filter(gt, a.smooth_mm) * cols.active
        gmax = max(np.abs(gb).max(), np.abs(gt).max())
        if gmax > 0:
            zb = zb - step * gb / gmax; zt = zt - step * gt / gmax
        zb, zt, B, rep = cols.project(zb, zt)
        np.savez(case / f"h_{c:04d}.npz", zb=zb, zt=zt)
        rec = {"cycle": c, "J": J, "secs": round(secs, 1), "step_mm": round(step, 3),
               "pod_cm3_both_sides": float((B & cols.reg).sum() * 1e-3), "cols_with_pod": int(((zt - zb) > 0.5).sum()),
               "loose_deleted_mm3": rep["loose_deleted_mm3"], "uncut_filled_mm3": rep["uncut_foam_mm3"],
               "above_ceiling_mm3": rep["above_ceiling_mm3"]}
        with open(case / "mill_log.jsonl", "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(json.dumps(rec), flush=True)
        step = max(a.step_min_mm, step * a.step_decay)


def cmd_extract(a):
    """The milled car of cycle N and its body-fitted drag."""
    case = Path(a.case)
    cols = Columns(case)
    hs = sorted(case.glob("h_*.npz"))
    hp = case / f"h_{a.cycle:04d}.npz" if a.cycle is not None else hs[-1]
    d = np.load(hp)
    zb, zt, B, prep = cols.project(d["zb"], d["zt"])
    car = cols.car
    chk = car.check(B)
    rep = {"h_file": hp.name, "pod_cm3_both_sides": float((B & cols.reg).sum() * 1e-3), "project": prep, "check": chk,
           "max_pod_z_mm": float(car.zs[np.nonzero((B & cols.reg).any(axis=(0, 1)))[0].max()] + 0.5 * car.h) if (B & cols.reg).any() else None}
    if chk["ok"]:
        out = case / f"car_{hp.stem}"
        car.export_car_folder(car.body_mesh_for(B), out, f"mill_{hp.stem}")
        if a.cfd:
            import gate
            half, health, secs = gate.solve(out, NP, 2000, extra={"resolution": a.res})
            rep["cfd"] = {"D20_half_N": float(half.D20), "D20_N": float(half.to_full_car().D20),
                          "converged": bool(health.converged), "wall_s": secs}
    (case / f"extract_{hp.stem}.json").write_text(json.dumps(rep, indent=1, default=float))
    print(json.dumps(rep, default=float)[:1500])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd"); ap.add_argument("case")
    ap.add_argument("--base", default=str(HERE / "car_coarse"))
    ap.add_argument("--cycles", type=int, default=60)
    ap.add_argument("--iters", type=int, default=300)
    ap.add_argument("--step_mm", type=float, default=1.5)
    ap.add_argument("--step_decay", type=float, default=0.97)
    ap.add_argument("--step_min_mm", type=float, default=0.3)
    ap.add_argument("--smooth_mm", type=float, default=2.0)
    ap.add_argument("--cycle", type=int, default=None)
    ap.add_argument("--cfd", action="store_true")
    ap.add_argument("--res", default="coarse")
    ap.add_argument("--start_from", default=None)
    ap.add_argument("--first_iters", type=int, default=1500)
    ap.add_argument("--hours", type=float, default=None)
    a = ap.parse_args()
    {"init": cmd_init, "fdcheck": cmd_fdcheck, "run": cmd_run, "extract": cmd_extract}[a.cmd](a)


if __name__ == "__main__":
    main()
