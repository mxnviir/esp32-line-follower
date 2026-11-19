"""Part 3: a start car's compass-map mode jobs as a queue lab job (runs in part5-simulation; prints only).

    python ../.github/lab/p3_map_modes.py '<start json>' <ref> <case_url> <case_sha256>

Prints one `LAB job {...}` line per mode car (map_jobs.py modes)."""
import json
import sys
import tempfile
from pathlib import Path

sys.path[:0] = ['.', '../part3-simulation/checks']
import map_jobs  # noqa: E402

p = Path(tempfile.mkdtemp()) / "start.json"
p.write_text(sys.argv[1])
import io, contextlib  # noqa: E401,E402
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    map_jobs.main(["modes", str(p)] + sys.argv[2:5])
for j in json.loads(buf.getvalue())["jobs"]:
    print("LAB job " + json.dumps(j), flush=True)
