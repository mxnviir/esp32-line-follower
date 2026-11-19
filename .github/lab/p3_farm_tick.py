"""Part 3 carving-loop tick as a queue lab job (runs in part5-simulation; prints only).

    python ../.github/lab/p3_farm_tick.py <state_url> <results_url> <sigma_url>

Reads the loop state, the queue's results (env ADMIN_KEY sent as X-Admin-Key if set) and Part 2's fine
noise (key shape_sigma_s), moves every chain, then prints `LAB state {...}` (the new state, for the
reviewer to store) and one `LAB job {...}` line per car still to time."""
import json
import os
import sys
import urllib.request

sys.path[:0] = ['.']
import farm  # noqa: E402


def get(url):
    req = urllib.request.Request(url, headers={"X-Admin-Key": os.environ["ADMIN_KEY"]} if os.environ.get("ADMIN_KEY") else {})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


state, results, sigma = (get(u) for u in sys.argv[1:4])
_cars = {}


def side_check(c, k, amp):
    """map_jobs.side_moves on the current car, carved once per car (the dead-mode screen)."""
    sys.path.insert(0, "../part3-simulation/checks")
    import carve
    import map_jobs
    rec = farm.recipe(c, c["x"])
    key = json.dumps(rec, sort_keys=True)
    if key not in _cars:
        _cars[key] = carve.carve(rec["layout"], rec["edits"])[0]
    v = c["vars"][k]
    return map_jobs.side_moves(_cars[key], c["centres"][v["k"]], v.get("r", farm.R_MM), amp) > 0


jobs = farm.tick(state, results, float(sigma["shape_sigma_s"]), side_check=side_check)
print("LAB state " + json.dumps(state), flush=True)
for j in jobs:
    print("LAB job " + json.dumps(j), flush=True)
print(f"LAB farm: {len(jobs)} jobs; chains " + ", ".join(f"{c['id']} {c['status']} r{c['round']}" for c in state["chains"]), flush=True)
