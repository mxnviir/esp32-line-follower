"""Evaluators: car folder (or milled body) -> whole-car D20, L20 (N). One interface, four backends.

    ev.submit(cases)   cases: list of {"id", "folder", "body" (1 mm bool, optional), "fidelity"}
    ev.collect()       -> {id: {"D20_N", "L20_N", "ok", "info"}} for every finished case

Backends
  openfoam    Part 2's OpenFOAM pipeline (snappyHexMesh + simpleFoam kOmegaSST, rolling road,
              rotating wheels) on this machine. Needs OpenFOAM v2412 (`openfoam2412-default`).
  actions     the same OpenFOAM job, as a matrix on GitHub Actions (.github/workflows/sidepod_eval.yml),
              any number of accounts. submit() commits the batch and dispatches; collect() downloads.
  simscale    SimScale through its API (simscale_sdk), cloned from a template simulation the team
              sets up once in the web UI (BCs, rolling road, rotating wheels, force plot). No adjoint;
              good for derivative-free methods. Needs SIMSCALE_API_KEY and api.simscale.com.
  adjoint     OpenFOAM adjoint (Part 2's openfoam_adjoint, ESI adjointOptimisationFoam) returning
              per-vertex drag sensitivities; turned into a race-time gradient on the design field.
              GATED: unusable until it passes campaign.gate_adjoint (it failed Part 3's wing test).

Only full-Reynolds RANS solvers (OpenFOAM, SimScale): the low-Re lattice-Boltzmann tunnel and its
differentiable copy are gone (they ranked sidepods wrongly). Fidelity labels: "medium", "fine", "resolved" (OpenFOAM mesh levels of Part 2).
Frozen states: a run can be warm-started from a frozen reference flow of THIS car (states A and B,
made once by `campaign.py make-refs`). Small changes reshape the reference mesh (morph_from: the
low-noise path, 0.09 ms in Part 2); big organic changes get a fresh mesh started from the
reference flow (warm_from). Both states are run and averaged, as Part 2's method A.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
RHO = 1.225                        # kg/m3, Part 2
REPO = HERE.parents[1]
P2 = REPO / "part2-simulation"


# ---------------------------------------------------------------------- base
class Evaluator:
    name = "base"

    def __init__(self):
        self._done = {}

    def submit(self, cases):
        raise NotImplementedError

    def collect(self):
        out, self._done = self._done, {}
        return out


# ---------------------------------------------------------------------- OpenFOAM (local)
class OpenFOAMEvaluator(Evaluator):
    """Part 2's pipeline on this machine. states: ("A", "B") frozen references of THIS car
    (campaign.py make-refs), or () for one plain solve."""
    name = "openfoam"

    def __init__(self, refs: dict | None = None, n_subdomains=2, iters=1000, cfd=None, mode="auto"):
        super().__init__()
        self.refs, self.np, self.iters, self.cfd, self.mode = refs or {}, n_subdomains, iters, cfd or {}, mode

    def submit(self, cases):
        for c in cases:
            self._done[c["id"]] = run_openfoam_case(Path(c["folder"]), c.get("fidelity", "medium"), self.refs,
                                                    self.np, self.iters, self.cfd, self.mode)


def run_openfoam_case(folder: Path, res: str, refs: dict, n_sub=2, iters=1000, cfd=None, mode="auto") -> dict:
    """One car, every frozen state, averaged (Part 2 method A). mode: "morph" (reshape the
    reference mesh: lowest noise, small changes only), "warm" (fresh mesh, flow mapped from the
    reference), "auto" (morph, falling back to warm when the reshaped mesh fails its checks),
    "plain" (fresh mesh, cold start)."""
    sys.path.insert(0, str(P2))
    from cfd_wrapper import run_half_car_cfd
    import stopwatch as SW
    body = SW.body_stl(folder / "car_half.stl", folder / "_body_half.stl")
    kw = dict(SW.SEARCH, **(cfd or {}))
    kw.update(resolution=res, max_iterations=int(iters))
    per = {}
    states = list(refs) if (refs and mode != "plain") else [None]
    for s in states:
        k2 = dict(kw)
        if s:
            if mode in ("morph", "auto"):
                k2.update(morph_from=refs[s], warm_from=refs[s])
            else:
                k2.update(warm_from=refs[s])
        try:
            half, health = run_half_car_cfd(str(body), n_subdomains=n_sub, extra_surfaces=SW.extra_surfaces(folder), **k2)
            full = half.to_full_car()
            per[s or "plain"] = {"D20_N": full.D20, "L20_N": full.L, "converged": bool(health.converged),
                                 "residual_p": health.residual_final, "force_osc": health.force_oscillation}
        except Exception as e:                                    # a failed case is a result, not a crash
            per[s or "plain"] = {"error": repr(e)[:400]}
    good = [v for v in per.values() if "D20_N" in v]
    if not good:
        return {"D20_N": None, "L20_N": None, "ok": False, "info": per}
    return {"D20_N": float(np.mean([v["D20_N"] for v in good])), "L20_N": float(np.mean([v["L20_N"] for v in good])),
            "ok": all(v.get("converged") for v in good) and len(good) == len(per),
            "info": {"by_state": per, "state_spread_N": float(np.ptp([v["D20_N"] for v in good])) if len(good) > 1 else 0.0}}


# ---------------------------------------------------------------------- OpenFOAM on GitHub Actions
class ActionsEvaluator(Evaluator):
    """Writes the batch into jobs/<campaign>/<batch>/ (car folders + batch.json), commits it to
    `branch`, and dispatches .github/workflows/sidepod_eval.yml on each repo in `repos` (round
    robin, for several accounts). collect() downloads finished runs' `sidepod-results-*` artifacts.
    dry_run=True only writes the batch (for checking, or for dispatching by hand)."""
    name = "actions"

    def __init__(self, jobs_dir: Path, repos: list, branch="sidepod-jobs", res="medium", dry_run=False, per_job=1):
        super().__init__()
        self.jobs, self.repos, self.branch, self.res, self.dry, self.per_job = Path(jobs_dir), repos, branch, res, dry_run, per_job
        self.pending = {}                                         # batch -> {"repo", "ids", "dispatched"}
        self.state_file = self.jobs / "actions_state.json"
        if self.state_file.exists():
            self.pending = json.loads(self.state_file.read_text())

    def submit(self, cases):
        if not cases:
            return
        batch = time.strftime("b%Y%m%d-%H%M%S")
        bdir = self.jobs / batch
        bdir.mkdir(parents=True, exist_ok=True)
        import shutil
        ids = []
        for c in cases:
            dst = bdir / c["id"]
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(c["folder"], dst, ignore=shutil.ignore_patterns("*_raw.stl", "body_full.stl", "_body_half.stl"))
            ids.append(c["id"])
        groups = [ids[i:i + self.per_job] for i in range(0, len(ids), self.per_job)]
        (bdir / "batch.json").write_text(json.dumps({"res": self.res, "groups": groups}, indent=1))
        repo = self.repos[len(self.pending) % len(self.repos)] if self.repos else None
        self.pending[batch] = {"repo": repo, "ids": ids, "dispatched": False}
        if not self.dry and repo:
            rel = bdir.relative_to(REPO)
            _sh(["git", "add", str(bdir)], REPO)
            _sh(["git", "commit", "-q", "-m", f"sidepod jobs {batch}"], REPO)
            _sh(["git", "push", "-q", "origin", f"HEAD:{self.branch}"], REPO)
            _sh(["gh", "workflow", "run", "sidepod_eval.yml", "-R", repo, "--ref", self.branch,
                 "-f", f"batch={rel}", "-f", f"res={self.res}"], REPO)
            self.pending[batch]["dispatched"] = True
        self._save()

    def collect(self):
        for batch, p in list(self.pending.items()):
            if self.dry or not p["repo"]:
                rdir = self.jobs / batch / "results"              # results dropped in by hand
            else:
                rdir = self.jobs / batch / "results"
                runs = json.loads(_sh(["gh", "run", "list", "-R", p["repo"], "-w", "sidepod_eval.yml", "--json",
                                       "databaseId,status,conclusion,displayTitle", "-L", "50"], REPO) or "[]")
                for r in runs:
                    if batch in r["displayTitle"] and r["status"] == "completed":
                        _sh(["gh", "run", "download", str(r["databaseId"]), "-R", p["repo"], "-p", "sidepod-results-*",
                             "-D", str(rdir)], REPO)
            for f in rdir.rglob("*.json") if rdir.exists() else []:
                d = json.loads(f.read_text())
                if d.get("id") in p["ids"]:
                    self._done[d["id"]] = d
            if all(i in self._done for i in p["ids"]):
                self.pending.pop(batch)
        self._save()
        return super().collect()

    def _save(self):
        self.jobs.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.pending, indent=1))


def _sh(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"{' '.join(cmd)}: {r.stderr[-500:]}")
    return r.stdout


# ---------------------------------------------------------------------- SimScale
class SimScaleEvaluator(Evaluator):
    """SimScale via its Python SDK (pip install simscale-sdk). Set up ONE template simulation in the
    web UI on the original car (imported as the same named STL solids: car, wheelF, wheelR, ...):
    rolling road, rotating wheels, k-omega SST, a 'Forces and moments' result control on the car + wheels.
    Each design: upload its STLs, import, clone the template with every face reference re-mapped
    BY SOLID NAME onto the new geometry, mesh, run, read the force plot.

    Calls checked against the SDK source (github.com/SimScaleGmbH/simscale-python-sdk, examples/
    incompressible_example.py); NOT run against SimScale from here (no network access to it).
    Install: pip install git+https://github.com/SimScaleGmbH/simscale-python-sdk.git"""
    name = "simscale"

    def __init__(self, project_id: str, template_sim_id: str, mesh_template_id: str | None = None,
                 speed_mps=20.0, poll_s=60, symmetric_half=False, bodies=("car", "wheelF", "wheelR"),
                 force_result_name="Forces and moments"):
        super().__init__()
        import simscale_sdk as sim
        self.sim = sim
        cfg = sim.Configuration()
        cfg.host = os.environ.get("SIMSCALE_API_URL", "https://api.simscale.com") + "/v0"
        cfg.api_key = {"X-API-KEY": os.environ["SIMSCALE_API_KEY"]}
        self.api = sim.ApiClient(cfg)
        self.api.rest_client.pool_manager.connection_pool_kw["timeout"] = 120
        self.project, self.template, self.mesh_template = project_id, template_sim_id, mesh_template_id
        self.speed, self.poll_s, self.half = speed_mps, poll_s, symmetric_half
        self.bodies, self.force_name = list(bodies), force_result_name
        self.running = {}                                         # id -> (sim_id, run_id)

    def _upload(self, folder: Path, name: str):
        import zipfile
        sim = self.sim
        z = folder / "simscale_geometry.zip"
        with zipfile.ZipFile(z, "w") as zf:
            for f in (["car_half.stl", "wheelF.stl", "wheelR.stl"] if self.half else ["body_full.stl", "wheelF.stl", "wheelR.stl"]):
                zf.write(folder / f, f)
        st = sim.StorageApi(self.api).create_storage()
        self.api.rest_client.PUT(url=st.url, headers={"Content-Type": "application/octet-stream"}, body=z.read_bytes())
        gi_api = sim.GeometryImportsApi(self.api)
        req = sim.GeometryImportRequest(name=name, location=sim.GeometryImportRequestLocation(st.storage_id),
                                        format="STL", input_unit="m",
                                        options=sim.GeometryImportRequestOptions(facet_split=False, sewing=False, improve=True,
                                                                                 optimize_for_lbm_solver=False))
        gi = gi_api.import_geometry(self.project, req)
        while gi.status not in ("FINISHED", "CANCELED", "FAILED"):
            time.sleep(10)
            gi = gi_api.get_geometry_import(self.project, gi.geometry_import_id)
        if gi.status != "FINISHED":
            raise RuntimeError(f"SimScale import {gi.status}: {getattr(gi, 'failure_reasons', '')}")
        return gi.geometry_id

    def _entity_names(self, geometry_id):
        """face entity name -> body (solid) name, for the solids the car folder exports."""
        g_api = self.sim.GeometriesApi(self.api)
        out = {}
        for body in self.bodies:
            page = 1
            while True:
                m = g_api.get_geometry_mappings(self.project, geometry_id, _class="face", bodies=[body], page=page, limit=1000)
                for e in m.embedded:
                    out[e.name] = body
                if len(m.embedded) < 1000:
                    break
                page += 1
        return out

    def submit(self, cases):
        sim = self.sim
        s_api = sim.SimulationsApi(self.api)
        r_api = sim.SimulationRunsApi(self.api)
        tmpl = s_api.get_simulation(self.project, self.template)
        old_names = self._entity_names(tmpl.geometry_id)
        for c in cases:
            gid = self._upload(Path(c["folder"]), c["id"])
            new = self._entity_names(gid)
            by_body = {}
            for eid, body in new.items():
                by_body.setdefault(body, []).append(eid)
            spec = self.api.sanitize_for_serialization(tmpl)
            spec["geometryId"] = gid
            spec["name"] = f"sidepod {c['id']}"
            _remap_entities(spec, old_names, by_body)
            new_sim = s_api.create_simulation(self.project, self.api._ApiClient__deserialize(spec, "SimulationSpec"))
            if self.mesh_template:
                m_api = sim.MeshOperationsApi(self.api)
                mt = m_api.get_mesh_operation(self.project, self.mesh_template)
                mo = m_api.create_mesh_operation(self.project, sim.MeshOperation(name=f"mesh {c['id']}", geometry_id=gid,
                                                                                   model=mt.model))
                m_api.start_mesh_operation(self.project, mo.mesh_operation_id, simulation_id=new_sim.simulation_id)
                while m_api.get_mesh_operation(self.project, mo.mesh_operation_id).status not in ("FINISHED", "FAILED", "CANCELED"):
                    time.sleep(self.poll_s)
                spec2 = s_api.get_simulation(self.project, new_sim.simulation_id)
                spec2.mesh_id = mo.mesh_id
                s_api.update_simulation(self.project, new_sim.simulation_id, spec2)
            run = r_api.create_simulation_run(self.project, new_sim.simulation_id, sim.SimulationRun(name="run"))
            r_api.start_simulation_run(self.project, new_sim.simulation_id, run.run_id)
            self.running[c["id"]] = (new_sim.simulation_id, run.run_id)

    def collect(self):
        r_api = self.sim.SimulationRunsApi(self.api)
        for cid, (sid, rid) in list(self.running.items()):
            run = r_api.get_simulation_run(self.project, sid, rid)
            if run.status not in ("FINISHED", "FAILED", "CANCELED"):
                continue
            self.running.pop(cid)
            if run.status != "FINISHED":
                self._done[cid] = {"D20_N": None, "L20_N": None, "ok": False, "info": {"simscale": "FAILED"}}
                continue
            res = r_api.get_simulation_run_results(self.project, sid, rid, category="FORCE_PLOT", name=self.force_name)
            Fx = Fz = None
            for item in res.embedded:
                url = item.download.url
                txt = self.api.rest_client.GET(url, headers={"X-API-KEY": os.environ["SIMSCALE_API_KEY"]}).data.decode()
                Fx, Fz = _last_force_row(txt)
            k = 2.0 if self.half else 1.0
            self._done[cid] = {"D20_N": Fx * k * (20.0 / self.speed) ** 2 if Fx is not None else None,
                               "L20_N": Fz * k * (20.0 / self.speed) ** 2 if Fz is not None else None,
                               "ok": Fx is not None, "info": {"simscale_sim": sid, "run": rid}}
        return super().collect()


def _remap_entities(node, old_names, by_body):
    """Walk a simulation spec; replace every face-entity list by the new geometry's faces of the
    same solids (the template's faces -> their solid names -> the new faces of those solids)."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "entities" and isinstance(v, list) and v and isinstance(v[0], str):
                bodies = {old_names.get(e) for e in v} - {None}
                node[k] = sorted({e for b in bodies for e in by_body.get(b, [])}) or v
            else:
                _remap_entities(v, old_names, by_body)
    elif isinstance(node, list):
        for v in node:
            _remap_entities(v, old_names, by_body)


def _last_force_row(csv_text):
    """SimScale 'Forces and moments' CSV: take the time-average of the last 30 % of rows of the
    total force x (drag) and z (lift) columns."""
    import csv
    import io
    rows = list(csv.reader(io.StringIO(csv_text)))
    head = [h.lower() for h in rows[0]]
    ix = next(i for i, h in enumerate(head) if "total" in h and "force" in h and h.strip().endswith("x"))
    iz = next(i for i, h in enumerate(head) if "total" in h and "force" in h and h.strip().endswith("z"))
    data = np.array([[float(r[ix]), float(r[iz])] for r in rows[1:] if r])
    tail = data[int(0.7 * len(data)):]
    return float(tail[:, 0].mean()), float(tail[:, 1].mean())


# ---------------------------------------------------------------------- adjoint
class AdjointEvaluator(Evaluator):
    """Primal + adjoint on one car: D20, L20 AND the race-time gradient w.r.t. the 1 mm design
    field (s per mm of field), aero part from the adjoint, mass/COM part exact.
    backend "esi": Part 2's openfoam_adjoint (failed Part 3's known-answer wing: r 0.53).
    backend "dafoam": DAFoam (discrete, exact w.r.t. its own primal); runner script expected at
    research/sidepod_opt/dafoam_run.py inside a DAFoam container. Never used before gate_adjoint passes."""
    name = "adjoint"

    def __init__(self, car, race_model, backend="esi", res="medium", n_subdomains=2):
        super().__init__()
        self.car, self.rm, self.backend, self.res, self.np = car, race_model, backend, res, n_subdomains

    def submit(self, cases):
        for c in cases:
            folder = Path(c["folder"])
            if self.backend == "esi":
                sys.path.insert(0, str(P2))
                import openfoam_adjoint as OA
                import stopwatch as SW
                cfg = OA.AdjointRunConfig(resolution=self.res, n_subdomains=self.np)
                body = SW.body_stl(folder / "car_half.stl", folder / "_body_half.stl")
                # one value per STL triangle CORNER (the nearest CFD point's): kinematic dD20_half/dn
                # per unit AREA (ESI's default, includeSurfaceArea false; gate.py and Part 3). Turned
                # into N per m of outward move per corner: rho * value * (face area / 3).
                s = np.asarray(OA.invoke_adjoint(str(body), str(folder / "adjoint_case"), cfg))
                import trimesh
                bm = trimesh.load(body)
                verts = bm.vertices[bm.faces].reshape(-1, 3)
                if len(verts) != len(s):
                    raise RuntimeError(f"adjoint: {len(s)} values for {len(verts)} STL corners")
                sens = RHO * s * np.repeat(bm.area_faces / 3.0, 3)
                fwd = run_openfoam_case(folder, self.res, {}, self.np, 1000)
            else:
                out = folder / "dafoam_out.json"
                subprocess.run([sys.executable, str(HERE / "dafoam_run.py"), str(folder), self.res], check=True)
                d = json.loads(out.read_text())
                verts, sens, fwd = np.array(d["vertices_m"]), np.array(d["dD20_half_dn_N_per_m"]), d["forward"]   # per point, area-integrated
            self._done[c["id"]] = dict(fwd, grad_vertices_m=np.asarray(verts).tolist(), grad_dD20_half_dn=np.asarray(sens).tolist())


def field_gradient(car, body, mass, rm, D20, L20, pts_m, dD_half_N_per_m):
    """Race-time gradient on the 1 mm field (s per mm of field = per mm of outward surface move).
    pts_m: surface points (car frame, m); dD_half_N_per_m: half-car drag change per m of outward
    move of the surface each point carries (area already in). Aero: dT/dD20 x the points' sum per
    cell (N/mm), put on the cell and its mirror (finish() symmetrises the field: a field change at
    one cell is half a change on each side of the whole car, 2 x 0.5 = 1). Mass and COM: exact
    per-cell slope (objective.mass_cell_gradient) on the surface cells, x cell face area."""
    from objective import mass_cell_gradient
    from scipy import ndimage
    T, sl = rm(D20, L20, mass)
    g = np.zeros(car.body0.shape)
    P = np.asarray(pts_m)
    x = car.s.x_nose_mm - P[:, 0] * 1e3
    y = P[:, 1] * 1e3
    z = P[:, 2] * 1e3
    ix = np.clip(np.searchsorted(car.xs, x) - 1, 0, len(car.xs) - 1)
    iz = np.clip(np.searchsorted(car.zs, z) - 1, 0, len(car.zs) - 1)
    for yy in (y, -y):
        iy = np.clip(np.searchsorted(car.ys, yy) - 1, 0, len(car.ys) - 1)
        np.add.at(g, (ix, iy, iz), sl["drag_20_n"] * np.asarray(dD_half_N_per_m) * 1e-3)
    surf = body & ~ndimage.binary_erosion(body)
    g += np.where(surf, mass_cell_gradient(car, mass, sl) * car.h ** 2, 0.0)
    return g * car.region
