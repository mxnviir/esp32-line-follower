"""Build the DAFoam case from a converged OpenFOAM state of THIS pipeline (default: the gate's state A).

Same mesh, same boundary conditions (rolling road, rotating wheels, Spalding wall functions), same
schemes and SIMPLE settings as the runs the adjoint is judged against: the ESI adjoint's lesson is that
any mismatch with the measured flow (its own primal ended 2.5 % off) muddies the test. The flow starts
from the converged state, so DAFoam's primal only has to settle, not converge from scratch.

    python dafoam/make_case.py [--src gate/refA] [--time 2000] [--out gate/dafoam_case] [--iters 300]
"""
import argparse
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
SP = HERE.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(SP / "gate" / "refA"))
    ap.add_argument("--time", default=None, help="time folder of the converged state (default: latest)")
    ap.add_argument("--out", default=str(SP / "gate" / "dafoam_case"))
    ap.add_argument("--iters", type=int, default=300, help="primal SIMPLE iterations DAFoam runs from the state")
    a = ap.parse_args()
    src, out = Path(a.src), Path(a.out)
    t = a.time or max((p.name for p in src.iterdir() if re.fullmatch(r"\d+", p.name) and p.name != "0"), key=int)
    if out.exists():
        shutil.rmtree(out)
    (out / "constant").mkdir(parents=True)
    shutil.copytree(src / "constant" / "polyMesh", out / "constant" / "polyMesh")
    for f in ("transportProperties", "turbulenceProperties"):
        shutil.copy(src / "constant" / f, out / "constant" / f)
    tp = out / "constant" / "transportProperties"             # DAFoam reads Pr/Prt even without heat transfer
    tp.write_text(tp.read_text().rstrip() + "\nPr              0.7;\nPrt             0.85;\n")
    (out / "0").mkdir()
    for f in ("U", "p", "k", "omega", "nut", "phi"):
        if (src / t / f).exists():
            b = (src / t / f).read_bytes().replace(f'location    "{t}";'.encode(), b'location    "0";')
            (out / "0" / f).write_bytes(b)
    shutil.copytree(src / "system", out / "system")
    for f in ("decomposeParDict",):
        (out / "system" / f).unlink(missing_ok=True)
    (out / "system" / "controlDict").write_text(CONTROL.replace("@ITERS@", str(a.iters)))
    fs = (out / "system" / "fvSchemes").read_text()
    print(f"case {out} from {src}/{t}; schemes kept:\n" + "\n".join(l for l in fs.splitlines() if re.search(r"Gauss|limited|default", l)))


CONTROL = r"""FoamFile { version 2.0; format ascii; class dictionary; location "system"; object controlDict; }
application     DASimpleFoam;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         @ITERS@;
deltaT          1;
writeControl    timeStep;
writeInterval   @ITERS@;
purgeWrite      0;
writeFormat     ascii;      // DAFoam's AD build (CoDiPack scalars) cannot read binary
writePrecision  16;
writeCompression off;
timeFormat      general;
timePrecision   16;
runTimeModifiable false;
"""

if __name__ == "__main__":
    main()
