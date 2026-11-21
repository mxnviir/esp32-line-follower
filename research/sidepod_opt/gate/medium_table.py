"""Table of every medium-mesh production result: total, body, wheels, block means, per design."""
import numpy as np, json, glob, os
H = os.path.dirname(os.path.abspath(__file__)) + "/.."
groups = {}
for p in sorted(glob.glob(f"{H}/gate_results_medium/prodcheck_*.json")):
    t = os.path.basename(p)[10:-5]
    d = json.load(open(p))
    f = np.loadtxt(f"{H}/gate_results_medium/forces/prodcheck_{t}/forces.dat"); b = np.loadtxt(f"{H}/gate_results_medium/forces/prodcheck_{t}/forces_car.dat"); w = slice(-400, None)
    g = t.split("~")[0].replace("_p05", "").replace("_m05", "").replace("_p10", "")
    groups.setdefault(g, []).append(d["D20_half_N"] * 1e3)
    print(f"{t:18s} {d['D20_half_N']*1e3:7.2f} conv {d['converged']} body {b[w,1].mean()*1e3:6.2f} (p {b[w,4].mean()*1e3:5.2f}) wheels {(f[w,1].mean()-b[w,1].mean())*1e3:6.2f} lift {f[w,3].mean()*1e3:5.1f} blocks {[round(f[i:i+200,1].mean()*1e3,1) for i in range(1000,2000,200)]}")
print()
ss, dof = 0.0, 0
for g, v in groups.items():
    v = np.array(v); print(f"{g:14s} n={len(v)} mean {v.mean():7.2f} values {np.round(v,2).tolist()}" + (f" sd {v.std(ddof=1):.2f}" if len(v) > 1 else ""))
    if len(v) > 1: ss += ((v - v.mean())**2).sum(); dof += len(v) - 1
if dof: print(f"pooled sigma {np.sqrt(ss/dof):.2f} mN ({dof} dof)")
