"""Adjoint accuracy test on the trial car (Part 3's known-answer marks: sign >= 9/10, r >= 0.9).

    python gate.py base   [np]            plain medium solve of the original, run dir kept = state A
    python gate.py bumps                  write the bump STLs (exact mesh, Gaussian normal moves)
    python gate.py bump <k> [np]          time bump k on the state-A mesh reshaped onto it (morph path)
    python gate.py adjoint [np]           ESI adjoint on the original: per-vertex dD/dn
    python gate.py variant <name> <site> <mm>  extra bump folder at another height (null, pairs)
    python gate.py judge                  measured vs predicted drag change per bump

Drag only (half car, N): race time and mass are left out on purpose. Every result goes to
gate/results/*.json. A bump whose run fell back to a fresh mesh (MORPH_FALLBACK) is not used.
"""
import json, os, shutil, sys, time
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
P2 = HERE.parents[1] / "part2-simulation"
sys.path.insert(0, str(P2)); sys.path.insert(0, str(HERE))
G = HERE / "gate"
R = Path(os.environ.get("GATE_RESULTS", HERE / "gate_results")); R.mkdir(parents=True, exist_ok=True)   # tracked in git
ADJ = HERE / "gate_results"       # the adjoint was solved here (one machine); other machines judge against it
ORIG0 = G / "original"            # exact CAD export (state A is solved on this)
ORIG = G / "original_rm"          # the same surface re-meshed to even 1 mm triangles: zero run, bumps, adjoint
DOMAIN = ((-0.005, 0.0, 0.0), (0.265, 0.045, 0.066))      # fixed for every car (trial car is 257 mm)
RES, ITERS_BASE, ITERS = "medium", 2000, 1000
BUMP_R_M, BUMP_A_M = 0.010, 0.001                           # Part 3: 10 mm radius, 1 mm height
# centres in the car frame (m): x from the nose, z up; y on the +y side. Front/attached vs rear/wake.
CENTRES = {"nose_top": (0.030, 0.000, 0.022), "nose_side": (0.040, 0.008, 0.019),
           "pod_front": (0.085, 0.030, 0.012), "pod_front_low": (0.095, 0.022, 0.004),
           "pod_rear": (0.160, 0.030, 0.012), "pod_rear_low": (0.165, 0.022, 0.004),
           "pod_rear_top": (0.150, 0.025, 0.026), "tail_side": (0.215, 0.010, 0.030)}


def kw(extra=None):
    import stopwatch as SW
    k = dict(SW.SEARCH, domain_reference_bounds=DOMAIN)
    k.update(extra or {})
    return k


def solve(folder, n_sub, iters, extra=None, keep=False):
    import stopwatch as SW
    from cfd_wrapper import run_half_car_cfd
    body = SW.body_stl(folder / "car_half.stl", folder / "_body_half.stl")
    k = kw(extra); k["max_iterations"] = iters
    t = time.time()
    half, health = run_half_car_cfd(str(body), n_subdomains=n_sub, extra_surfaces=SW.extra_surfaces(folder),
                                    keep_run_dir=keep, **k)
    return half, health, time.time() - t


def rec(half, health, secs, **more):
    d = {"D20_half_N": float(half.D20), "wall_s": round(secs, 1),
         "converged": bool(health.converged), "residual_p": health.residual_final,
         "force_osc": health.force_oscillation, "force_drift": getattr(health, "force_drift", None),
         "run_dir": str(getattr(health, "run_dir", "") or "")}
    d.update(more)
    return d


def cmd_base(n_sub):
    half, health, secs = solve(ORIG0, n_sub, ITERS_BASE, keep=True)
    run = latest_run_of(os.getpid())
    keep = G / "refA"                                         # state A lives outside Part 2's runs folder
    if run:
        if keep.exists():
            shutil.rmtree(keep)
        shutil.copytree(run, keep, ignore=shutil.ignore_patterns("processor*"))
    d = rec(half, health, secs, run_dir_kept=str(keep) if run else None,
            full_D20_N=float(half.to_full_car().D20), full_L20_N=float(half.to_full_car().L))
    (R / "base.json").write_text(json.dumps(d, indent=1, default=float))
    print(json.dumps(d, default=float)[:600], flush=True)


def ref_dir():
    """State A: the kept run folder of the base solve."""
    return json.loads((R / "base.json").read_text())["run_dir_kept"]


def bump_field(mesh, centre, r=BUMP_R_M, a=BUMP_A_M):
    """Outward normal move (m) per vertex: a Gaussian bump centred on the surface point nearest
    `centre`, faded to zero on the closed symmetry face (y = 0) so that face stays flat."""
    v, n = mesh.vertices, mesh.vertex_normals
    c = v[np.argmin(np.linalg.norm(v - np.asarray(centre), axis=1))]
    d2 = ((v - c) ** 2).sum(1)
    w = a * np.exp(-d2 / r ** 2)
    on_plane = (np.abs(v[:, 1]) < 1e-7) & (n[:, 1] < -0.9)
    w[on_plane] = 0.0
    w *= np.clip(v[:, 1] / 0.002, 0.0, 1.0) ** 2 if c[1] > 0.004 else 1.0
    return w, c


def cmd_remesh(target_m=1.0e-3):
    """Even ~1 mm triangles (the CAD has 150 mm ones on flat faces): a 10 mm bump and a per-vertex
    sensitivity both need them. Sharp edges kept (30 deg), surface held within 20 um."""
    import pymeshlab as ml
    import trimesh
    import cadio as CI
    m = trimesh.load(ORIG0 / "car_half.stl")
    ms = ml.MeshSet(); ms.add_mesh(ml.Mesh(m.vertices, m.faces))
    ms.meshing_isotropic_explicit_remeshing(iterations=6, targetlen=ml.PureValue(target_m), featuredeg=30.0,
                                            checksurfdist=True, maxsurfdist=ml.PureValue(2e-5))
    r = ms.current_mesh()
    t = trimesh.Trimesh(r.vertex_matrix(), r.face_matrix())
    if ORIG.exists():
        shutil.rmtree(ORIG)
    shutil.copytree(ORIG0, ORIG, ignore=shutil.ignore_patterns("_body_half.stl", "car_half.stl"))
    CI.write_ascii_named(t, ORIG / "car_half.stl", "car", m.volume, 0.002)
    print("remeshed", len(t.vertices), "vertices, volume error", (t.volume - m.volume) / m.volume, flush=True)


def cmd_bumps():
    import trimesh
    import cadio as CI
    if not ORIG.exists():
        cmd_remesh()
    base = trimesh.load(ORIG / "car_half.stl")
    out = {}
    for k, cen in CENTRES.items():
        w, c = bump_field(base, cen)
        m = base.copy()
        nv = base.vertices + base.vertex_normals * w[:, None]
        nv[np.abs(base.vertices[:, 1]) < 1e-9, 1] = 0.0        # the symmetry face stays exactly at y = 0
        m.vertices = nv
        dv_expect = float((w[m.faces].mean(1) * base.area_faces).sum())
        dv = m.volume - base.volume
        folder = G / f"bump_{k}"
        if folder.exists():
            shutil.rmtree(folder)
        shutil.copytree(ORIG, folder, ignore=shutil.ignore_patterns("_body_half.stl"))
        CI.write_ascii_named(m, folder / "car_half.stl", "car", base.volume + dv, 0.01)
        np.save(folder / "move_m.npy", w)
        out[k] = {"centre_on_surface_m": c.tolist(), "dV_mm3": dv * 1e9, "dV_expected_mm3": dv_expect * 1e9,
                  "moved_vertices": int((w > 1e-6).sum()), "max_move_mm": float(w.max() * 1e3)}
        print(k, json.dumps(out[k]), flush=True)
    (R / "bumps.json").write_text(json.dumps(out, indent=1))


def cmd_variant(name, centre_key, amp_mm):
    """An extra bump folder: a CENTRES site at another height (negative = dent). For the noise
    floor (tiny height), linearity and +/- pairs."""
    import trimesh
    import cadio as CI
    base = trimesh.load(ORIG / "car_half.stl")
    w, c = bump_field(base, CENTRES[centre_key], a=float(amp_mm) * 1e-3)
    m = base.copy()
    nv = base.vertices + base.vertex_normals * w[:, None]
    nv[np.abs(base.vertices[:, 1]) < 1e-9, 1] = 0.0
    m.vertices = nv
    folder = G / f"bump_{name}"
    if folder.exists():
        shutil.rmtree(folder)
    shutil.copytree(ORIG, folder, ignore=shutil.ignore_patterns("_body_half.stl"))
    CI.write_ascii_named(m, folder / "car_half.stl", "car", m.volume, 0.01)
    np.save(folder / "move_m.npy", w)
    meta = json.loads((R / "bumps.json").read_text())
    meta[name] = {"site": centre_key, "amp_mm": float(amp_mm), "dV_mm3": (m.volume - base.volume) * 1e9}
    (R / "bumps.json").write_text(json.dumps(meta, indent=1))
    print(name, meta[name], flush=True)


def cmd_bump(k, n_sub):
    ref = ref_dir()
    folder = G / f"bump_{k}"
    half, health, secs = solve(folder, n_sub, ITERS, extra={"morph_from": ref, "warm_from": ref}, keep=True)
    run = latest_run_of(os.getpid())
    fell_back = bool(run and (Path(run) / "MORPH_FALLBACK").exists())
    d = rec(half, health, secs, bump=k, morph_fallback=fell_back, run_dir_kept=run)
    (R / f"bump_{k}.json").write_text(json.dumps(d, indent=1, default=float))
    if run and not fell_back:
        shutil.rmtree(run, ignore_errors=True)             # keep the disk; the numbers are saved
    print(json.dumps(d, default=float), flush=True)


def cmd_reference_repeat(n_sub):
    """The ORIGINAL on the morph path from state A: the zero of every bump difference (and a noise point)."""
    ref = ref_dir()
    half, health, secs = solve(ORIG, n_sub, ITERS, extra={"morph_from": ref, "warm_from": ref}, keep=True)
    run = latest_run_of(os.getpid())
    d = rec(half, health, secs, morph_fallback=bool(run and (Path(run) / "MORPH_FALLBACK").exists()), run_dir_kept=run)
    (R / "zero.json").write_text(json.dumps(d, indent=1, default=float))
    if run:
        shutil.rmtree(run, ignore_errors=True)
    print(json.dumps(d, default=float), flush=True)


def cmd_adjoint(n_sub):
    import openfoam_adjoint as OA
    import stopwatch as SW
    import trimesh
    body = SW.body_stl(ORIG / "car_half.stl", ORIG / "_body_half.stl")
    cfg = OA.AdjointRunConfig(resolution=RES, n_subdomains=n_sub, extra_surfaces=SW.extra_surfaces(ORIG),
                              domain_reference_bounds=DOMAIN)
    t = time.time()
    s = OA.invoke_adjoint(str(body), str(P2 / "cfd_case_template"), cfg)      # kinematic dD_half/dn per vertex
    v = trimesh.load(body).vertices
    np.save(R / "adjoint_sens.npy", np.asarray(s)); np.save(R / "adjoint_verts.npy", v)
    (R / "adjoint.json").write_text(json.dumps({"wall_s": round(time.time() - t, 1), "n": int(len(s)),
                                                "rho": 1.225}, indent=1))
    print("adjoint done", len(s), round(time.time() - t), "s", flush=True)


def latest_run_of(pid):
    runs = sorted((P2 / "cfd_case_template/runs").glob(f"run_{pid}_*"), key=lambda p: p.stat().st_mtime)
    return str(runs[-1]) if runs else None


def adjoint_on_base(base):
    """The adjoint as saved is one value per STL triangle CORNER, each the value of the nearest
    CFD surface point (openfoam_adjoint.map_sensitivity_to_stl_vertices): kinematic dD_half/dn per
    unit AREA (ESI default, includeSurfaceArea false, as Part 3's known-answer check reads it).
    Per vertex: the mean of its corners (g) and its area (1/3 of its faces). On another machine
    whose re-meshed original differs, g is taken from the nearest vertex of the adjoint's mesh
    (adjoint_g.npy + adjoint_verts.npy)."""
    s = np.load(ADJ / "adjoint_sens.npy")
    vid = base.faces.reshape(-1)
    area = np.bincount(vid, weights=np.repeat(base.area_faces / 3, 3), minlength=len(base.vertices))
    if len(base.faces) * 3 == len(s) and np.allclose(base.vertices, np.load(ADJ / "adjoint_verts.npy")):
        g = np.bincount(vid, weights=s, minlength=len(base.vertices)) / np.bincount(vid, minlength=len(base.vertices))
        if not (ADJ / "adjoint_g.npy").exists():
            np.save(ADJ / "adjoint_g.npy", g)
        return g, area
    from scipy.spatial import cKDTree
    V = np.load(ADJ / "adjoint_verts.npy")
    d, i = cKDTree(V).query(base.vertices)
    if np.median(d) > 2e-4:
        raise SystemExit(f"this original differs from the adjoint's (median {np.median(d)*1e3:.2f} mm)")
    return np.load(ADJ / "adjoint_g.npy")[i], area


def cmd_judge():
    """Measured dD (bump - zero, morph path) vs adjoint prediction rho * sum(s dn)."""
    import trimesh
    zero = json.loads((R / "zero.json").read_text())["D20_half_N"]
    base_run = json.loads((R / "base.json").read_text())["D20_half_N"]
    base = trimesh.load(ORIG / "car_half.stl")
    g, area = adjoint_on_base(base)
    rows = []
    for p in sorted(R.glob("bump_*.json")):
        k = p.stem[5:]
        b = json.loads(p.read_text())
        dn = ((trimesh.load(G / f"bump_{k}" / "car_half.stl").vertices - base.vertices) * base.vertex_normals).sum(1)
        rows.append({"bump": k, "measured_mN": (b["D20_half_N"] - zero) * 1e3,
                     "predicted_mN": float(1.225 * (g * dn * area).sum()) * 1e3,
                     "dV_mm3": float((dn * area).sum() * 1e9),
                     "usable": bool(not b["morph_fallback"] and b["converged"])})
    use = [r for r in rows if r["usable"]]
    out = {"zero_minus_base_mN (one noise sample)": (zero - base_run) * 1e3, "rows": rows}
    if len(use) >= 3:
        m = np.array([r["measured_mN"] for r in use]); pr = np.array([r["predicted_mN"] for r in use])
        rr = float(np.corrcoef(m, pr)[0, 1]); sg = (np.sign(m) == np.sign(pr))
        out.update(pearson_r=rr, signs=f"{int(sg.sum())}/{len(use)}", slope_measured_per_predicted=float((m @ pr) / (pr @ pr)),
                   passed=bool(rr >= 0.9 and sg.mean() >= 0.9))
    (R / "judge.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    c = sys.argv[1]
    npar = lambda i: int(sys.argv[i]) if len(sys.argv) > i else 2
    if c == "base":
        cmd_base(npar(2))
    elif c == "remesh":
        cmd_remesh()
    elif c == "bumps":
        cmd_bumps()
    elif c == "bump":
        cmd_bump(sys.argv[2], npar(3))
    elif c == "zero":
        cmd_reference_repeat(npar(2))
    elif c == "adjoint":
        cmd_adjoint(npar(2))
    elif c == "variant":
        cmd_variant(sys.argv[2], sys.argv[3], sys.argv[4])
    elif c == "judge":
        cmd_judge()
