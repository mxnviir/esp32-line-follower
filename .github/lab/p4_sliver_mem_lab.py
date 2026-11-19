"""p4_sliver_mem_lab: does Part 4's sliver_wedges (non-convex manifold3d minkowski sums and a
minkowski_difference on the foam band) hold the 13 GB peak of the BODY + PARTS stage?
Wraps joints.sliver_wedges and prints peak RSS before and after it, with the foam's and each
cut's triangle counts and the seconds taken, then runs run_car's build as given.

    python -u ../.github/lab/p4_sliver_mem_lab.py <run_car args>     (from part5-simulation)"""
import resource
import sys
import time
from pathlib import Path

sys.path[:0] = [str(Path.cwd()), str(Path.cwd().parent / "part4-simulation")]
import joints  # noqa: E402

_sw = joints.sliver_wedges


def peak_gb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 ** 2   # Linux: kB


def sliver_wedges(foam, cuts):
    t = time.time()
    print(f"LAB sliver in: peak {peak_gb():.2f} GB, foam faces {len(foam.faces)}, "
          f"cuts { {k: len(c.faces) for k, c in cuts.items()} }", flush=True)
    out = _sw(foam, cuts)
    print(f"LAB sliver out: peak {peak_gb():.2f} GB, {time.time() - t:.1f} s, wedges {sorted(out[0])}", flush=True)
    return out


joints.sliver_wedges = sliver_wedges
import run_car  # noqa: E402

print(f"LAB start: peak {peak_gb():.2f} GB", flush=True)
run_car.main(sys.argv[1:])
