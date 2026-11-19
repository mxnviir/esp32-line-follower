"""The fresh stress cars as build-only queue jobs: the same cars `stress_cars.py --carve --seed S`
would build (random_carve, carve_edits, the same part flags), written as run_car arguments.

    python checks/stress_jobs.py --seed 9000 --n 180 --ref <sha> > ../../jobs/part4/b-p4-fresh180.json

One difference from stress_cars: run_car --carve-json stops on a refused cut, where stress_cars
logged the refusal and kept the car. A refused cut shows up as a failed job with its reason."""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pattern  # noqa: E402
import stress_cars as sc  # noqa: E402


def job_args(c: dict) -> list:
    lay = {"W": 120.3, "x_front": 46.0, "d_halo": 43.72,
           **{k: v for k, v in c.get("layout", {}).items() if k in ("W", "x_front", "d_halo")}}
    args = ["--skin-mm", "0", "--support", "beam",
            "--carve-json", json.dumps({"layout": lay, "edits": sc.carve_edits(c)})]
    for part, flag in pattern.PART_FLAGS.items():
        if c["car"]["parts"].get(part):
            args += [flag, json.dumps(c["car"]["parts"][part])]
    return args


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--n", type=int, default=180)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--repo", default="anasssssssss1/stem-racing-compute")
    a = ap.parse_args()
    import param_body as pb
    sc.SETTINGS = (pattern.LOFT + [f"mode{i}" for i in range(pb.N_MODES)] + list(pattern.FLOOR)
                   + list(pattern.PARTS))                     # as stress_cars.main sets it
    rng = random.Random(a.seed)
    jobs = [{"id": f"p4-fresh-{a.seed}-{i}", "stage": "p4-fresh", "prio": 5,
             "recipe": {"repo": a.repo, "ref": a.ref, "args": job_args(sc.random_carve(rng)),
                        "fetch": [], "save_case": False}}
            for i in range(a.n)]
    print(json.dumps({"batch": {"id": f"b-p4-fresh{a.n}", "stage": "p4-fresh", "cars": a.n,
                                "label": f"Part 4: fresh {a.n} carved cars on the final cutter, build-only (seed {a.seed})"},
                      "jobs": jobs,
                      "priority_note": "After the cutter fixes; before cars=true and the Part 4 tag."}, indent=0))


if __name__ == "__main__":
    main()
