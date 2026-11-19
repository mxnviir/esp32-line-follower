"""One GitHub Actions job: time the car folders of one group, on ONE frozen state, with OpenFOAM.

    python eval_one.py <batch_dir> <group_index> <res> --state A|B|plain [--refs refs.json] [--mode auto] [--np 2]

refs.json maps state -> unpacked reference case dir (made by `campaign.py make-refs`, released,
downloaded by the workflow). Writes <batch_dir>/results/<id>__<state>.json for each car of the
group: {"id", "state", "result": that state's D20/L20/health, or "error"}. The campaign's
ActionsEvaluator combines the states of a car (Part 2 method A).
"""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluators import run_openfoam_case

ap = argparse.ArgumentParser()
ap.add_argument("batch"); ap.add_argument("group", type=int); ap.add_argument("res")
ap.add_argument("--state", default="plain")
ap.add_argument("--refs"); ap.add_argument("--mode", default="auto"); ap.add_argument("--np", type=int, default=2)
ap.add_argument("--iters", type=int, default=1000)
a = ap.parse_args()
b = Path(a.batch)
groups = json.loads((b / "batch.json").read_text())["groups"]
refs = json.loads(Path(a.refs).read_text()) if a.refs else {}
if a.state != "plain":
    if a.state not in refs:
        raise SystemExit(f"state {a.state} not in {a.refs}")
    refs = {a.state: refs[a.state]}
else:
    refs = {}
out = b / "results"; out.mkdir(exist_ok=True)
for cid in groups[a.group]:
    r = run_openfoam_case(b / cid, a.res, refs, a.np, a.iters, None, a.mode if refs else "plain")
    per = r["info"].get("by_state", r["info"]) if isinstance(r.get("info"), dict) else {}
    one = next(iter(per.values()), {"error": "no result"})
    (out / f"{cid}__{a.state}.json").write_text(json.dumps({"id": cid, "state": a.state, "result": one}, indent=1, default=float))
    print(cid, a.state, one.get("D20_N"), one.get("error", ""), flush=True)
