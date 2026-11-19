"""Part 3: start the carving loop and write chain 1's full compass map (c1-scan) (lab script).

    python ../.github/lab/p3_farm_init.py <ref> <results_url> <start json>... [--remap keep|round]

Run by the reviewer on the server, not a queue job: /api/results is local-only on the server and
ADMIN_KEY must never be in a recipe.

Builds each start car's mode centres (the cutter), makes the loop state (96 modes + layout + part
settings), then runs one tick: the start car's result is found by its id (the step-proof base job is the
same car, same id), so the tick asks for the full map, 2 cars per variable, warm-started from its saved
case. Prints `LAB state {...}` (store it for p3_farm_tick.py) and one `LAB job {...}` per car."""
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path[:0] = ['.', '../part3-simulation/checks']
import farm  # noqa: E402
import map_jobs  # noqa: E402

a = sys.argv[1:]
remap = a[a.index("--remap") + 1] if "--remap" in a else "keep"
a = [x for i, x in enumerate(a) if x != "--remap" and (i == 0 or a[i - 1] != "--remap")]
ref, results_url, starts = a[0], a[1], [json.loads(s) for s in a[2:]]
req = urllib.request.Request(results_url, headers={"X-Admin-Key": os.environ["ADMIN_KEY"]} if os.environ.get("ADMIN_KEY") else {})
results = json.loads(urllib.request.urlopen(req, timeout=120).read())
st = farm.init(Path(tempfile.mkdtemp()) / "state.json", starts, ref, [map_jobs.centres_mm(s) for s in starts], remap=remap)
jobs = farm.tick(st, results, 1.0)        # no step is taken before every map is in, so sigma is unused here
assert all(c["round"] == 0 for c in st["chains"]), "a step was taken at init"
print("LAB state " + json.dumps(st), flush=True)
for j in jobs:
    print("LAB job " + json.dumps(j), flush=True)
print(f"LAB init: {len(jobs)} jobs, remap={remap}; vars per chain " + ", ".join(str(len(c['vars'])) for c in st["chains"]), flush=True)
