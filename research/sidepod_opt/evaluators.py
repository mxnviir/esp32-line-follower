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


def _latest_run_dir():
    runs = sorted((P2 / "cfd_case_template" / "runs").glob(f"run_{os.getpid()}_*"), key=lambda p: p.stat().st_mtime)
    return runs[-1] if runs else None


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
            half, health = run_half_car_cfd(str(body), n_subdomains=n_sub, extra_surfaces=SW.extra_surfaces(folder),
                                            keep_run_dir=True, **k2)
            run = _latest_run_dir()
            fell_back = bool(s and run and (run / "MORPH_FALLBACK").exists())   # left the reference mesh
            if run:
                import shutil
                shutil.rmtree(run, ignore_errors=True)
            full = half.to_full_car()
            per[s or "plain"] = {"D20_N": full.D20, "L20_N": full.L, "converged": bool(health.converged),
                                 "residual_p": health.residual_final, "force_osc": health.force_oscillation,
                                 "morph_fallback": fell_back}
            if fell_back and mode == "morph":                     # morph only: a fresh mesh is not this result
                per[s]["error"] = "reshaped mesh failed checkMesh (fresh-mesh noise); mode morph"
                per[s].pop("D20_N")
        except Exception as e:                                    # a failed case is a result, not a crash
            per[s or "plain"] = {"error": repr(e)[:400]}
    return combine_states(per)


def combine_states(per: dict) -> dict:
    """Per-state results -> one car result (Part 2 method A: mean over states)."""
    good = [v for v in per.values() if "D20_N" in v]
    if not good:
        return {"D20_N": None, "L20_N": None, "ok": False, "info": per}
    return {"D20_N": float(np.mean([v["D20_N"] for v in good])), "L20_N": float(np.mean([v["L20_N"] for v in good])),
            "ok": all(v.get("converged") for v in good) and len(good) == len(per),
            "info": {"by_state": per, "state_spread_N": float(np.ptp([v["D20_N"] for v in good])) if len(good) > 1 else 0.0}}


# ---------------------------------------------------------------------- OpenFOAM on GitHub Actions
class ActionsEvaluator(Evaluator):
    """OpenFOAM on GitHub Actions (.github/workflows/sidepod_eval.yml), any number of repos.

    submit(): zips the batch (car folders + batch.json) and uploads it as an asset of the release
    `release` in the chosen repo (round robin), then dispatches the workflow on `ref` (the branch
    that holds this code and the workflow). Nothing is committed. The workflow runs ONE job per
    (car group, frozen state), so a state never shares the 6 h job limit with another.
    collect(): idempotent. Every completed run of a pending batch is downloaded once, into
    results/<run id>/; per-state results are combined (mean of states) when all states of a car
    are in. A car whose run finished without a result (job failed, timed out, cancelled) comes
    back as a failed car (ok False), so the campaign tells the method and moves on.
    dry_run=True only writes the batch (results can be dropped into <batch>/results/ by hand)."""
    name = "actions"

    def __init__(self, jobs_dir: Path, repos: list, ref="main", res="medium", dry_run=False, per_job=1,
                 release="sidepod-jobs", refs_tag="", states=None, mode="auto", iters=1000):
        super().__init__()
        self.jobs, self.repos, self.ref, self.res, self.dry, self.per_job = Path(jobs_dir), repos, ref, res, dry_run, per_job
        self.release, self.refs_tag, self.mode, self.iters = release, refs_tag, mode, iters
        self.states = list(states or (["A", "B"] if refs_tag else ["plain"]))
        self.pending = {}                                         # batch -> {"repo", "ids", "dispatched", "runs_done"}
        self.state_file = self.jobs / "actions_state.json"
        if self.state_file.exists():
            self.pending = json.loads(self.state_file.read_text())

    def submit(self, cases):
        if not cases:
            return
        import shutil
        batch = time.strftime("b%Y%m%d-%H%M%S") + f"-{os.getpid() % 1000:03d}"
        bdir = self.jobs / batch
        bdir.mkdir(parents=True, exist_ok=True)
        ids = []
        for c in cases:
            dst = bdir / c["id"]
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(c["folder"], dst, ignore=shutil.ignore_patterns("*_raw.stl", "body_full.stl", "_body_half.stl", "*.npy"))
            ids.append(c["id"])
        groups = [ids[i:i + self.per_job] for i in range(0, len(ids), self.per_job)]
        matrix = [{"group": g, "state": s} for g in range(len(groups)) for s in self.states]
        (bdir / "batch.json").write_text(json.dumps({"res": self.res, "groups": groups, "states": self.states,
                                                     "matrix": matrix}, indent=1))
        repo = self.repos[len(self.pending) % len(self.repos)] if self.repos else None
        self.pending[batch] = {"repo": repo, "ids": ids, "dispatched": False, "runs_done": []}
        if not self.dry and repo:
            z = shutil.make_archive(str(self.jobs / batch), "zip", root_dir=self.jobs, base_dir=batch)
            if subprocess.run(["gh", "release", "view", self.release, "-R", repo], capture_output=True).returncode:
                _sh(["gh", "release", "create", self.release, "-R", repo, "--prerelease", "--title", "sidepod job inputs",
                     "--notes", "Batch inputs for sidepod_eval.yml (zipped car folders). Safe to delete old assets."], REPO)
            _sh(["gh", "release", "upload", self.release, z, "-R", repo, "--clobber"], REPO)
            _sh(["gh", "workflow", "run", "sidepod_eval.yml", "-R", repo, "--ref", self.ref,
                 "-f", f"batch={batch}", "-f", f"release={self.release}", "-f", f"res={self.res}",
                 "-f", f"refs_tag={self.refs_tag}", "-f", f"mode={self.mode}", "-f", f"iters={self.iters}"], REPO)
            self.pending[batch]["dispatched"] = True
            self.pending[batch]["submitted"] = time.time()
        self._save()

    def collect(self):
        for batch, p in list(self.pending.items()):
            rdir = self.jobs / batch / "results"
            finished_runs = 0
            if not self.dry and p["repo"]:
                runs = json.loads(_sh(["gh", "run", "list", "-R", p["repo"], "-w", "sidepod_eval.yml", "--json",
                                       "databaseId,status,conclusion,displayTitle", "-L", "200"], REPO) or "[]")
                for r in runs:
                    if batch not in r["displayTitle"] or r["status"] != "completed":
                        continue
                    finished_runs += 1
                    rid = str(r["databaseId"])
                    if rid in p["runs_done"]:
                        continue
                    d = rdir / rid
                    if r["conclusion"] in ("success", "failure", "timed_out", "cancelled"):
                        shutil_rm(d)
                        subprocess.run(["gh", "run", "download", rid, "-R", p["repo"], "-p", "sidepod-results-*",
                                        "-D", str(d)], cwd=REPO, capture_output=True)   # none on a run that died early
                    p["runs_done"].append(rid)
            per = {}
            for f in rdir.rglob("*.json") if rdir.exists() else []:
                d = json.loads(f.read_text())
                if d.get("id") in p["ids"]:
                    per.setdefault(d["id"], {})[d.get("state", "plain")] = d.get("result", d)
            closed = finished_runs > 0 or self.dry
            for cid in p["ids"]:
                got = per.get(cid, {})
                if all(s in got for s in self.states):
                    self._done[cid] = combine_states(got)
                elif closed and not self.dry:
                    for s in self.states:
                        got.setdefault(s, {"error": "no result from the Actions run (job failed, timed out or cancelled)"})
                    self._done[cid] = combine_states(got)
            if all(i in self._done for i in p["ids"]):
                self.pending.pop(batch)
        self._save()
        return super().collect()

    def _save(self):
        self.jobs.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.pending, indent=1))


def shutil_rm(d: Path):
    import shutil
    shutil.rmtree(d, ignore_errors=True)


def _sh(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"{' '.join(cmd)}: {r.stderr[-500:]}")
    return r.stdout


# ---------------------------------------------------------------------- SimScale
class SimScaleEvaluator(Evaluator):
    """SimScale via its Python SDK. Set up ONE template in the web UI on the original car (imported
    as the same named STL solids: body_full or car, wheelF, wheelR): k-omega SST, rolling road,
    rotating wheels, a 'Forces and moments' result control on the car + wheels, and ONE mesh
    operation on it (its settings are copied for every design). See SIMSCALE.md.

    Every design walks import -> mesh -> run as a state machine kept in `state_path` (JSON), so a
    batch survives between cron ticks and nothing blocks: submit() only uploads and starts the
    imports, collect() advances every case one step and returns the finished ones.
    Each case is cost-checked before its run starts (SimScale's own estimate, `max_cost`).

    Calls checked against the SDK source (github.com/SimScaleGmbH/simscale-python-sdk, examples/
    incompressible_example.py) and by a mocked test (test_simscale.py); not yet run against SimScale.
    Install: git clone the SDK and `pip install ./simscale-python-sdk` (it is not on PyPI)."""
    name = "simscale"

    def __init__(self, project_id: str, template_sim_id: str, mesh_template_id: str, state_path: Path,
                 speed_mps=20.0, symmetric_half=True, bodies=None,
                 force_result_name="Forces and moments", max_cost=None, sdk=None, api_client=None):
        super().__init__()
        if sdk is None:
            import simscale_sdk as sdk
        self.sim = sdk
        if api_client is None:
            cfg = sdk.Configuration()
            cfg.host = os.environ.get("SIMSCALE_API_URL", "https://api.simscale.com") + "/v0"
            cfg.api_key = {"X-API-KEY": os.environ["SIMSCALE_API_KEY"]}
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")   # urllib3 ignores proxy env vars
    if proxy:
        cfg.proxy = proxy
    ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if ca:
        cfg.ssl_ca_cert = ca
            api_client = sdk.ApiClient(cfg)
            api_client.rest_client.pool_manager.connection_pool_kw["timeout"] = 120
        self.api = api_client
        self.project, self.template, self.mesh_template = str(project_id), template_sim_id, mesh_template_id
        self.speed, self.half, self.max_cost = speed_mps, symmetric_half, max_cost
        self.bodies = list(bodies or (["car", "wheelF", "wheelR"] + ([] if symmetric_half else ["wheelF_m", "wheelR_m"])))
        self.force_name = force_result_name
        self.state_path = Path(state_path)
        self.cases = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self._tmpl = None

    # ---------------------------------------------------------------- helpers
    def _save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.cases, indent=1))

    def _fail(self, cid, why):
        self.cases.pop(cid, None)
        self._done[cid] = {"D20_N": None, "L20_N": None, "ok": False, "info": {"simscale": str(why)[:500]}}

    def _template(self):
        if self._tmpl is None:
            s_api = self.sim.SimulationsApi(self.api)
            tmpl = s_api.get_simulation(self.project, self.template)
            m_api = self.sim.MeshOperationsApi(self.api)
            self._tmpl = (tmpl, self._entity_names(tmpl.geometry_id), m_api.get_mesh_operation(self.project, self.mesh_template))
        return self._tmpl

    def _upload(self, folder: Path, name: str):
        import zipfile
        sim = self.sim
        z = folder / "simscale_geometry.zip"
        with zipfile.ZipFile(z, "w") as zf:
            for f in (["car_half.stl", "wheelF.stl", "wheelR.stl"] if self.half else ["body_full.stl", "wheelF.stl", "wheelR.stl"]):
                zf.write(folder / f, f)
            if not self.half:                                     # whole car: the -y wheels, mirrored
                for w in ("wheelF", "wheelR"):
                    zf.writestr(f"{w}_m.stl", _mirrored_stl(folder / f"{w}.stl", f"{w}_m"))
        st = sim.StorageApi(self.api).create_storage()
        self.api.rest_client.PUT(url=st.url, headers={"Content-Type": "application/octet-stream"}, body=z.read_bytes())
        req = sim.GeometryImportRequest(name=name, location=sim.GeometryImportRequestLocation(st.storage_id),
                                        format="STL", input_unit="m",
                                        options=sim.GeometryImportRequestOptions(facet_split=False, sewing=False, improve=True,
                                                                                 optimize_for_lbm_solver=False))
        return sim.GeometryImportsApi(self.api).import_geometry(self.project, req).geometry_import_id

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

    # ---------------------------------------------------------------- interface
    def submit(self, cases):
        for c in cases:
            try:
                gi = self._upload(Path(c["folder"]), c["id"])
                self.cases[c["id"]] = {"phase": "import", "import_id": gi, "t0": time.time()}
            except Exception as e:                                     # one bad case never stops the batch
                self._fail(c["id"], f"upload: {e!r}")
            self._save()

    def collect(self):
        for cid in list(self.cases):
            try:
                self._advance(cid)
            except Exception as e:
                self._fail(cid, f"{self.cases.get(cid, {}).get('phase')}: {e!r}")
            self._save()
        return super().collect()

    def _advance(self, cid):
        sim, c = self.sim, self.cases[cid]
        if c["phase"] == "import":
            gi = sim.GeometryImportsApi(self.api).get_geometry_import(self.project, c["import_id"])
            if gi.status in ("FAILED", "CANCELED"):
                return self._fail(cid, f"import {gi.status}: {getattr(gi, 'failure_reasons', '')}")
            if gi.status != "FINISHED":
                return
            tmpl, old_names, mesh_t = self._template()
            new = self._entity_names(gi.geometry_id)
            by_body = {}
            for eid, body in new.items():
                by_body.setdefault(body, []).append(eid)
            missing = set(self.bodies) - set(by_body)
            if missing:
                return self._fail(cid, f"solids missing after import: {sorted(missing)}")
            spec = self.api.sanitize_for_serialization(tmpl)
            spec.pop("simulationId", None); spec.pop("meshId", None)
            spec["geometryId"] = gi.geometry_id
            spec["name"] = f"sidepod {cid}"
            _remap_entities(spec, old_names, by_body)
            s_api, m_api = sim.SimulationsApi(self.api), sim.MeshOperationsApi(self.api)
            new_sim = s_api.create_simulation(self.project, self.api._ApiClient__deserialize(spec, "SimulationSpec"))
            mo = m_api.create_mesh_operation(self.project, sim.MeshOperation(name=f"mesh {cid}", geometry_id=gi.geometry_id,
                                                                               model=mesh_t.model))
            chk = m_api.check_mesh_operation_setup(self.project, mo.mesh_operation_id, simulation_id=new_sim.simulation_id)
            errs = [e for e in (getattr(chk, "entries", None) or []) if e.severity == "ERROR"]
            if errs:
                return self._fail(cid, f"mesh check: {errs}")
            m_api.start_mesh_operation(self.project, mo.mesh_operation_id, simulation_id=new_sim.simulation_id)
            c.update(phase="mesh", geometry_id=gi.geometry_id, sim_id=new_sim.simulation_id, mesh_op=mo.mesh_operation_id)
        elif c["phase"] == "mesh":
            m_api, s_api = sim.MeshOperationsApi(self.api), sim.SimulationsApi(self.api)
            mo = m_api.get_mesh_operation(self.project, c["mesh_op"])
            if mo.status in ("FAILED", "CANCELED"):
                return self._fail(cid, f"mesh {mo.status}")
            if mo.status != "FINISHED":
                return
            spec = s_api.get_simulation(self.project, c["sim_id"])
            spec.mesh_id = mo.mesh_id
            s_api.update_simulation(self.project, c["sim_id"], spec)
            chk = s_api.check_simulation_setup(self.project, c["sim_id"])
            errs = [e for e in (getattr(chk, "entries", None) or []) if e.severity == "ERROR"]
            if errs:
                return self._fail(cid, f"simulation check: {errs}")
            cost = None
            try:
                est = s_api.estimate_simulation_setup(self.project, c["sim_id"])
                cost = est.compute_resource.value if est.compute_resource is not None else None
            except sim.ApiException as e:
                if e.status != 422:                               # 422: no estimate available
                    raise
            if self.max_cost is not None and cost is not None and cost > self.max_cost:
                return self._fail(cid, f"too expensive: estimate {cost} > max_cost {self.max_cost}")
            r_api = sim.SimulationRunsApi(self.api)
            run = r_api.create_simulation_run(self.project, c["sim_id"], sim.SimulationRun(name="run"))
            r_api.start_simulation_run(self.project, c["sim_id"], run.run_id)
            c.update(phase="run", run_id=run.run_id, cost_estimate=cost)
        elif c["phase"] == "run":
            r_api = sim.SimulationRunsApi(self.api)
            run = r_api.get_simulation_run(self.project, c["sim_id"], c["run_id"])
            if run.status in ("FAILED", "CANCELED"):
                return self._fail(cid, f"run {run.status}")
            if run.status != "FINISHED":
                return
            res = r_api.get_simulation_run_results(self.project, c["sim_id"], c["run_id"], category="FORCE_PLOT",
                                                   name=self.force_name)
            Fx = Fz = None
            for item in res.embedded:
                txt = self.api.rest_client.GET(item.download.url, headers={"X-API-KEY": self.api.configuration.api_key["X-API-KEY"]}).data
                Fx, Fz = _last_force_row(txt.decode() if isinstance(txt, bytes) else txt)
            k = 2.0 if self.half else 1.0
            sc = k * (20.0 / self.speed) ** 2
            self.cases.pop(cid)
            self._done[cid] = {"D20_N": Fx * sc if Fx is not None else None, "L20_N": Fz * sc if Fz is not None else None,
                               "ok": Fx is not None,
                               "info": {"simscale_sim": c["sim_id"], "run": c["run_id"], "cost_estimate": c.get("cost_estimate"),
                                        "wall_s": time.time() - c["t0"]}}


def _mirrored_stl(path: Path, solid: str) -> str:
    """The +y wheel STL mirrored to -y (y -> -y, winding reversed so normals stay outward), ASCII."""
    import trimesh
    m = trimesh.load(path, process=False)
    v = m.vertices * np.array([1.0, -1.0, 1.0])
    f = m.faces[:, ::-1]
    tri = v[f]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-300
    out = [f"solid {solid}"]
    for nn, t in zip(n, tri):
        out.append(f"facet normal {nn[0]:.9e} {nn[1]:.9e} {nn[2]:.9e}\n outer loop")
        out += [f"  vertex {p[0]:.9e} {p[1]:.9e} {p[2]:.9e}" for p in t]
        out.append(" endloop\nendfacet")
    out.append(f"endsolid {solid}")
    return "\n".join(out) + "\n"


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
