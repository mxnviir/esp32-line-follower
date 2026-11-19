"""Part 4 lab, start reference car: (1) per sizing pass, what pod_joint did at each axle
(cavity hollowed or solid, window cut or not, shell and pocket volumes, extra plastic);
(2) for every joint, its pocket's distance to the machined body's thinnest wall, so the
foam sliver (0.07 mm at x 33, |y| 7.3, z 5.8) can be named."""
import sys
from pathlib import Path

sys.path[:0] = [str(Path.cwd()), str(Path.cwd().parent / "part4-simulation")]
import numpy as np
import trimesh

import joints


def _mem():
    """(now, peak since the last reset) RSS in GB from /proc (C++ arrays included); the peak
    is reset after reading, so each step reports its own high-water mark."""
    kb = {}
    for line in open("/proc/self/status"):
        if line.startswith(("VmRSS", "VmHWM")):
            kb[line.split(":")[0]] = int(line.split()[1])
    try:
        open("/proc/self/clear_refs", "w").write("5")   # resets VmHWM
    except OSError:
        pass
    return kb.get("VmRSS", 0) / 2**20, kb.get("VmHWM", 0) / 2**20


def _measured(name, f):
    def g(*a, **k):
        before = _mem()[0]
        try:
            return f(*a, **k)
        finally:
            now, peak = _mem()
            print(f"MEM {name}: before {before:.2f} GB, peak {peak:.2f} GB, after {now:.2f} GB", flush=True)
    return g


# Part 4's own steps; the body build before them is Part 1's
for _n in ("pod_joint", "sliver_wedges", "join_wedge", "make_all"):
    setattr(joints, _n, _measured(_n, getattr(joints, _n)))

_pod = joints.pod_joint


def pod_joint(part, body_half, channels, keep_out=None):
    j = _pod(part, body_half, channels, keep_out)
    if j is not None:
        w = j.printed_whole
        print(f"PODJOINT channels { {k: round(v['length_mm'], 2) for k, v in channels.items()} } "
              f"floors { {k: round(v['z_floor_mm'], 3) for k, v in channels.items()} } "
              f"pocket_cm3 {j.pocket_cm3:.3f} extra_plastic_cm3 {j.extra_plastic_cm3:.3f} "
              f"whole_cm3 {abs(w.volume) * 1e6:.3f} pieces {len(w.split(only_watertight=False))}", flush=True)
    return j


joints.pod_joint = pod_joint
_make = joints.make_all


def make_all(body_half, assembly, x_ref_a_mm, rear_face_mm, out_dir=None):
    rep = _make(body_half, assembly, x_ref_a_mm, rear_face_mm, out_dir)
    print(f"SLIVER wedges {rep.get('sliver_wedges')}", flush=True)
    mb = rep["manufactured"].get("machined_body", {}).get("file")
    if mb:
        import legality as lg
        t, where = lg._min_wall_mm(mb, n=8000)
        print(f"MACHINED min wall {t:.3f} mm at {where}", flush=True)
        if where is not None:
            p = np.array(where) / 1e3
            for jn in rep.get("joint_names", []) or []:
                pass
            for k, v in rep["manufactured"].items():
                if "file" in v and k != "machined_body":
                    m = trimesh.load(v["file"], force="mesh")
                    d = trimesh.proximity.closest_point(m, [np.array(where)])[1][0]
                    print(f"  nearest part {k}: {d:.3f} mm", flush=True)
    return rep


joints.make_all = make_all
import run_car
run_car.main(["--out", "../out/start", "--body-json", "{}"])
