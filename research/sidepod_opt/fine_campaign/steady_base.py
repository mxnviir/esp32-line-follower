"""The adjoint's base state on any mesh: continue a converged production state with first-order upwind U
(the "steady model" of ROUTES.md 2026-11-20), and test whether the wake actually goes steady there.

    python fine_campaign/steady_base.py <production state dir> <steady state dir> <results dir> [np] [extra iters]

Writes <results dir>/base.json (D20_half_N, run_dir_kept, flatness). PASS mark (fixed 2026-11-21, before
any fine/resolved result): over the last 1,000 iterations the 100-iteration block means of the half-car
drag span <= 0.10 mN (coarse: 0.02 mN). A ±1 mm bump moves drag by 0.25-1.6 mN, so a base that wanders
more than ~0.1 mN can't measure it, and DAFoam's Krylov adjoint stalls on an unsteady primal.
FAIL => the steady-model trick does not carry to this mesh; the adjoint stage must not run on it.
"""
import json, os, re, shutil, subprocess, sys
from pathlib import Path
import numpy as np

src, dst, res = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
n = int(sys.argv[4]) if len(sys.argv) > 4 else 4
extra = int(sys.argv[5]) if len(sys.argv) > 5 else 3000
bashrc = os.environ.get("OF_BASHRC", "/usr/lib/openfoam/openfoam2412/etc/bashrc")
res.mkdir(parents=True, exist_ok=True)
times = lambda d: sorted((int(p.name) for p in d.iterdir() if re.fullmatch(r"\d+", p.name)), key=int)
if not (dst / "STEADY_DONE").exists():
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("processor*", "postProcessing", "logs"))
    t0 = times(dst)[-1]
    fs = dst / "system" / "fvSchemes"
    s = fs.read_text()
    s2 = re.sub(r"div\(phi,U\)\s+[^;]+;", "div(phi,U)      bounded Gauss upwind;", s, count=1)
    assert s2 != s or "div(phi,U)      bounded Gauss upwind;" in s, "div(phi,U) not found"
    fs.write_text(s2)
    cd = dst / "system" / "controlDict"
    c = cd.read_text()
    for k, v in (("startFrom", "latestTime"), ("endTime", str(t0 + extra)), ("writeInterval", str(extra)), ("purgeWrite", "0")):
        c = re.sub(rf"^{k}\s+[^;]+;", f"{k}       {v};", c, flags=re.M)
    cd.write_text(c)
    dp = dst / "system" / "decomposeParDict"
    if dp.exists():
        dp.write_text(re.sub(r"numberOfSubdomains\s+\d+;", f"numberOfSubdomains {n};", dp.read_text()))
    sh = f"""source {bashrc} || true; set -e; export OMPI_ALLOW_RUN_AS_ROOT=1 OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1
cd {dst}; decomposePar -force -latestTime > log.decompose 2>&1
mpirun -np {n} simpleFoam -parallel > log.simpleFoam 2>&1
reconstructPar -latestTime > log.reconstruct 2>&1; rm -rf processor*"""
    subprocess.run(["bash", "-c", sh], check=True)
    (dst / "STEADY_DONE").write_text(str(t0))
t0 = int((dst / "STEADY_DONE").read_text())
f = sorted((dst / "postProcessing" / "forces").glob("*/force.dat"))[-1]
a = np.loadtxt(f, comments="#")
D = a[:, 1] * 1e3                                    # half-car drag, mN (total over car + wheels: the forces FO)
last = D[-1000:]
blocks = last[: len(last) // 100 * 100].reshape(-1, 100).mean(1)
span = float(blocks.max() - blocks.min())
d = {"D20_half_N": float(D[-int(0.2 * len(D)):].mean() * 1e-3), "converged": span <= 0.10,
     "steady_pass": span <= 0.10, "block_span_last1000_mN": span, "block_means_mN": blocks.round(3).tolist(),
     "run_dir_kept": str(dst.resolve()), "from_state": str(src), "from_time": t0, "extra_iterations": extra,
     "scheme_div_phi_U": "bounded Gauss upwind", "n_proc": n}
(res / "base.json").write_text(json.dumps(d, indent=1))
print(json.dumps(d), flush=True)
print("STEADY_PASS" if d["steady_pass"] else "STEADY_FAIL", flush=True)
