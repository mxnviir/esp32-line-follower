"""The air volume around the car as a STEP solid, for SimScale's standard (OpenFOAM) solver.

The same idea as the team's Fusion add-in (OpenCFD_fusion_addin.py): a half wind tunnel, the car cut
out of it with a solid Boolean, the result written as STEP, every face labelled by where it is.
Here it is done with OpenCASCADE (the kernel this repo already uses to read the team's STEP):

  car body (body_full.stl, the whole car, so it crosses the symmetry plane cleanly) and the +y wheels
  -> sewn into solids -> cut from the box  x [-3 L, +8 L], y [0, 5 W], z [0, 5 H]  (Part 2's tunnel)
  -> faces named inlet / outlet / symmetry / side / top / ground (planes of the box) and wheelF /
     wheelR (faces of the wheel solids); every other face is the car
  -> STEP in mm, with the names written on the faces.

    python simscale_step_domain.py <car_folder> [--out <car_folder>/domain.step]
"""
import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import trimesh

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

ROAD_GAP_MM = 0.15           # the team's choice: the road 0.15 mm BELOW the wheels' lowest point (no contact)
SINK_MM = -ROAD_GAP_MM       # kept for callers: how far the wheels go into the road (negative = a gap)
DOMAIN_MM = ((-771.0, 0.0, 0.0), (2314.0, 192.0, 245.0))   # Part 2's half tunnel for this car


def stl_solid(mesh_mm):
    """A closed triangle mesh (mm) -> an OpenCASCADE solid (one planar face per triangle)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeSolid
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.StlAPI import StlAPI_Reader
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS, TopoDS_Shape
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "m.stl"
        mesh_mm.export(p)
        shape = TopoDS_Shape()
        StlAPI_Reader().Read(shape, str(p))
    sew = BRepBuilderAPI_Sewing(1e-4)
    sew.Add(shape); sew.Perform()
    ex = TopExp_Explorer(sew.SewedShape(), TopAbs_SHELL)
    shell = TopoDS.Shell(ex.Current())
    solid = BRepBuilderAPI_MakeSolid(shell).Solid()
    fix = ShapeFix_Solid(solid); fix.Perform()                      # outward orientation
    return fix.Solid()


def volume(shape):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(shape, g)
    return g.Mass()


def build(folder: Path, out: Path, domain=DOMAIN_MM):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    t0 = time.time()
    folder = Path(folder)
    body = trimesh.load(folder / "body_full.stl"); body.apply_scale(1e3)
    wheels = {}
    for w in ("wheelF", "wheelR"):
        m = trimesh.load(folder / f"{w}.stl"); m.apply_scale(1e3); wheels[w] = m
    car_s = stl_solid(body)
    wheel_s = {w: stl_solid(m) for w, m in wheels.items()}
    (x0, y0, _), (x1, y1, z1) = domain
    z0 = min(float(m.bounds[0, 2]) for m in wheels.values()) - ROAD_GAP_MM   # e.g. wheels at -0.3 -> road at -0.45
    domain = ((x0, y0, z0), (x1, y1, z1))
    box = BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape()
    cut = BRepAlgoAPI_Cut()
    from OCP.OCP.collections import List_TopoDS_Shape
    args, tools = List_TopoDS_Shape(), List_TopoDS_Shape()
    args.Append(box)
    for s_ in [car_s, *wheel_s.values()]:
        tools.Append(s_)
    cut.SetArguments(args); cut.SetTools(tools)
    cut.SetFuzzyValue(1e-5); cut.Build()
    assert cut.IsDone(), "Boolean failed"
    fluid = cut.Shape()
    v_box = (x1 - x0) * (y1 - y0) * (z1 - z0)
    removed = v_box - volume(fluid)
    expect = 0.5 * body.volume + sum(m.volume for m in wheels.values())
    labels = label_faces(fluid, cut, wheel_s, domain)
    write_step(fluid, labels, out)
    counts = {}
    for n in labels.values():
        counts[n] = counts.get(n, 0) + 1
    return {"step": str(out), "removed_mm3": removed, "expected_mm3": expect,
            "removed_share": removed / expect, "faces": counts, "secs": round(time.time() - t0)}


def label_faces(fluid, cut, wheel_s, domain):
    """{face: name} for the tunnel planes and the wheel faces; the rest (unnamed) is the car."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    (x0, y0, z0), (x1, y1, z1) = domain
    tol = 1e-3
    labels = {}
    # wheel faces: the result faces that come from each wheel solid (unchanged or modified)
    wheel_faces = []
    for name, ws in wheel_s.items():
        ex = TopExp_Explorer(ws, TopAbs_FACE)
        while ex.More():
            f = ex.Current()
            mod = cut.Modified(f)
            if mod.Size() if hasattr(mod, 'Size') else len(mod):
                for g in mod:
                    wheel_faces.append((g, name))
            elif not cut.IsDeleted(f):
                wheel_faces.append((f, name))
            ex.Next()
    ex = TopExp_Explorer(fluid, TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face(ex.Current())
        name = None
        s = BRepAdaptor_Surface(f)
        if s.GetType() == GeomAbs_Plane:
            pl = s.Plane(); n = pl.Axis().Direction(); o = pl.Location()
            nv = np.array([n.X(), n.Y(), n.Z()]); ov = np.array([o.X(), o.Y(), o.Z()])
            for nm, ax, val in (("inlet", 0, x0), ("outlet", 0, x1), ("symmetry", 1, y0), ("side", 1, y1),
                                ("ground", 2, z0), ("top", 2, z1)):
                if abs(abs(nv[ax]) - 1) < 1e-9 and abs(ov[ax] - val) < tol:
                    name = nm
                    break
        if name is None:
            for g, wn in wheel_faces:
                if f.IsSame(g):
                    name = wn
                    break
        if name is not None:
            labels[f] = name
        ex.Next()
    return labels


def write_step(fluid, labels, out: Path):
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Interface import Interface_Static
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_AsIs
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFDoc import XCAFDoc_DocumentTool
    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    lab = st.AddShape(fluid, False)
    TDataStd_Name.Set_s(lab, TCollection_ExtendedString("fluid"))
    for f, name in labels.items():
        sub = st.AddSubShape(lab, f)
        if not sub.IsNull():
            TDataStd_Name.Set_s(sub, TCollection_ExtendedString(name))
    from OCP.STEPCAFControl import STEPCAFControl_Controller
    STEPCAFControl_Controller.Init_s()                              # registers the write.stepcaf.* options
    assert Interface_Static.SetIVal_s("write.stepcaf.subshapes.name", 1), "subshape-name option missing"
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    w = STEPCAFControl_Writer()
    w.SetNameMode(True)
    assert w.Transfer(doc, STEPControl_AsIs), "STEP transfer failed"
    assert w.Write(str(out)) == IFSelect_RetDone, "STEP write failed"


def to_car_frame(shape, x_nose_mm):
    """STEP frame -> car frame (mm): x from the nose tip (x' = x_nose - X), flow +x. A mirror."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf
    tr = gp_Trsf(); tr.SetMirror(gp_Ax2(gp_Pnt(x_nose_mm / 2.0, 0, 0), gp_Dir(1, 0, 0)))
    return BRepBuilderAPI_Transform(shape, tr, True).Shape()


def build_exact(out: Path, spec=None, domain=DOMAIN_MM):
    """The team's car exactly as in its STEP (no triangles): body and the +y wheels cut from the tunnel."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.OCP.collections import List_TopoDS_Shape
    from OCP.gp import gp_Pnt
    import cadio as CI
    from geometry import CarSpec
    t0 = time.time()
    s = spec or CarSpec()
    solids = CI.read_step_solids(s.step)
    body = to_car_frame(CI.outer_solid(solids[s.body_solid]), s.x_nose_mm)
    wheel_s = {"wheelF": to_car_frame(solids["wheel_fl"], s.x_nose_mm), "wheelR": to_car_frame(solids["wheel_rl"], s.x_nose_mm)}
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    zmin = []
    for w in wheel_s.values():
        b = Bnd_Box(); BRepBndLib.Add_s(w, b, False); zmin.append(b.CornerMin().Z())
    # The team's choice: car and wheels exactly as in the STEP; the road ROAD_GAP_MM under the wheels' lowest point
    drop = 0.0
    (x0, y0, _), (x1, y1, z1) = domain
    z0 = min(zmin) - ROAD_GAP_MM
    domain = ((x0, y0, z0), (x1, y1, z1))
    box = BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape()
    cut = BRepAlgoAPI_Cut()
    args, tools = List_TopoDS_Shape(), List_TopoDS_Shape()
    args.Append(box)
    for sh in [body, *wheel_s.values()]:
        tools.Append(sh)
    cut.SetArguments(args); cut.SetTools(tools); cut.SetFuzzyValue(1e-5); cut.Build()
    assert cut.IsDone(), "Boolean failed"
    fluid = cut.Shape()
    removed = (x1 - x0) * (y1 - y0) * (z1 - z0) - volume(fluid)
    expect = 0.5 * volume(body) + sum(volume(w) for w in wheel_s.values())
    labels = label_faces(fluid, cut, wheel_s, domain)
    write_step(fluid, labels, out)
    counts = {}
    for n in labels.values():
        counts[n] = counts.get(n, 0) + 1
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    nf = 0; ex = TopExp_Explorer(fluid, TopAbs_FACE)
    while ex.More():
        nf += 1; ex.Next()
    return {"step": str(out), "removed_mm3": removed, "expected_mm3": expect, "removed_share": removed / expect,
            "faces_total": nf, "named": counts, "ground_mm": z0, "wheel_bottom_mm": min(zmin), "road_gap_mm": ROAD_GAP_MM, "secs": round(time.time() - t0)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="car folder (faceted car) or 'exact' (the team's STEP as is)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if a.folder == "exact":
        print(json.dumps(build_exact(Path(a.out or "domain_exact.step")), default=float))
        return
    out = Path(a.out) if a.out else Path(a.folder) / "domain.step"
    print(json.dumps(build(Path(a.folder), out), default=float))


if __name__ == "__main__":
    main()
