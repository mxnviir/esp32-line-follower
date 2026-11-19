"""One GitHub Actions job: time the car folders of one group with OpenFOAM and write results.

    python eval_one.py <batch_dir> <group_index> <res> [--refs refs.json] [--mode auto] [--np 2]

refs.json maps state -> unpacked reference case dir (made by `campaign.py make-refs`, released,
downloaded by the workflow). Writes <batch_dir>/results/<id>.json for each car in the group.
"""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluators import run_openfoam_case

ap = argparse.ArgumentParser()
ap.add_argument("batch"); ap.add_argument("group", type=int); ap.add_argument("res")
ap.add_argument("--refs"); ap.add_argument("--mode", default="auto"); ap.add_argument("--np", type=int, default=2)
ap.add_argument("--iters", type=int, default=1000)
a = ap.parse_args()
b = Path(a.batch)
groups = json.loads((b / "batch.json").read_text())["groups"]
refs = json.loads(Path(a.refs).read_text()) if a.refs else {}
out = b / "results"; out.mkdir(exist_ok=True)
for cid in groups[a.group]:
    r = run_openfoam_case(b / cid, a.res, refs, a.np, a.iters, None, a.mode)
    r["id"] = cid
    (out / f"{cid}.json").write_text(json.dumps(r, indent=1, default=float))
    print(cid, r.get("D20_N"), r.get("ok"), flush=True)
