"""Voxelize every solid of the STEP at 1 mm with OpenCascade's own inside test (robust to the
non-watertight tessellation). Writes cad/vox1mm.npz: one bool grid per solid + the grid axes."""
import numpy as np, sys
from pathlib import Path
from OCP.STEPControl import STEPControl_Reader
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID, TopAbs_IN, TopAbs_ON
from OCP.TopoDS import TopoDS
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.gp import gp_Pnt
from multiprocessing import Pool

HERE = Path(__file__).resolve().parent
H = 1.0
XS = np.arange(-30.0, 231.0, H) + H / 2
YS = np.arange(-40.0, 40.0, H) + H / 2
ZS = np.arange(0.0, 50.0, H) + H / 2


def solids():
    r = STEPControl_Reader(); r.ReadFile(str(HERE / "cad/trial_car.step")); r.TransferRoots()
    tr = r.WS().TransferReader(); out = {}
    ex = TopExp_Explorer(r.OneShape(), TopAbs_SOLID)
    while ex.More():
        s = TopoDS.Solid(ex.Current()); e = tr.EntityFromShapeResult(s, 1)
        out[e.Name().ToCString()] = s; ex.Next()
    return out


def column_block(args):
    name, i0, i1 = args
    s = solids()[name]
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    b = Bnd_Box(); BRepBndLib.Add_s(s, b); p0, p1 = b.CornerMin(), b.CornerMax(); x0, y0, z0, x1, y1, z1 = p0.X(), p0.Y(), p0.Z(), p1.X(), p1.Y(), p1.Z()
    cl = BRepClass3d_SolidClassifier(s)
    g = np.zeros((i1 - i0, len(YS), len(ZS)), bool)
    for ii, i in enumerate(range(i0, i1)):
        x = XS[i]
        if x < x0 or x > x1: continue
        for j, y in enumerate(YS):
            if y < y0 or y > y1: continue
            for k, z in enumerate(ZS):
                if z < z0 or z > z1: continue
                cl.Perform(gp_Pnt(x, y, z), 1e-6)
                g[ii, j, k] = cl.State() == TopAbs_IN
    return g


if __name__ == "__main__":
    names = list(solids())
    res = {}
    with Pool(4) as p:
        for n in names:
            chunks = [(n, i, min(i + 8, len(XS))) for i in range(0, len(XS), 8)]
            res[n] = np.concatenate(p.map(column_block, chunks), 0)
            print(n, res[n].sum() * H ** 3, "mm3", flush=True)
    np.savez_compressed(HERE / "cad/vox1mm.npz", xs=XS, ys=YS, zs=ZS, **res)
