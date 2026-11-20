"""SimScale geometry engine and setup tool: from the team's STEP (or any design) to a SimScale run,
by hand, one step at a time. The campaign uses the same pieces automatically.

    python simscale_tool.py check                          # SDK installed? API key works?
    python simscale_tool.py ids                            # projects, simulations, mesh operations: the IDs
    python simscale_tool.py export <out_dir> [--design original|none|<x.npy>] [--config config.simscale.json]
                                                           # STEP -> design -> milled, rule-checked car folder (STLs)
    python simscale_tool.py upload <car_folder> --project ID
                                                           # import the STLs; prints the body names SimScale made
    python simscale_tool.py run <car_folder> --project ID --template SIM_ID --mesh MESH_OP_ID [--max-cost X]
                                                           # one car end to end: import, mesh, run, D20/L20
    python simscale_tool.py selftest --project ID --template SIM_ID --mesh MESH_OP_ID [--max-cost X]
                                                           # original x3 (noise) + 2 evolved designs (cost, time)

Needs SIMSCALE_API_KEY in the environment (never in a file in the repo). Units: STLs in metres,
car frame (x from the nose, flow +x), half car (y >= 0, closed at y = 0) with solids `car`, `wheelF`,
`wheelR`; a whole-car export (body_full.stl + mirrored wheels) is also written for templates without
a symmetry plane.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def sdk():
    try:
        import simscale_sdk as s
    except ImportError:
        sys.exit("simscale_sdk is not installed. It is not on PyPI:\n"
                 "  git clone --depth 1 https://github.com/SimScaleGmbH/simscale-python-sdk.git\n"
                 "  pip install ./simscale-python-sdk\n"
                 "If pip fails to build it, put the clone on PYTHONPATH instead:\n"
                 "  export PYTHONPATH=$PWD/simscale-python-sdk:$PYTHONPATH")
    return s


def client():
    s = sdk()
    if not os.environ.get("SIMSCALE_API_KEY"):
        sys.exit("SIMSCALE_API_KEY is not set (SimScale: account settings -> API keys).")
    cfg = s.Configuration()
    cfg.host = os.environ.get("SIMSCALE_API_URL", "https://api.simscale.com") + "/v0"
    cfg.api_key = {"X-API-KEY": os.environ["SIMSCALE_API_KEY"]}
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")   # urllib3 ignores proxy env vars
    if proxy:
        cfg.proxy = proxy
    ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if ca:
        cfg.ssl_ca_cert = ca
    api = s.ApiClient(cfg)
    api.rest_client.pool_manager.connection_pool_kw["timeout"] = 120
    return s, api


def load_spec(config):
    from geometry import CarSpec
    car = json.loads(Path(config).read_text()).get("car", {}) if config else {}
    for k, v in list(car.items()):
        if isinstance(v, list):
            car[k] = tuple(v)
    return CarSpec(**car)


def cmd_check(a):
    s, api = client()
    p = s.ProjectsApi(api).get_projects(limit=5, page=1)
    print("SDK ok, API key ok. Projects visible:", len(p.embedded or []))


def cmd_ids(a):
    s, api = client()
    page = 1
    while True:
        ps = s.ProjectsApi(api).get_projects(limit=100, page=page)
        for p in ps.embedded or []:
            print(f"project  {p.project_id}  {p.name}")
            for sim in (s.SimulationsApi(api).get_simulations(p.project_id, limit=100).embedded or []):
                print(f"   simulation      {sim.simulation_id}  {sim.name}")
            for mo in (s.MeshOperationsApi(api).get_mesh_operations(p.project_id, limit=100).embedded or []):
                print(f"   mesh operation  {mo.mesh_operation_id}  {mo.name}")
        if len(ps.embedded or []) < 100:
            break
        page += 1


def cmd_export(a):
    from geometry import Car
    import design as DS
    spec = load_spec(a.config)
    car = Car(spec, h=1.0)
    out = Path(a.out)
    if a.design == "original":
        b = car.build(car.sdf_original, original=True)
    elif a.design == "none":
        b = car.build(np.full(car.body0.shape, -1.0))
    else:
        rep = DS.Lattice(car, (10, 4, 5), 12.0, "blend")
        b = car.build(rep.field(np.load(a.design)))
    if not b["check"]["ok"]:
        sys.exit(f"design fails the rules: {b['check']}")
    car.export_car_folder(b["mesh"], out, out.name)
    for w in ("wheelF", "wheelR"):                     # whole-car extras for templates without symmetry
        from evaluators import _mirrored_stl
        (out / f"{w}_m.stl").write_text(_mirrored_stl(out / f"{w}.stl", f"{w}_m"))
    (out / "mass.json").write_text(json.dumps(b["mass"], indent=1, default=float))
    print(json.dumps({"folder": str(out), "check": b["check"], "foam_g": b["mass"]["foam_g"],
                      "files": sorted(p.name for p in out.glob("*.stl"))}, default=float))


def evaluator(a, state):
    import evaluators as EV
    bodies = a.bodies.split(",") if a.bodies else None
    return EV.SimScaleEvaluator(a.project, a.template, a.mesh, state, symmetric_half=not a.whole,
                                max_cost=a.max_cost, bodies=bodies)


def cmd_upload(a):
    s, api = client()
    import evaluators as EV
    ev = EV.SimScaleEvaluator(a.project, "none", "none", Path(a.folder) / "simscale_upload_state.json",
                              symmetric_half=not a.whole, sdk=s, api_client=api)
    gi = ev._upload(Path(a.folder), Path(a.folder).name)
    g = s.GeometryImportsApi(api)
    while True:
        r = g.get_geometry_import(a.project, gi)
        if r.status in ("FINISHED", "FAILED", "CANCELED"):
            break
        time.sleep(10)
    print("import:", r.status, getattr(r, "failure_reasons", ""))
    if r.status == "FINISHED":
        geo = s.GeometriesApi(api).get_geometry(a.project, r.geometry_id)
        print("geometry id:", r.geometry_id)
        print(json.dumps(api.sanitize_for_serialization(geo), indent=1)[:3000])
        print("The template's boundary conditions are matched to these BODY names. The campaign expects",
              ev.bodies, "- if SimScale named them otherwise, set \"bodies\" in the evaluator config.")


def run_cases(a, cases):
    ev = evaluator(a, Path(a.state or "simscale_tool_state.json"))
    ev.submit(cases)
    out = {}
    while len(out) < len(cases):
        time.sleep(60)
        for cid, r in ev.collect().items():
            out[cid] = r
            print(cid, json.dumps(r, default=float), flush=True)
    return out


def cmd_run(a):
    folder = Path(a.folder)
    run_cases(a, [{"id": folder.name, "folder": str(folder)}])


def cmd_selftest(a):
    """Original 3x (spread = SimScale's noise) + 2 evolved designs; prints cost and time per car."""
    from geometry import Car
    import design as DS
    spec = load_spec(a.config)
    car = Car(spec, h=1.0)
    root = Path(a.out or "simscale_selftest"); root.mkdir(exist_ok=True)
    cases = []
    b = car.build(car.sdf_original, original=True)
    for i in range(3):
        d = root / f"original_{i}"; car.export_car_folder(b["mesh"], d, d.name); cases.append({"id": d.name, "folder": str(d)})
    rep = DS.Lattice(car, (10, 4, 5), 12.0, "blend"); rng = np.random.default_rng(1)
    while len(cases) < 5:
        bb = car.build(rep.field(rep.x0("original") + 0.8 * rng.normal(size=rep.dim)))
        if bb["check"]["ok"] and bb["mass"]["legal"]:
            d = root / f"design_{len(cases) - 3}"; car.export_car_folder(bb["mesh"], d, d.name); cases.append({"id": d.name, "folder": str(d)})
    res = run_cases(a, cases)
    D = [res[f"original_{i}"]["D20_N"] for i in range(3) if res[f"original_{i}"]["ok"]]
    summary = {"original_D20_N": D, "noise_N": float(np.ptp(D)) if len(D) > 1 else None,
               "designs": {k: v for k, v in res.items() if k.startswith("design")},
               "cost_estimates": [v["info"].get("cost_estimate") for v in res.values()],
               "wall_s": [v["info"].get("wall_s") for v in res.values()]}
    (root / "selftest.json").write_text(json.dumps(summary, indent=1, default=float))
    print(json.dumps(summary, indent=1, default=float))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check", "ids", "export", "upload", "run", "selftest"])
    ap.add_argument("folder", nargs="?", help="car folder (upload/run) or output folder (export)")
    ap.add_argument("--config", default=str(HERE / "config.simscale.json"), help="campaign config: its \"car\" rules")
    ap.add_argument("--design", default="original")
    ap.add_argument("--project"); ap.add_argument("--template"); ap.add_argument("--mesh")
    ap.add_argument("--max-cost", type=float, default=None)
    ap.add_argument("--whole", action="store_true", help="whole car (template without a symmetry plane)")
    ap.add_argument("--bodies", default=None, help="comma list of SimScale body names, if not car,wheelF,wheelR")
    ap.add_argument("--state", default=None); ap.add_argument("--out", default=None)
    a = ap.parse_args()
    a.out = a.out or (a.folder if a.cmd == "export" else None)
    if a.cmd == "export" and not a.folder:
        sys.exit("export needs an output folder")
    {"check": cmd_check, "ids": cmd_ids, "export": cmd_export, "upload": cmd_upload, "run": cmd_run,
     "selftest": cmd_selftest}[a.cmd](a)


if __name__ == "__main__":
    main()
