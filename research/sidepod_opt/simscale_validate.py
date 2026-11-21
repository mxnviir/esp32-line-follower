"""Validation runs on SimScale, outside the evolution: the same evaluator (same geometry route, keys in
order, retries) on chosen car folders with a chosen mesh setting, in its own state file.

    python simscale_validate.py <out_dir> <tag> '<sizing json or null>' [fineness] [box_mm] car_folder ...

Results are appended to <out_dir>/results.jsonl as {"tag", "car", "D20_N", "L20_N", "info"}.
Keys come from SIMSCALE_API_KEYS (first key first), never from a file.
"""
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main():
    out, tag, sizing = Path(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3])
    fineness, box_mm = float(sys.argv[4]), float(sys.argv[5])
    folders = [Path(f) for f in sys.argv[6:]]
    import campaign as C
    import simscale_step_eval as SSE
    car = C.Campaign(HERE / "runs" / "simscale").car
    out.mkdir(parents=True, exist_ok=True)
    ev = SSE.SimScaleStepEvaluator(car, out / f"state_{tag}.json", runs_per_key=None, speed_mps=20.0, max_cost=float(os.environ.get("VAL_MAX_COST", "80")),
                                   fineness=fineness, box_mm=box_mm, iters=1000, sizing=sizing)
    ids = {f"{tag}_{f.name}": f for f in folders}
    ev.submit([{"id": cid, "folder": str(f)} for cid, f in ids.items() if cid not in ev.st["cases"]])
    left = set(ids)
    while left:
        for cid, r in ev.collect().items():
            if cid in left:
                left.discard(cid)
                row = {"tag": tag, "car": ids[cid].name, "sizing": sizing, "fineness": fineness, "box_mm": box_mm, **r}
                with open(out / "results.jsonl", "a") as fh:
                    fh.write(json.dumps(row, default=float) + "\n")
                print(json.dumps(row, default=float)[:400], flush=True)
        st = {k: (v.get("phase"), v.get("attempt"), v.get("progress"), v.get("last_error")) for k, v in ev.st["cases"].items()}
        print(time.strftime("%H:%M:%S"), st, flush=True)
        if left:
            time.sleep(60)


if __name__ == "__main__":
    main()
