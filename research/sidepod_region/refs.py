"""Reference sidepods, each measured from frozen state A and from state B (the difference is
the start-state noise), with the run length the methods use and a 3x longer one."""
import json, sys, numpy as np
from pathlib import Path
from region import Car
from tunnel import CarTunnel
from score import Scorer
import run_one

HERE = Path(__file__).resolve().parent
car = Car(); tun = CarTunnel(car)
A, B = np.load(HERE / "results/state_A.npy"), np.load(HERE / "results/state_B.npy")
S, AV = run_one.STEPS, run_one.AVG_FROM


def designs():
    X, Y, Z = car.X, car.Y, car.Z
    d = {"original": car.original.copy()}
    d["lean (cargo only)"] = car.finish(-np.ones(X.shape))
    # a designer's teardrop pod: round nose at the front, tapering to the rear wheel
    t = np.clip((152 - X) / 95.0, 0, 1)                      # 0 at the nose, 1 at the tail
    half_w = 13 * np.sqrt(np.clip(t / 0.25, 0, 1)) * np.where(t > 0.25, 1 - 0.75 * (t - 0.25) / 0.75, 1)
    half_h = 10 * np.sqrt(np.clip(t / 0.25, 0, 1)) * np.where(t > 0.25, 1 - 0.5 * (t - 0.25) / 0.75, 1)
    pod = ((Y - 19) / np.maximum(half_w, 1e-6)) ** 2 + ((Z - 13) / np.maximum(half_h, 1e-6)) ** 2 <= 1
    d["hand teardrop pods"] = car.finish(np.where(pod, 1.0, -1.0))
    d["whole region solid"] = car.finish(np.ones(X.shape))
    return d


if __name__ == "__main__":
    out = {}
    D = designs()
    # first the original from A to set the scale
    bp = HERE / "results/base.json"
    if bp.exists():
        base = json.loads(bp.read_text())
    else:
        r = tun.measure(car.original, S, AV, warm=A)
        base = {"drag_A": float(r["drag"]), "lift_A": float(r["lift"])}
        bp.write_text(json.dumps(base))
    sc = Scorer(car, base["drag_A"], base["lift_A"])
    for name, body in D.items():
        if name == 'original' and len(sys.argv) > 1:
            continue
        m = sc.mass(body)
        row = dict(mass=m)
        for st, warm in (("A", A), ("B", B)):
            r = tun.measure(body, S, AV, warm=warm)
            row[st] = dict(drag=float(r["drag"]), lift=float(r["lift"]), T=sc.race(r["drag"], r["lift"], m)[0])
        r = tun.measure(body, 2 * S, S, warm=A)
        row["A_long"] = dict(drag=float(r["drag"]), lift=float(r["lift"]), T=sc.race(r["drag"], r["lift"], m)[0])
        out[name] = row
        np.save(HERE / f"results/ref_{name.split()[0]}.npy", body)
        print(name, json.dumps({k: (v if k != "mass" else {kk: round(float(vv), 2) for kk, vv in v.items()}) for k, v in row.items()}), flush=True)
    (HERE / "results/refs.json").write_text(json.dumps(out, indent=1, default=float))
