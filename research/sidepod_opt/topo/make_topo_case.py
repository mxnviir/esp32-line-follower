"""Topology optimisation of the sidepods FROM SCRATCH (ESI adjointOptimisationFoam, OpenFOAM v2412).

The car is meshed with its sidepod region EMPTY: the team's body outside the region, the cargo and
the locked spine, but no sidepod material. Every fluid cell inside the region (the T7.9.2/T7.9.3 wheel
wedges and the halo zone are already outside it) is a design variable that may become porous solid
(Brinkman penalisation). It starts as pure fluid, so any solid that appears is geometry the optimiser
created: the test of "creative" geometry.

Objective: total dissipated power over the whole domain, including the porous solid's own Brinkman
dissipation. That is the drag-power proxy; the wall force alone would let a porous blob hide drag.
Constraint: solid fraction of the region <= SOLID_MAX. Regularisation grows solid from the walls, so
nothing floats. Turbulence k-omega SST, as in Part 2.

    python topo/make_topo_case.py [--res coarse] [--cycles 60] [--np 4] [--out topo/car_coarse]
then topo/run_topo.sh <case>
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SP = HERE.parent
sys.path.insert(0, str(SP)); sys.path.insert(0, str(SP.parents[1] / "part2-simulation"))
from geometry import Car  # noqa: E402

BASHRC = "/usr/lib/openfoam/openfoam2412/etc/bashrc"


def lean_car(out: Path):
    """The car with no sidepod: field negative everywhere -> keep | cargo, milled and exported."""
    car = Car()
    B, rep = car.mill(car.finish(np.full(car.body0.shape, -1.0)))
    B, _ = car.min_wall(B, rep)
    # only a CFD base: slivers where the kept CAD meets the empty region (about 45 mm3) fail the
    # thin-foam rule, which applies to built cars, not to this mesh
    car.export_car_folder(car.body_mesh_for(B), out, "lean")
    return car


def region_box_car_frame(car, pad_m=0.002):
    """The sidepod region's bounding box in the CFD frame (m: x from the nose, y >= 0, z up)."""
    s = car.s
    X = car.xs[np.nonzero(car.region.any(axis=(1, 2)))[0]]
    Y = car.ys[np.nonzero(car.region.any(axis=(0, 2)))[0]]
    Z = car.zs[np.nonzero(car.region.any(axis=(0, 1)))[0]]
    x0, x1 = (s.x_nose_mm - X.max()) * 1e-3, (s.x_nose_mm - X.min()) * 1e-3
    return ((x0 - pad_m, 0.0, max(Z.min() * 1e-3 - pad_m, 0.0)),
            (x1 + pad_m, np.abs(Y).max() * 1e-3 + pad_m, Z.max() * 1e-3 + pad_m))


def in_region(car, C):
    """Cell centres (CFD frame, m) -> inside the sidepod region voxels (STEP frame, mm)."""
    s = car.s
    X = s.x_nose_mm - C[:, 0] * 1e3
    Y = np.abs(C[:, 1]) * 1e3
    Z = C[:, 2] * 1e3
    h = car.h
    i = np.round((X - car.xs[0]) / h).astype(int)
    j = np.round((Y - car.ys[0]) / h).astype(int)
    k = np.round((Z - car.zs[0]) / h).astype(int)
    ok = (i >= 0) & (i < car.region.shape[0]) & (j >= 0) & (j < car.region.shape[1]) & (k >= 0) & (k < car.region.shape[2])
    out = np.zeros(len(C), bool)
    out[ok] = car.region[i[ok], j[ok], k[ok]]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", default="coarse")
    ap.add_argument("--region_level", type=int, default=4, help="snappy level inside the design region")
    ap.add_argument("--pad_mm", type=float, default=2.0, help="refinement box margin around the region")
    ap.add_argument("--cycles", type=int, default=60)
    ap.add_argument("--np", type=int, default=4)
    ap.add_argument("--iters", type=int, default=300, help="primal and adjoint iterations per cycle")
    ap.add_argument("--init_iters", type=int, default=1500, help="... in the first cycle")
    ap.add_argument("--solid_max", type=float, default=0.6)
    ap.add_argument("--beta_max", type=float, default=1.0e5, help="Brinkman coefficient of full solid, 1/s")
    ap.add_argument("--out", default=str(HERE / "car_coarse"))
    a = ap.parse_args()
    import openfoam_adjoint as OA
    import openfoam_case as oc
    import stopwatch as SW
    import gate

    out = Path(a.out)
    lean = HERE / "lean_car"
    car = lean_car(lean)
    body = SW.body_stl(lean / "car_half.stl", lean / "_body_half.stl")
    cfg = OA.AdjointRunConfig(resolution=a.res, n_subdomains=a.np, extra_surfaces=SW.extra_surfaces(lean),
                              domain_reference_bounds=gate.DOMAIN, layer_overrides={"nSurfaceLayers": 0})
    OA.build_adjoint_case(str(out), str(body), cfg)

    # --- a refinement box over the design region, so the free cells are fine enough to grow detail
    (bx0, by0, bz0), (bx1, by1, bz1) = region_box_car_frame(car, pad_m=a.pad_mm * 1e-3)
    sh = (out / "system" / "snappyHexMeshDict").read_text()
    sh = sh.replace("\n    underbody\n", f"\n    design\n    {{\n        type searchableBox;\n        min  ({bx0} {by0} {bz0});\n"
                    f"        max  ({bx1} {by1} {bz1});\n    }}\n\n    underbody\n", 1)
    sh = sh.replace("refinementRegions { underbody", f"refinementRegions {{ design {{ mode inside; levels ((1e15 {a.region_level})); }} underbody", 1)
    (out / "system" / "snappyHexMeshDict").write_text(sh)

    # --- mesh (serial), then the zones
    for cmd, log in (("surfaceFeatureExtract", "surfaceFeatureExtract.log"), ("blockMesh", "blockMesh.log"),
                     ("snappyHexMesh -overwrite", "snappyHexMesh.log"), ("checkMesh", "checkMesh.log"),
                     ("postProcess -func writeCellCentres -time 0", "cellCentres.log")):
        oc._run(cmd, out, BASHRC, log, 3600)
    C = read_vector_field(out / "0" / "C")
    design = np.nonzero(in_region(car, C))[0]
    sets = out / "constant" / "polyMesh" / "sets"
    sets.mkdir(exist_ok=True)
    write_cellset(sets / "designSpace", design)
    write_cellset(sets / "allCells", np.arange(len(C)))
    oc._run("setsToZones -noFlipMap", out, BASHRC, "setsToZones.log", 600)
    for f in ("C", "Cx", "Cy", "Cz"):
        (out / "0" / f).unlink(missing_ok=True)

    # --- topology optimisation settings
    patch_files(out, a)
    cells = int(re.search(r"cells:\s+(\d+)", (out / "logs" / "checkMesh.log").read_text()
                          if (out / "logs" / "checkMesh.log").exists() else (out / "checkMesh.log").read_text()).group(1))
    meta = {"cells": cells, "design_cells": int(len(design)), "region_box_m": [[bx0, by0, bz0], [bx1, by1, bz1]],
            "res": a.res, "region_level": a.region_level, "cycles": a.cycles, "solid_max": a.solid_max,
            "beta_max": a.beta_max}
    (out / "topo_meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta))


def read_vector_field(p: Path) -> np.ndarray:
    t = p.read_text()
    m = re.search(r"internalField\s+nonuniform\s+List<vector>\s*(\d+)\s*\(", t)
    n = int(m.group(1))
    body = t[m.end(): m.end() + n * 80]
    v = np.array(re.findall(r"\(([^()]+)\)", body)[:n], dtype=object)
    return np.array([list(map(float, s.split())) for s in v])


def write_cellset(p: Path, ids):
    hdr = ("FoamFile\n{\n    version 2.0;\n    format ascii;\n    class cellSet;\n    location \"constant/polyMesh/sets\";\n"
           f"    object {p.name};\n}}\n\n{len(ids)}\n(\n")
    p.write_text(hdr + "\n".join(map(str, ids)) + "\n)\n")


def patch_files(out: Path, a):
    sysd = out / "system"
    # controlDict: one time step = one optimisation cycle
    cd = (sysd / "controlDict").read_text()
    cd = re.sub(r"endTime\s+\d+;", f"endTime         {a.cycles};", cd)
    cd = re.sub(r"writeInterval\s+\d+;", "writeInterval   5;", cd)
    (sysd / "controlDict").write_text(cd)
    # schemes: differentiable wall distance (topology changes the walls), and its convection terms
    fs = (sysd / "fvSchemes").read_text()
    fs = re.sub(r"wallDist\s*\{[^}]*\}", "wallDist\n{\n    method advectionDiffusion;\n    advectionDiffusionCoeffs\n"
                "    {\n        method    meshWave;\n        tolerance 1.e-6;\n        maxIter   1000;\n        epsilon   0.1;\n    }\n}", fs)
    fs = fs.replace("gradSchemes\n{", "gradSchemes\n{\n    gradDConv       cellLimited Gauss linear 1;\n"
                    "    gradDaConv      cellLimited Gauss linear 1;", 1)
    fs = fs.replace("    div(-phi,wa)       bounded Gauss upwind;",
                    "    div(-phi,wa)       bounded Gauss upwind;\n    div(yPhi,yWall)    Gauss linearUpwind gradDConv;\n"
                    "    div(-yPhi,da)      Gauss linearUpwind gradDaConv;", 1)
    assert "gradDConv" in fs and "div(yPhi,yWall)" in fs, "fvSchemes layout changed"
    (sysd / "fvSchemes").write_text(fs)
    fsol = (sysd / "fvSolution").read_text()
    fsol = fsol.replace("    ma\n", "    \"(yWall|da)\"\n    {\n        solver          smoothSolver;\n        smoother        symGaussSeidel;\n"
                        "        tolerance       1e-8;\n        relTol          0.1;\n    }\n    bTilda\n    {\n        solver          GAMG;\n"
                        "        tolerance       1e-8;\n        relTol          0.01;\n        smoother        GaussSeidel;\n    }\n    ma\n", 1)
    (sysd / "fvSolution").write_text(fsol)
    # Brinkman source in every primal and adjoint equation it enters (SST: U, k, omega, wall distance)
    (sysd / "fvOptions").write_text(
        "FoamFile { version 2.0; format ascii; class dictionary; object fvOptions; }\n"
        "eqSource\n{\n    type        topOSource;\n    names       (U k omega yWall Ua ka wa da);\n"
        "    function    linear;\n    interpolationField beta;\n}\n")
    # optimisationDict: steady optimisation, dissipation objective, solid-fraction constraint, topO variables
    od = (sysd / "optimisationDict").read_text()
    od = od.replace("optimisationManager singleRun;", "optimisationManager steadyOptimisation;")
    # per optimisation cycle: a short warm-started primal and adjoint; a long first one
    od, n = re.subn(r"nIters \d+;", f"nIters {a.iters};\n            nInitialIters {a.init_iters};", od)
    assert n == 2, f"expected a primal and an adjoint nIters, found {n}"
    od = re.sub(r"objectiveNames\s*\{\s*drag\s*\{[^}]*\}\s*\}",
                "objectiveNames\n                    {\n                        dissipation\n                        {\n"
                "                            weight     1.;\n                            type       powerDissipation;\n"
                "                            zones      (allCells);\n                        }\n                    }", od, count=1)
    od = od.replace("                computeSensitivities   true;\n", "")
    # the constraint: a null adjoint solver holding a geometric objective
    od = re.sub(r"(adjointSolvers\s*\{)", r"\1\n            solidVol\n            {\n                active       true;\n"
                r"                type         null;\n                isConstraint true;\n                objectives\n"
                r"                {\n                    type  geometric;\n                    objectiveNames\n                    {\n"
                f"                        solidVol {{ weight 1.; type topOSolidVolume; percentage {a.solid_max}; }}\n"
                r"                    }\n                }\n            }", od, count=1)
    od = re.sub(r"optimisation\s*\{\s*designVariables\s*\{.*\}\s*\}\s*$",
                "optimisation\n{\n    designVariables\n    {\n        type               topO;\n        sensitivityType    topO;\n"
                "        adjointPorousZones (designSpace);\n        regularisation\n        {\n            regularise     true;\n"
                "            growFromWalls  true;\n            meanRadiusMult 2;\n            function       tanh;\n            b              40;\n"
                f"        }}\n        betaMax            {a.beta_max};\n        maxInitChange      0.2;\n    }}\n"
                "    updateMethod\n    {\n        method nullSpace;\n    }\n}\n", od, flags=re.S)
    assert "topOSolidVolume" in od and "powerDissipation" in od and "type               topO" in od, "optimisationDict layout changed"
    (sysd / "optimisationDict").write_text(od)


if __name__ == "__main__":
    main()
