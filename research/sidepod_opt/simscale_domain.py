"""The external-flow domain for SimScale's standard (OpenFOAM) incompressible solver.

SimScale's API cannot extract an external flow volume, so we make it: the half wind tunnel of
Part 2 (x from -3 L to +8 L around the car, y from the symmetry plane to 5 widths, z from the
track to 5 heights) minus the car and wheels, as ONE closed STL whose triangles are grouped in named
solids: inlet, outlet, symmetry, side, top, ground, car, wheelF, wheelR. Imported with sewing, each
group should become a face set the boundary conditions can be put on.

    python simscale_domain.py <car_folder> [--out <car_folder>/domain.stl]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import trimesh

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Part 2's domain for this car (openfoam_case.domain_box of the trial car), metres, car frame
DOMAIN = ((-0.771, 0.0, 0.0), (2.314, 0.192, 0.245))
GROUPS = ("inlet", "outlet", "symmetry", "side", "ground", "top", "car", "wheelF", "wheelR")


def mirrored(m):
    w = m.copy()
    w.vertices = w.vertices * np.array([1.0, -1.0, 1.0])
    w.invert()
    return w


def build(folder: Path, domain=DOMAIN):
    import manifold3d as mf
    import cadio as CI
    folder = Path(folder)
    body = trimesh.load(folder / "body_full.stl")
    wf, wr = trimesh.load(folder / "wheelF.stl"), trimesh.load(folder / "wheelR.stl")
    inputs = {"car": [body], "wheelF": [wf, mirrored(wf)], "wheelR": [wr, mirrored(wr)]}
    (x0, y0, z0), (x1, y1, z1) = domain
    box = mf.Manifold.cube([x1 - x0, y1 - y0, z1 - z0]).translate([x0, y0, z0]).as_original()
    owner = {box.original_id(): "box"}
    fluid = box
    for name, ms in inputs.items():
        for m in ms:
            s = CI.to_manifold(m).as_original()
            owner[s.original_id()] = name
            fluid = fluid - s
    assert fluid.status() == mf.Error.NoError and fluid.volume() > 0
    g = fluid.to_mesh()
    V = np.asarray(g.vert_properties)[:, :3].astype(np.float64)
    T = np.asarray(g.tri_verts)
    F = trimesh.Trimesh(V, T, process=False)
    label = np.full(len(T), "", dtype=object)
    run_idx = np.asarray(g.run_index) // 3                       # triangle ranges per input mesh
    for k, oid in enumerate(np.asarray(g.run_original_id)):
        label[run_idx[k]:run_idx[k + 1]] = owner.get(int(oid), "")
    # the tunnel's own faces by plane
    c = V[T].mean(1)
    on_box = label == "box"
    for g_, axis, val in (("inlet", 0, x0), ("outlet", 0, x1), ("symmetry", 1, y0), ("side", 1, y1),
                          ("ground", 2, z0), ("top", 2, z1)):
        label[on_box & np.isclose(c[:, axis], val, atol=1e-7)] = g_
    assert not (label == "box").any() and not (label == "").any(), "unlabelled triangles"
    # clean as a CAD importer will see it (weld, drop slivers), then carry the labels over by position
    from scipy.spatial import cKDTree
    C = CI.clean(trimesh.Trimesh(F.vertices * 1e3, F.faces, process=False))   # cadio works in mm
    w = trimesh.Trimesh(C.vertices * 1e-3, C.faces, process=False)
    assert w.is_watertight, "cleaned domain not watertight"
    _, j = cKDTree(c).query(w.triangles_center)
    F, label = w, label[j]
    counts = {g_: int((label == g_).sum()) for g_ in GROUPS}
    return F, label, counts


def write_stl(F, label, out: Path):
    lines = []
    for g in GROUPS:
        idx = np.nonzero(label == g)[0]
        lines.append(f"solid {g}")
        for i in idx:
            t = F.vertices[F.faces[i]]; nn = F.face_normals[i]
            lines.append(f"facet normal {nn[0]:.9e} {nn[1]:.9e} {nn[2]:.9e}\n outer loop")
            lines += [f"  vertex {p[0]:.9e} {p[1]:.9e} {p[2]:.9e}" for p in t]
            lines.append(" endloop\nendfacet")
        lines.append(f"endsolid {g}")
    out.write_text("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder"); ap.add_argument("--out", default=None)
    a = ap.parse_args()
    F, label, counts = build(Path(a.folder))
    out = Path(a.out) if a.out else Path(a.folder) / "domain.stl"
    write_stl(F, label, out)
    print(json.dumps({"domain": str(out), "watertight": bool(F.is_watertight), "fluid_volume_m3": float(F.volume),
                      "triangles": counts}))


if __name__ == "__main__":
    main()
