"""Make a topology run variant from a meshed base case (topo/make_topo_case.py).

Objective = RACE TIME, from Part 2's race model (objective.RaceModel) at the original car:
    dT = 0.179 s/N * dD20 - 0.00195 s/N * dL20 + 7.5 s/kg * (mass above the 48.2 g floor)
- Drag: total dissipated power (kinematic) over the whole domain, porous solid included.
  D_whole ~ 2 P_half / U (a proxy; topo/proxy_check checks it against body-fitted CFD).
- Lift: wall force along +z on car + wheels (the porous body's lift is not in it; the term is
  90x weaker than drag).
- Mass: the empty-region car is AT the floor with 10.26 g of lead. Foam added up to that lead
  (62,962 mm3, whole car) is free; beyond it, 1 cm3 costs 1.22 ms (= 6.8 mN of drag), more than
  any measured drag gain per volume. So mass enters as a hard cap at the lead budget, minus a margin
  for what milling adds. ESI's cap is a fraction of the WHOLE mesh volume.
Modes:
  optimise          design cells free; start empty or half solid
  fixed_empty       nothing free, design region all air        (known-answer test)
  fixed_original    nothing free, the team's sidepod cells solid (known-answer test)

    python topo/configure.py <base_case> <out_case> --mode optimise --start empty --cycles 60
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SP = HERE.parent
sys.path.insert(0, str(SP)); sys.path.insert(0, str(HERE))
BASHRC = "/usr/lib/openfoam/openfoam2412/etc/bashrc"

RHO, U = 1.225, 20.0
DT_DD, DT_DL = 0.178925, -0.00195           # s per N, whole car (objective.RaceModel at the original)
FREE_FOAM_MM3_WHOLE = 62962.0               # lead budget of the empty-region car, as foam


def foam(cmd, cwd):
    subprocess.run(["bash", "-c", f"source {BASHRC} >/dev/null 2>&1; {cmd}"], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def scalar_field(p):
    t = p.read_text()
    m = re.search(r"internalField\s+nonuniform\s+List<scalar>\s*(\d+)\s*\(", t)
    return np.array(t[m.end():].split(")", 1)[0].split()[: int(m.group(1))], float)


def write_scalar_field(p, name, vals, patches):
    bf = "\n".join(f"    {n} {{ type zeroGradient; }}" if t != "symmetryPlane" else f"    {n} {{ type symmetryPlane; }}"
                   for n, t in patches)
    p.write_text("FoamFile { version 2.0; format ascii; class volScalarField; object " + name + "; }\n"
                 f"dimensions [0 0 0 0 0 0 0];\ninternalField nonuniform List<scalar> {len(vals)}\n(\n"
                 + "\n".join(f"{v:.6g}" for v in vals) + "\n);\nboundaryField\n{\n" + bf + "\n}\n")


def patches_of(case):
    t = (case / "constant" / "polyMesh" / "boundary").read_text()
    return re.findall(r"\n\s+(\w+)\s*\{\s*type\s+(\w+);", t)


def cell_zones(case):
    t = (case / "constant" / "polyMesh" / "cellZones").read_text()
    return re.findall(r"\n(\w+)\n\{\s*type cellZone;", t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base"); ap.add_argument("out")
    ap.add_argument("--mode", default="optimise", choices=["optimise", "fixed_empty", "fixed_original"])
    ap.add_argument("--start", default="empty", choices=["empty", "half", "original"])
    ap.add_argument("--cap_mm3", type=float, default=None, help="half-car solid cap, mm3 (default: lead budget x margin)")
    ap.add_argument("--b", default=None, help="constant projection sharpness (default: ramp 2 -> 40)")
    ap.add_argument("--cycles", type=int, default=60)
    ap.add_argument("--radius", type=float, default=0.0025, help="filter radius, m")
    ap.add_argument("--mill_margin", type=float, default=0.85, help="share of the lead budget the porous design may use")
    a = ap.parse_args()
    base, out = Path(a.base), Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(base, out, ignore=shutil.ignore_patterns("processor*", "log.*", "optimisation", "[1-9]*", "car_t*", "extract_*"))

    # --- zones: outside (pinned air), origPod (design cells inside the team's sidepod)
    if not (out / "0" / "C").exists():
        foam("postProcess -func writeCellCentres -time 0", out)
    foam("postProcess -func writeCellVolumes -time 0", out)
    from make_topo_case import read_vector_field, write_cellset, in_region  # noqa: E402
    from geometry import Car  # noqa: E402
    C = read_vector_field(out / "0" / "C")
    V = scalar_field(out / "0" / "V")
    design = np.array((out / "constant" / "polyMesh" / "sets" / "designSpace").read_text().split("(", 1)[1].split(")")[0].split(), int)
    isd = np.zeros(len(C), bool); isd[design] = True
    car = Car()
    s = car.s
    X, Y, Z = s.x_nose_mm - C[:, 0] * 1e3, np.abs(C[:, 1]) * 1e3, C[:, 2] * 1e3
    i = np.clip(np.round((X - car.xs[0]) / car.h).astype(int), 0, car.body0.shape[0] - 1)
    j = np.clip(np.round((Y - car.ys[0]) / car.h).astype(int), 0, car.body0.shape[1] - 1)
    k = np.clip(np.round((Z - car.zs[0]) / car.h).astype(int), 0, car.body0.shape[2] - 1)
    orig = isd & car.body0[i, j, k]
    sets = out / "constant" / "polyMesh" / "sets"
    write_cellset(sets / "outside", np.nonzero(~isd)[0])
    write_cellset(sets / "origPod", np.nonzero(orig)[0])
    write_cellset(sets / "designRest", np.nonzero(isd & ~orig)[0])
    foam("setsToZones -noFlipMap", out)
    for f in ("C", "V"):
        (out / "0" / f).unlink(missing_ok=True)
    v_total = float(V.sum()); v_design = float(V[isd].sum()); v_orig = float(V[orig].sum())
    cap_mm3_half = a.cap_mm3 if a.cap_mm3 else 0.5 * FREE_FOAM_MM3_WHOLE * a.mill_margin
    cap_frac = cap_mm3_half * 1e-9 / v_total

    # --- initial design
    alpha = np.zeros(len(C))
    if a.mode == "optimise" and a.start == "half":
        alpha[isd] = 0.5
    if a.mode == "fixed_original" or (a.mode == "optimise" and a.start == "original"):
        alpha[orig] = 1.0
    write_scalar_field(out / "0" / "alpha", "alpha", alpha, patches_of(out))

    # --- optimisationDict
    od = (out / "system" / "optimisationDict").read_text()
    w_p = 2.0 * DT_DD / U                       # s per (kinematic W) of half-car dissipation
    w_l = 2.0 * DT_DL                           # s per (kinematic N) of half-car lift
    od = re.sub(r"dissipation\s*\{[^}]*\}",
                "dissipation\n                        {\n                            weight     %.6g;\n"
                "                            type       powerDissipation;\n                            zones      (allCells);\n"
                "                        }\n                        lift\n                        {\n"
                "                            weight     %.6g;\n                            type       force;\n"
                "                            patches    (car wheelF wheelR);\n                            direction  (0 0 1);\n"
                "                            Aref       0.005;\n                            rhoInf     1.225;\n"
                "                            UInf       20.0;\n                        }\n"
                "                        dragWall\n                        {\n                            weight     0;\n"
                "                            type       force;\n                            patches    (car wheelF wheelR);\n"
                "                            direction  (1 0 0);\n                            Aref       0.005;\n"
                "                            rhoInf     1.225;\n                            UInf       20.0;\n                        }"
                % (w_p, w_l), od, count=1)
    od = re.sub(r"solidVol \{[^}]*\}", f"solidVol {{ weight 1.; type topOSolidVolume; percentage {cap_frac:.6g}; }}", od, count=1)
    if a.mode == "optimise":
        zones = "        adjointPorousZones   (designSpace);\n        fixedZeroPorousZones (outside);\n"
    elif a.mode == "fixed_empty":
        zones = "        fixedZeroPorousZones (outside designSpace);\n"
    else:
        zones = ("        fixedPorousZones     (origPod);\n        fixedPorousValues    (1);\n"
                 "        fixedZeroPorousZones (outside designRest);\n")
    od = re.sub(r"        adjointPorousZones \(designSpace\);\n", zones, od, count=1)
    od = re.sub(r"meanRadiusMult \d+;", f"radius         {a.radius};", od, count=1)
    # sharpness ramp: a soft projection first (pure-fluid cells keep a gradient), sharp at the end
    n = max(a.cycles, 1)
    if a.b is not None:
        bspec = a.b
    elif a.mode == "optimise" and n >= 10:
        bspec = "table ((0 2) (%d 2) (%d 8) (%d 40) (%d 40))" % (int(0.3 * n), int(0.6 * n), int(0.85 * n), n + 1000)
    else:
        bspec = "40"                            # fixed designs: every cell is pinned; a crisp projection
    od = re.sub(r"\n(\s*)b\s+\d+;", "\n\\1b              %s;" % bspec, od, count=1)
    assert "dragWall" in od and f"b              {bspec};" in od and f"{a.radius}" in od, "optimisationDict layout changed"
    (out / "system" / "optimisationDict").write_text(od)
    cd = (out / "system" / "controlDict").read_text()
    cd = re.sub(r"endTime\s+\d+;", f"endTime         {a.cycles};", cd)
    cd = re.sub(r"writeInterval\s+\d+;", f"writeInterval   {1 if a.cycles <= 5 else 5};", cd)
    (out / "system" / "controlDict").write_text(cd)
    meta = {"mode": a.mode, "start": a.start, "cycles": a.cycles, "radius_m": a.radius,
            "v_total_m3": v_total, "v_design_mm3_half": v_design * 1e9, "v_original_pod_mm3_half": v_orig * 1e9,
            "solid_cap_mm3_half": cap_mm3_half, "solid_cap_fraction_of_mesh": cap_frac,
            "weights": {"dissipation_kinematic_W_half": w_p, "lift_kinematic_N_half": w_l},
            "race_model": {"dT_dD20_s_per_N": DT_DD, "dT_dL20_s_per_N": DT_DL, "mass_above_floor_s_per_kg": 7.514}}
    (out / "topo_variant.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
