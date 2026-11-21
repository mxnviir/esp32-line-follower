"""A FAIR test of OpenFOAM's own (ESI, continuous) adjoint: on the exact mesh and converged flow where the
DAFoam adjoint passed its check (coarse steady state, gate/refA_coarse_up), judged against the same six
measured +/-1 mm bumps (gate_results_coarse_up). The first ESI test (gate_results/RESULT.md) solved
different meshes (375 k vs 520 k cells) on an unsteady flow, so it never tested ESI itself.

    python esi/esi_on_state.py <state dir> <out case dir> <turb: sst|frozen> [np] [adjoint iters] [primal iters]
      -> <out>/esi_sens.npz (Xs, dD_dXs in N/m per point, like DAFoam's), esi_sens.json
    python dafoam/pair_judge.py <out>/esi_sens.npz gate_results_coarse_up --sites pod_rear pod_front_low pod_rear_top

turb "sst": adjointkOmegaSST (the adjoint of the turbulence model too; it crashed with SIGFPE once in 2026-07
on a different mesh/flow). "frozen": adjointLaminar (nu_t held fixed: cheap, approximate, the common
industrial choice). Same pass marks as DAFoam's check: r >= 0.9, every sign of a pair above 3 sigma agrees.
Cost: about the primal's own (no Jacobian, no colouring); memory a few times the primal's.
"""
import json, os, re, shutil, subprocess, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
P2 = HERE.parents[2] / "part2-simulation"
sys.path.insert(0, str(P2))
import openfoam_case as oc          # noqa: E402
import openfoam_adjoint as oa       # noqa: E402

src, out, turb = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
n = int(sys.argv[4]) if len(sys.argv) > 4 else 4
adj_it = int(sys.argv[5]) if len(sys.argv) > 5 else 3000
pri_it = int(sys.argv[6]) if len(sys.argv) > 6 else 100
bashrc = os.environ.get("OF_BASHRC", "/usr/lib/openfoam/openfoam2412/etc/bashrc")
RHO = 1.225
t = max((p.name for p in src.iterdir() if re.fullmatch(r"\d+", p.name) and p.name != "0"), key=int)

if out.exists():
    shutil.rmtree(out)
(out / "constant").mkdir(parents=True); (out / "system").mkdir(); (out / "0").mkdir()
shutil.copytree(src / "constant" / "polyMesh", out / "constant" / "polyMesh")
for f in ("transportProperties", "turbulenceProperties"):
    shutil.copy(src / "constant" / f, out / "constant" / f)
for f in ("U", "p", "k", "omega", "nut", "phi"):          # the converged steady flow is the primal's start
    if (src / t / f).exists():
        b = (src / t / f).read_bytes().replace(f'location    "{t}";'.encode(), b'location    "0";')
        (out / "0" / f).write_bytes(b)
patches = re.findall(r"^\s{4}(\w+)\s*$", (src / "constant" / "polyMesh" / "boundary").read_text(), re.M)
assert {"car", "wheelF", "wheelR"} <= set(patches), patches

cfg = oa.AdjointRunConfig(primal_iters=pri_it, adjoint_iters=adj_it, resolution="coarse", n_subdomains=n)
meta = json.loads((src / "case_meta.json").read_text()) if (src / "case_meta.json").exists() else {}
aref = meta.get("frontal_area_half", 7.3e-4)
(out / "system" / "controlDict").write_text(oa.build_adjoint_control_dict(cfg))
fs = oa._FV_SCHEMES_ADJOINT
fs2 = re.sub(r"div\(phi,U\)\s+[^;]+;", "div(phi,U)         bounded Gauss upwind;", fs, count=1)   # the steady model
assert fs2 != fs
(out / "system" / "fvSchemes").write_text(fs2)
fsol = oa._FV_SOLUTION_ADJOINT
if os.environ.get("ESI_MESHMOVE") == "1":   # solvers for the adjoint eikonal (da) and adjoint grid displacement (ma), as liftFullSetup
    fsol = fsol.replace("solvers\n{", """solvers
{
    "(m|ma)" { solver PCG; preconditioner DIC; tolerance 1e-9; relTol 0.01; }
    "(yWall|da)" { solver PBiCGStab; preconditioner DILU; tolerance 1e-9; relTol 0.1; }""", 1)
    assert '"(m|ma)"' in fsol, "solvers block not found"
    fsol = re.sub(r"(equations\s*\{)", r'\1\n        "da.*" 0.7;\n        "yWall.*" 0.5;', fsol, count=1)
    fs2 = fs2.replace("divSchemes\n{", "divSchemes\n{\n    div(-yPhi,da)      Gauss linearUpwind gradDaConv;\n    div(yPhi,yWall)    Gauss linearUpwind gradDConv;", 1)
    fs2 = fs2.replace("gradSchemes\n{", "gradSchemes\n{\n    gradDaConv      cellLimited Gauss linear 1;\n    gradDConv       cellLimited Gauss linear 1;", 1)
    assert "gradDaConv" in fs2 and "div(-yPhi,da)" in fs2
    (out / "system" / "fvSchemes").write_text(fs2)
(out / "system" / "fvSolution").write_text(fsol)
(out / "system" / "decomposeParDict").write_text(oc._decompose_dict(n))
od = oa.build_optimisation_dict(cfg, aref)
od = re.sub(r"patches\s+\(([^)]*)\);(\s*direction)", r"patches    (car wheelF wheelR);\2", od, count=1)   # objective = D20's patches
od = re.sub(r"(designVariables[\s\S]*?patches\s+)\([^)]*\);", r"\1(car);", od, count=1)               # sensitivity on the body
# ESI's own "full setup" (tutorials .../naca0012/turbulent/liftFullSetup): grid sensitivities and the wall
# distance terms on, ATC term kept near walls. Our default ("minimum setup") drops all three.
if os.environ.get("ESI_MESHMOVE") == "1":
    od = od.replace("includeMeshMovement false;", """includeMeshMovement true;
        includeDistance     true;
        adjointMeshMovementSolver { iters 1000; tolerance 1.e-6; }""")
    assert "includeMeshMovement true;" in od
if os.environ.get("ESI_ATC_FULL") == "1":
    od2 = re.sub(r"nSmooth\s+\d+;", "nSmooth           0;", od)
    od2 = re.sub(r"zeroATCPatchTypes\s+\([^)]*\);", "zeroATCPatchTypes ();", od2)
    od2 = re.sub(r"maskType\s+\w+;", "maskType          faceCells;", od2)
    assert od2 != od; od = od2
(out / "system" / "optimisationDict").write_text(od)
ras = oa.build_adjoint_ras_properties()
ras = ras.replace("adjointRASModel adjointLaminar;", "adjointRASModel adjointkOmegaSST;" if turb == "sst" else "adjointRASModel adjointLaminar;")
(out / "constant" / "adjointRASProperties").write_text(ras)
oa._write_adjoint_fields(out / "0")
for f in ("Ua", "pa", "ka", "wa"):                         # wheels: the same wall conditions as the body
    p = out / "0" / f
    if p.exists():
        s = p.read_text()
        line = re.search(r"^\s*car\s+\{[^}]*\}\s*$", s, re.M).group(0)
        s = s.replace(line, line + "\n" + line.replace("car", "wheelF", 1) + "\n" + line.replace("car", "wheelR", 1))
        p.write_text(s)
print("objective/sensitivity patches:", re.findall(r"patches\s+\([^)]*\);", od), flush=True)

sh = f"""source {bashrc} || true; set -e; export OMPI_ALLOW_RUN_AS_ROOT=1 OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1
cd {out}; foamFormatConvert -constant > log.formatConvert 2>&1   # the parsers below read ASCII
decomposePar -force > log.decompose 2>&1
mpirun -np {n} adjointOptimisationFoam -parallel > log.adjoint 2>&1
reconstructPar -latestTime > log.reconstruct 2>&1; rm -rf processor*"""
r = subprocess.run(["bash", "-c", sh])
tail = (out / "log.adjoint").read_text(errors="replace")[-3000:] if (out / "log.adjoint").exists() else ""
if r.returncode != 0:
    print("ESI_FAILED rc", r.returncode, "\n", tail[-1500:], flush=True)
    sys.exit(1)

# per-point outward normal sensitivity (dJ per unit outward move per unit area, kinematic) -> N/m vector per point
pts, s_out = oa.outward_sensitivity(str(out))
b = (out / "constant" / "polyMesh")
P = oa.read_polymesh_points(str(out))
bd = oa._read_boundary(b.joinpath("boundary").read_text())
start, nf = bd["car"]
def car_faces(path, start, nf):
    """Faces start..start+nf of an ASCII faceList, streamed line by line (a 5 M-cell mesh has ~15 M faces:
    reading the whole file into one regex, as Part 2's helper does, needs many GB)."""
    out, i, body = [], -1, False
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            if not body:
                if line.strip() == "(":
                    body, i = True, 0
                continue
            if i >= start + nf:
                break
            if i >= start:
                s = line.strip()
                out.append(np.array(s[s.index("(") + 1:s.rindex(")")].split(), dtype=np.int64))
            i += 1
    assert len(out) == nf, (len(out), nf)
    return out
faces = car_faces(b / "faces", start, nf)
avec = np.zeros_like(P)
for f in faces:
    v = P[list(f)]
    Sf = 0.5 * np.cross(v[1:-1] - v[0], v[2:] - v[0]).sum(0)          # points out of the fluid (into the body)
    avec[list(f)] += -Sf / len(f)                                    # outward from the body, area shared per corner
from scipy.spatial import cKDTree
ids = np.unique(np.concatenate([np.asarray(f) for f in faces]))
d, j = cKDTree(pts).query(P[ids])
assert np.median(d) < 1e-9, f"sensitivity points don't sit on the car patch (median {np.median(d)})"
an = np.linalg.norm(avec[ids], axis=1, keepdims=True)
G = RHO * s_out[j][:, None] * avec[ids]                              # dD/dX (N/m): dD = sum G . dX
np.savez(out / "esi_sens.npz", Xs=P[ids], dD_dXs=G, s_out=s_out[j], area=an.ravel())
res = re.findall(r"^\s*(?:DILUPBiCGStab|smoothSolver|GAMG|PBiCGStab):\s+Solving for (pa|Uax|ka|wa).*Initial residual = ([0-9.e+-]+)", tail, re.M)
json.dump({"turbulence": turb, "adjoint_iters": adj_it, "n_points": int(len(ids)), "sum_dD_dXs": G.sum(0).tolist(),
           "last_residuals": res[-4:]}, open(out / "esi_sens.json", "w"), indent=1)
print("ESI_DONE", len(ids), "points", flush=True)
