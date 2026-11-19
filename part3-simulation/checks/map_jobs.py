"""Queue jobs for one start car's compass map (run on Oracle or in Actions, never on the PC).

    python map_jobs.py base  <start.json> <ref> > batch.json      # the start car, saves its case
    python map_jobs.py modes <start.json> <ref> <case_url> <sha256> > batch.json   # its 2 x NMODES mode cars

start.json: {"name": "chain1", "layout": {"W", "x_front", "d_halo"}, "edits": [...carve.carve edits]}
Every car is the SIZED car (no --skin-mm), half car, fine, 4-core hierarchical, 1000 iterations, legality
gated, carved through carve.carve from its recipe (--carve-json). Mode k is the start car's edits plus one
bump of +-A at centre k on the START CAR's own surface (car_modes.centres, farthest-point order, NMODES 96
so every point is within one radius). A job id is the hash of its recipe: the same car is never timed twice.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "part5-simulation"))

REPO = "anasssssssss1/stem-racing-compute"
CFD = {"decompose": "hierarchical", "layer_overrides": {"nSurfaceLayers": 0}}


def args(carve: dict, cfd: dict) -> list:
    """carve: farm's recipe (layout, edits, and floor when it has a tunnel); the floor goes as --body-json."""
    floor = (["--body-json", json.dumps(carve["floor"], sort_keys=True)] if carve.get("floor") else [])
    return ["--carve-json", json.dumps({"layout": carve["layout"], "edits": carve["edits"]}, sort_keys=True), *floor, "--support", "beam", "--cfd", "--cfd-if-legal",
            "--res", "fine", "--np", "4", "--cfd-iters", "1000", "--keep-runs",
            "--cfd-json", json.dumps(cfd, sort_keys=True)]


def job(stage: str, ref: str, carve: dict, cfd: dict, fetch: list, save_case: bool, prio: int) -> dict:
    a = args(carve, cfd)
    h = hashlib.sha256(json.dumps([ref, carve], sort_keys=True).encode()).hexdigest()[:20]   # = farm.rid: one car, one id
    return {"id": f"p5-{h}", "stage": stage, "prio": prio,
            "recipe": {"repo": REPO, "ref": ref, "args": a, "fetch": fetch, "save_case": save_case}}


def centres_mm(start: dict) -> list:
    import paths  # noqa: F401  (puts the other parts on the path)
    import carve
    import car_modes as cm
    g, rep = carve.carve(start["layout"], start["edits"])
    if any(r.get("status") != "ok" for r in rep):
        raise SystemExit(f"start car refused: {rep}")
    _, V, N = cm.surface(g)
    return [[round(float(v), 4) for v in c] for c in cm.centres(V, N) * 1e3]



def tunnelled_mm(g, floor: dict):
    """The carved field (mm) with the start's tunnel cut as build() cuts it (param_body._field_tunnel_phi),
    plus the grid X, Y, Z (mm). Carving acts on the untunnelled surface; the tunnel is cut after."""
    import numpy as np
    import param_body as pb
    import unified_phi as up
    r, d = g.region, up.GRID_SPACING_M
    xs, ys, zs = ((r.origin_m[i] + np.arange(r.shape[i]) * d) * 1e3 for i in range(3))
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    field = np.asarray(g.phi.grid, float) * 1e3
    bp = pb.BodyParams.from_dict(floor)
    if bp.ft_h > 0:
        field = np.maximum(field, -pb._field_tunnel_phi(bp, field, X, Y, Z))
    return field, X, Y, Z


def slot_centres(start: dict, centres: list) -> list:
    """Indices of mode centres on the underside inside the tunnel slot footprint (|y| < ft_w,
    ft_x0..ft_x1, within ft_h + 1 mm of the column's lowest solid)."""
    import numpy as np
    import param_body as pb
    import paths  # noqa: F401
    import carve
    bp = pb.BodyParams.from_dict(start.get("floor", {}))
    if bp.ft_h <= 0:
        return []
    g, _ = carve.carve(start["layout"], start["edits"])
    field, X, Y, Z = tunnelled_mm(g, {})
    zb = np.where(field < 0, Z, 1e9).min(axis=2)
    xs, ys = X[:, 0, 0], Y[0, :, 0]
    out = []
    for k, (x, y, z) in enumerate(centres):
        i, j = int(np.abs(xs - x).argmin()), int(np.abs(ys - y).argmin())
        if abs(y) < bp.ft_w and bp.ft_x0 < x < bp.ft_x1 and z <= zb[i, j] + bp.ft_h + 1.0:
            out.append(k)
    return out


def side_moves(g, centre_mm, sigma_mm: float, amp_mm: float) -> int:
    """Cheap screen for one side of a bump mode on the car g (no carve): the cells this bump's move
    could flip. 0 means the side cannot move (dead); > 0 means it may (the wall guard and clean-up can
    still hold it: the field hash after timing is the exact word, farm.tick reads it).
    Speed as carve.carve's exact_speed cut (phi_updater): each cell within 4 cells of the surface takes
    the speed of its nearest half-surface vertex, either y half; the planned move of the fastest surface
    is |amp|, so a cell's move is its speed in mm. A cell may flip if it is on the moving side, its
    distance to the surface is under 2x its move (margin: a live side must never be screened dead), and
    no rule mask holds it: hard_mask_air (growing; it holds the one-cell border seal) or hard_mask_solid
    (thinning). Growing also cannot reach the cells beside the border seal: solid there would touch the
    seal (the reviewer measured mode 9 +1 on the start block: 54 such cells, carve flipped 0)."""
    import numpy as np
    import carve
    import unified_phi as up
    from scipy.spatial import cKDTree
    V = np.asarray(up.extract_half_surface(g).vertices, float)
    s = carve._speed_mm(V * 1e3, {"bumps": [{"c_mm": list(centre_mm), "amp_mm": amp_mm, "sigma_mm": sigma_mm}]})
    phi = np.asarray(g.phi.grid, float)
    d = up.GRID_SPACING_M
    band = np.abs(phi) < 4.0 * d
    o = np.asarray(g.phi.bv.origin_m, float)
    both = np.vstack([V, V * np.array([1.0, -1.0, 1.0])])
    move = np.zeros(phi.shape)
    move[band] = np.concatenate([s, s])[cKDTree(both).query(o + np.argwhere(band) * d)[1]] * 1e-3   # m, signed
    if amp_mm > 0:
        side = (phi > 0) & (phi < 2.0 * move) & ~g.phi.hard_mask_air
        side[1, :, :] = side[-2, :, :] = side[:, 1, :] = side[:, -2, :] = side[:, :, 1] = side[:, :, -2] = False
    else:
        side = (phi < 0) & (-phi < -2.0 * move) & ~g.phi.hard_mask_solid
    return int(side.sum())


def main(argv):
    kind, start, ref = argv[0], json.loads(Path(argv[1]).read_text()), argv[2]
    assert len(ref) == 40, "ref must be a full commit SHA"
    import farm
    start = farm.with_floor(start)                         # the start's tunnel (ft_h 3 unless it names its own)
    fl = {"floor": start["floor"]} if start["floor"].get("ft_h", 0.0) > 0 else {}
    stage = f"p3-map-{start['name']}"
    base = {"layout": start["layout"], "edits": start["edits"]}
    base.update(fl)
    if kind == "base":
        jobs = [job(stage, ref, base, CFD, [], True, 8)]
    else:
        url, sha = argv[3], argv[4]
        cfd = {**CFD, "morph_from": "/tmp/base", "warm_from": "/tmp/base"}
        a_mm, r_mm = float(os.environ.get("P3_MODE_A_MM", "1")), float(os.environ.get("P3_MODE_R_MM", "10"))
        jobs = []
        for k, c in enumerate(centres_mm(start)):
            for s in (1.0, -1.0):
                edits = start["edits"] + [{"bumps": [{"c_mm": c, "amp_mm": s * a_mm, "sigma_mm": r_mm}], "unit": False}]
                j = job(stage, ref, {"layout": start["layout"], "edits": edits, **fl}, cfd,
                        [{"url": url, "sha256": sha, "to": "/tmp/base"}], False, 7)
                j["mode"] = f"m{k}{'+' if s > 0 else '-'}"
                jobs.append(j)
    print(json.dumps({"batch": {"id": f"{stage}-{kind}", "label": f"Part 3 compass map {start['name']}: {kind}",
                                "stage": stage, "cars": len(jobs)}, "jobs": jobs}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
