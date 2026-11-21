"""Tables and pass marks for the fine-mesh campaign (marks fixed in ROUTES.md 2026-11-21 13:00, before results).

    python fine_campaign/summarize.py <TAG>      (TAG = fine | resolved | ...; reads gate_results_<TAG>/)
Compares with the medium and coarse results already in the repo. Drag = half car, production model, mN.
"""
import json, sys
from pathlib import Path
import numpy as np

SP = Path(__file__).resolve().parents[1]
TAG = sys.argv[1] if len(sys.argv) > 1 else "fine"
SIGMA_FLOOR = 0.3                                   # mN; no estimate of scatter is allowed below this

MEDIUM = {"team": "team", "team_p05": "team_p05", "team_m05": "team_m05", "groove": "channel", "groove_p05": "channel_p05",
          "groove_m05": "channel_m05", "adjoint8": "adjoint_it8", "adjoint8_p05": "adjoint_it8_p05",
          "adjoint8_m05": "adjoint_it8_m05", "win3": "win3", "nopod": "nopod", "team_p10": "team_p10"}
COARSE = {"team": "seed_fresh", "team_p05": "scatter_seed_p05", "team_m05": "scatter_seed_m05", "team_p10": "scatter_seed_p10",
          "groove": "concept_channel_fresh", "adjoint8": "best_it8", "win3": "concept_win3_fresh", "win5": "concept_win5_fresh",
          "nopod": "lean_seed_fresh", "blend50": "concept_blend50_fresh", "blend75": "concept_blend75_fresh"}
ORDER = ["team", "groove", "adjoint8", "win3", "win5", "nopod", "blend50", "blend75"]
design = lambda t: t.split("~")[0].split("_p0")[0].split("_m0")[0]


def load(res_dir, names):
    """{campaign tag: (total, body, wheels)} from prodcheck JSONs + force histories (last 20 %)."""
    out = {}
    for tag, name in names.items():
        j = res_dir / f"prodcheck_{name}.json"
        if not j.exists():
            continue
        d = json.loads(j.read_text())
        tot, body = d["D20_half_N"] * 1e3, float("nan")
        fc = res_dir / "forces" / f"prodcheck_{name}" / "forces_car.dat"
        if fc.exists():
            b = np.loadtxt(fc, comments="#"); body = b[-len(b) // 5:, 1].mean() * 1e3
        out[tag] = {"D": tot, "body": body, "wheels": tot - body, "conv": d.get("converged"), "cells": d.get("n_cells"),
                    "ypmax": d.get("y_plus_max"), "wall_s": d.get("wall_s"), "res": res_dir}
    return out


def groups(rows):
    g = {}
    for t, r in rows.items():
        g.setdefault(design(t), []).append(r)
    return g


def pooled(g):
    ss, dof = 0.0, 0
    for v in g.values():
        x = np.array([r["D"] for r in v])
        if len(x) > 1:
            ss += ((x - x.mean()) ** 2).sum(); dof += len(x) - 1
    return (max(np.sqrt(ss / dof), SIGMA_FLOOR) if dof else None), dof


def stats(rows):
    g = groups(rows); s, dof = pooled(g)
    st = {k: {"n": len(v), "mean": np.mean([r["D"] for r in v]), "body": np.nanmean([r["body"] for r in v]),
              "wheels": np.nanmean([r["wheels"] for r in v]), "values": [round(r["D"], 2) for r in v]} for k, v in g.items()}
    for k, v in st.items():
        if "team" in st and k != "team" and s:
            v["delta"] = v["mean"] - st["team"]["mean"]
            v["se"] = s * np.sqrt(1 / v["n"] + 1 / st["team"]["n"])
    return st, s, dof


def main():
    res_dir = SP / f"gate_results_{TAG}"
    alias = {v: k for k, v in MEDIUM.items()}               # medium results of 2026-11-21 used older names
    names = {alias.get(t, t): t for t in [p.stem[10:] for p in res_dir.glob("prodcheck_*.json")] if t != "stateA"}
    R = stats(load(res_dir, names)); M = stats(load(SP / "gate_results_medium", MEDIUM)); C = stats(load(SP / "gate_results_coarse", COARSE))
    print(f"# Fine-mesh campaign summary: {TAG}\n")
    rows = load(res_dir, names)
    if rows:
        print("## Runs\n\n| run | drag | body | wheels | converged | cells | y+ max | wall time |\n|---|---|---|---|---|---|---|---|")
        for t, r in sorted(rows.items()):
            res = res_dir / f"resources_{t}.json"
            peak = json.loads(res.read_text()).get("peak_used_MB_whole_machine") if res.exists() else None
            print(f"| {t} | {r['D']:.2f} | {r['body']:.1f} | {r['wheels']:.1f} | {r['conv']} | {r['cells']} | {r['ypmax'] and round(r['ypmax'], 1)} | "
                  f"{(r['wall_s'] or 0) / 3600:.1f} h{f', peak {peak / 1024:.1f} GB' if peak else ''} |")
    print(f"\n## Per design (difference vs the team pod; SE from the pooled mesh-to-mesh sigma)\n")
    print(f"Scatter sigma: {TAG} {R[1] and round(R[1], 2)} mN ({R[2]} dof); medium {M[1] and round(M[1], 2)} ({M[2]} dof); coarse {C[1] and round(C[1], 2)} ({C[2]} dof)\n")
    print(f"| design | {TAG}: meshes, mean | {TAG} vs team | medium vs team | coarse vs team | body {TAG} / medium / coarse |\n|---|---|---|---|---|---|")
    fmt = lambda st, k: (f"{st[k]['delta']:+.1f} ± {st[k]['se']:.1f}" if k in st and "delta" in st[k] else ("0" if k == "team" and k in st else "–"))
    for k in ORDER:
        if k not in R[0] and k not in M[0] and k not in C[0]:
            continue
        r = R[0].get(k)
        cell = f"{r['n']}, {r['mean']:.2f}" if r else "–"
        print(f"| {k} | {cell} | {fmt(R[0], k)} | {fmt(M[0], k)} | {fmt(C[0], k)} | "
              + " / ".join(f"{s[0][k]['body']:.1f}" if k in s[0] else "–" for s in (R, M, C)) + " |")
    st, s = R[0], R[1]
    print("\n## Pass marks (fixed 2026-11-21 13:00)\n")
    def verdict(name, ok, why):
        print(f"- **{name}: {'PASS' if ok else 'FAIL' if ok is not None else 'not yet testable'}**: {why}")
    if "team" in st and "team" in M[0]:
        db = st["team"]["body"] - M[0]["team"]["body"]
        diffs = [(k, st[k]["delta"], M[0][k]["delta"], st[k]["se"]) for k in st if k in M[0] and "delta" in st[k] and "delta" in M[0][k]]
        ok = abs(db) <= 3.0 and all(abs(a - b) <= max(2.0, 3 * se) for _, a, b, se in diffs) if diffs else None
        verdict("M1, medium is adequate for scoring", ok, f"team body drag {TAG} − medium = {db:+.1f} mN (mark ±3); "
                + ", ".join(f"{k}: {a:+.1f} vs medium {b:+.1f}" for k, a, b, _ in diffs))
    verdict("M2, single runs can score designs", (s <= 2.0) if s else None, f"pooled sigma {s and round(s, 2)} mN (mark ≤ 2)")
    def sig(k, sign):   # significant in the given direction
        return (sign * st[k]["delta"] > 3 * st[k]["se"]) if k in st and "delta" in st[k] else None
    verdict("C1, pod beats no pod by ≥ 15 mN", (st["nopod"]["delta"] >= 15) if "nopod" in st and "delta" in st["nopod"] else None,
            f"no pod {fmt(st, 'nopod')} mN")
    v = None
    if "blend50" in st and "nopod" in st and s:
        se = s * np.sqrt(1 / st["blend50"]["n"] + 1 / st["nopod"]["n"]); dd = st["blend50"]["mean"] - st["nopod"]["mean"]
        v = dd > 3 * se; why = f"blend50 − no pod = {dd:+.1f} ± {se:.1f} mN (valley if > +3 SE)"
    else:
        why = "needs blend50 and nopod"
    verdict("C2, the valley between no pod and pod exists", v, why)
    verdict("C3, the groove helps", sig("groove", -1), f"groove {fmt(st, 'groove')} mN (holds if < −3 SE)")
    w = (not sig("win3", -1)) if sig("win3", -1) is not None else None
    verdict("C4, windows don't help", w, f"3 windows {fmt(st, 'win3')}, 5 windows {fmt(st, 'win5')} mN (overturned if < −3 SE)")
    a = None if "adjoint8" not in st or "delta" not in st["adjoint8"] else not sig("adjoint8", -1)
    verdict("C5, the coarse adjoint design has no real gain", a, f"design 8 {fmt(st, 'adjoint8')} mN (a real gain if < −3 SE)")
    up = SP / f"gate_results_{TAG}_up" / "base.json"
    if up.exists():
        b = json.loads(up.read_text())
        verdict("A1, the steady model goes steady on this mesh", b.get("steady_pass"),
                f"block means span {b.get('block_span_last1000_mN'):.3f} mN over the last 1,000 iterations (mark ≤ 0.10)")
    pj = SP / f"gate_results_{TAG}_up" / "dafoam_pair_judge.json"
    if pj.exists():
        print(f"- A2, adjoint vs bumps: see {pj.name}")


if __name__ == "__main__":
    main()
