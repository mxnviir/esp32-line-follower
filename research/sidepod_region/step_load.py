"""Read the team's STEP, tessellate every solid, write STLs (mm, file frame) and a summary."""
import json, sys
from pathlib import Path
import numpy as np
from OCP.STEPControl import STEPControl_Reader
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRep import BRep_Tool
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.XSControl import XSControl_WorkSession
import trimesh

HERE = Path(__file__).resolve().parent
r = STEPControl_Reader()
assert r.ReadFile(str(HERE / "cad/trial_car.step")) == 1
r.TransferRoots()
shape = r.OneShape()
ws = r.WS()
tr = ws.TransferReader()
out = {}
ex = TopExp_Explorer(shape, TopAbs_SOLID)
i = 0
while ex.More():
    s = TopoDS.Solid(ex.Current())
    ent = tr.EntityFromShapeResult(s, 1)
    name = ent.Name().ToCString() if ent is not None and ent.Name() is not None else f"solid{i}"
    BRepMesh_IncrementalMesh(s, 0.05, False, 0.2, True)
    V, F = [], []
    fx = TopExp_Explorer(s, TopAbs_FACE)
    while fx.More():
        f = TopoDS.Face(fx.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(f, loc)
        if tri is not None:
            T = loc.Transformation()
            base = len(V)
            for k in range(1, tri.NbNodes() + 1):
                p = tri.Node(k).Transformed(T)
                V.append((p.X(), p.Y(), p.Z()))
            rev = f.Orientation().name == "TopAbs_REVERSED"
            for k in range(1, tri.NbTriangles() + 1):
                a, b, c = tri.Triangle(k).Get()
                F.append((base + a - 1, base + c - 1, base + b - 1) if rev else (base + a - 1, base + b - 1, base + c - 1))
        fx.Next()
    m = trimesh.Trimesh(np.array(V), np.array(F), process=True)
    m.merge_vertices()
    p = GProp_GProps(); BRepGProp.VolumeProperties_s(s, p)
    c = p.CentreOfMass()
    m.export(HERE / f"cad/{name}.stl")
    out[name] = dict(bbox_min=m.bounds[0].round(3).tolist(), bbox_max=m.bounds[1].round(3).tolist(),
                     volume_mm3=round(p.Mass(), 2), com=[round(c.X(), 3), round(c.Y(), 3), round(c.Z(), 3)],
                     watertight=bool(m.is_watertight), tris=len(m.faces))
    i += 1
    ex.Next()
(HERE / "cad/summary.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
