"""STEP -> named solids -> voxels at any spacing (used by research/sidepod_opt)."""
import numpy as np
from pathlib import Path


def solids_as_meshes(step_path):
    import trimesh
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRep import BRep_Tool
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS
    r = STEPControl_Reader(); assert r.ReadFile(str(step_path)) == 1; r.TransferRoots()
    tr = r.WS().TransferReader(); out = {}
    ex = TopExp_Explorer(r.OneShape(), TopAbs_SOLID)
    while ex.More():
        s = TopoDS.Solid(ex.Current()); e = tr.EntityFromShapeResult(s, 1)
        name = e.Name().ToCString() if e is not None else f"solid{len(out)}"
        BRepMesh_IncrementalMesh(s, 0.05, False, 0.2, True)
        V, F = [], []
        fx = TopExp_Explorer(s, TopAbs_FACE)
        while fx.More():
            f = TopoDS.Face(fx.Current()); loc = TopLoc_Location()
            t = BRep_Tool.Triangulation_s(f, loc)
            if t is not None:
                T = loc.Transformation(); b = len(V)
                for k in range(1, t.NbNodes() + 1):
                    p = t.Node(k).Transformed(T); V.append((p.X(), p.Y(), p.Z()))
                rev = f.Orientation().name == "TopAbs_REVERSED"
                for k in range(1, t.NbTriangles() + 1):
                    a, bb, c = t.Triangle(k).Get()
                    F.append((b + a - 1, b + c - 1, b + bb - 1) if rev else (b + a - 1, b + bb - 1, b + c - 1))
            fx.Next()
        out[name] = trimesh.Trimesh(np.array(V), np.array(F), process=True)
        ex.Next()
    return out


def voxelize(step_path, h, out_path, pad=2.0):
    import voxelize_fast as VF
    meshes = solids_as_meshes(step_path)
    lo = np.min([m.bounds[0] for m in meshes.values()], 0) - pad
    hi = np.max([m.bounds[1] for m in meshes.values()], 0) + pad
    lo[2] = 0.0
    xs = np.arange(lo[0], hi[0], h) + h / 2
    ym = max(abs(lo[1]), abs(hi[1]))
    ys = np.arange(-ym, ym, h) + h / 2                       # symmetric about y = 0
    zs = np.arange(0.0, hi[2], h) + h / 2
    VF.XS, VF.YS, VF.ZS = xs, ys, zs
    res = {n: VF.vox(m)[0] for n, m in meshes.items()}
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_path, xs=xs, ys=ys, zs=zs, **res)
