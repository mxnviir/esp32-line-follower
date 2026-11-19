"""The carving loop on the public job queue: one tick reads results, moves every chain, and writes the
next jobs (run on Oracle by cron or at a check-in, never on the PC; the reviewer adds the batch).

    python farm.py init  state.json start1.json start2.json ... --ref <sha>
    python farm.py tick  state.json results.json out_batch.json --shape-sigma-file <Part 2 fine gate json>

A chain's x is the amplitudes (mm) of NMODES bumps at FIXED centres on its start car's surface, so a car
is start edits + one bump edit carrying sum x_k * bump_k; step(x, d, size) = x + size * d.
The compass at x is a full map of the car x (x +- A on every mode, central differences), taken at the
start and after every KEEP only; a rejected round keeps the same car and the same map (map reuse:
recommended, the user's decision). A car is timed once: case ids with the same recipe share its result
(the solver is deterministic, so copies are byte-identical). Every car is sized, carve-json, fine,
4-core hierarchical, legality gated; each result must be legal with matching hashes (carve_loop._t).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402,F401  (part1-4 on sys.path for every caller: part_ranges, beam_support, nose, wings)
import carve_loop as cl  # noqa: E402

REPO = "anasssssssss1/stem-racing-compute"
A_MM, R_MM = 1.0, 10.0
CFD = {"decompose": "hierarchical", "layer_overrides": {"nSurfaceLayers": 0}}


MAP_H = 0.02          # map half-step for a layout or part setting, as a fraction of its search window
PART_FLAG = {"front_wing": "--fwing-json", "rear_wing": "--rwing-json", "nose": "--nose-json",
             "supports": "--support-json"}


def search_vars(centres: list, layout: dict, part_defaults: dict, r_mm: float = R_MM, a_mm: float = A_MM,
                floor: dict | None = None) -> list:
    """Every searched variable. x units: a mode is its bump amplitude in mm; a layout or part setting
    is a fraction of its search window (Part 4 part_ranges.SETTINGS, pattern.LAYOUT), so settings in
    different units are on one scale. Physical value = x0 + x * (hi - lo), kept inside the window."""
    import part_ranges as pr
    import pattern
    v = [{"kind": "mode", "k": k, "h": a_mm, "r": r_mm} for k in range(len(centres))]
    for name, (_, lo, hi) in pattern.LAYOUT.items():
        v.append({"kind": "layout", "key": name, "lo": lo, "hi": hi, "x0": float(layout[name]), "h": MAP_H})
    import param_body as pb
    fd = pb.BodyParams().as_dict()
    for name, (_, lo, hi) in pattern.FLOOR.items():           # the underfloor tunnel (Part 1 ft_*, via --body-json)
        v.append({"kind": "floor", "key": name, "lo": lo, "hi": hi, "x0": float((floor or {}).get(name, fd[name])), "h": MAP_H})
    for part, sets in pr.SETTINGS.items():
        for key, (lo, hi) in sets.items():
            v.append({"kind": "part", "part": part, "key": key, "lo": lo, "hi": hi,
                      "x0": float(part_defaults[part][key]), "h": MAP_H})
    # the support strip on/off (Part 4, option b): x 0 = strip on, 1 = off; never in the gradient,
    # tried each round as its own candidate (flip_candidate)
    v.append({"kind": "switch", "part": "supports", "key": "strip", "h": 0.0})
    return v


def _strip_off(chain: dict, x) -> bool:
    return any(v["kind"] == "switch" and xv >= 0.5 for v, xv in zip(chain.get("vars") or [], x))


def _frozen(chain: dict, k: int) -> bool:
    """Out of the gradient: the switch itself, and strip_w_mm while the strip is off (its value is
    kept, so switching back starts there; with the strip off it changes neither mass nor gates), and the
    tunnel's shape (ft_w, ft_x0, ft_x1, ft_ramp) while ft_h is 0: no tunnel, so its shape is not part of
    the car (Part 1: ft_h 0 gives the identical field); ft_h itself stays in the gradient."""
    v = chain["vars"][k] if chain.get("vars") else {"kind": "mode"}
    if v["kind"] == "switch":
        return True
    if v.get("part") == "supports" and v.get("key") == "strip_w_mm":
        return _strip_off(chain, chain["x"])
    if v["kind"] == "floor" and v["key"] != "ft_h":
        return "floor" not in recipe(chain, chain["x"])
    return False


def _phys(var: dict, xv: float) -> float:
    return round(min(max(var["x0"] + xv * (var["hi"] - var["lo"]), var["lo"]), var["hi"]), 6)


def recipe(chain: dict, x) -> dict:
    """The car at x: its carve recipe (start edits + one bump edit; layout moved) and its part settings."""
    V = chain.get("vars") or [{"kind": "mode", "k": k} for k in range(len(chain["centres"]))]
    bumps, layout = [], dict(chain["start"]["layout"])
    floor = dict(chain["start"].get("floor", {}))
    parts = json.loads(json.dumps(chain["start"].get("parts", {})))   # settings moved by an earlier pass
    for var, xv in zip(V, x):
        if var["kind"] == "mode":
            if xv != 0:
                bumps.append({"c_mm": chain["centres"][var["k"]], "amp_mm": round(float(xv), 6), "sigma_mm": var.get("r", R_MM)})
        elif var["kind"] == "layout":
            layout[var["key"]] = _phys(var, xv)
        elif var["kind"] == "floor":
            if xv != 0:
                floor[var["key"]] = _phys(var, xv)
        elif var["kind"] == "switch":
            sup = parts.setdefault("supports", {})
            if xv >= 0.5:
                sup["strip"] = False
            else:
                sup.pop("strip", None)                               # default: strip on
        elif xv != 0:
            parts.setdefault(var["part"], {})[var["key"]] = _phys(var, xv)
    if parts.get("supports", {}).get("strip") is False:
        parts["supports"].pop("strip_w_mm", None)                    # unused with the strip off: not part of the car
    parts = {p: kv for p, kv in parts.items() if kv}
    edits = chain["start"]["edits"] + ([{"bumps": bumps, "unit": False}] if bumps else [])
    rec = {"layout": layout, "edits": edits}
    if floor.get("ft_h", 0.0) > 0.0:                                  # ft_h 0 is no tunnel: the rest is not part of the car
        rec["floor"] = floor
    if parts:
        rec["parts"] = parts
    return rec


def rid(ref: str, rec: dict) -> str:
    return "p5-" + hashlib.sha256(json.dumps([ref, rec], sort_keys=True).encode()).hexdigest()[:20]


def job(ref: str, rec: dict, base: dict | None, save: bool) -> dict:
    cfd = dict(CFD)
    fetch = []
    if base:                                     # reshape and warm-start from the car this one is near
        cfd.update(morph_from="/tmp/base", warm_from="/tmp/base")
        fetch = [{"url": base["case_url"], "sha256": base.get("case_sha256", ""), "to": "/tmp/base"}]
    carve = {"layout": rec["layout"], "edits": rec["edits"]}
    args = ["--carve-json", json.dumps(carve, sort_keys=True), "--support", "beam", "--cfd", "--cfd-if-legal",
            "--res", "fine", "--np", "4", "--cfd-iters", "1000", "--keep-runs", "--cfd-json", json.dumps(cfd, sort_keys=True)]
    if rec.get("floor"):                                     # the tunnel: param_body ft_* on the carved field
        args += ["--body-json", json.dumps(rec["floor"], sort_keys=True)]
    for part, kv in sorted(rec.get("parts", {}).items()):      # moved part settings; the rest stay at their defaults
        args += [PART_FLAG[part], json.dumps(kv, sort_keys=True)]
    return {"id": rid(ref, rec), "stage": "p5-loop", "prio": 6,
            "recipe": {"repo": REPO, "ref": ref, "args": args, "fetch": fetch, "save_case": save}}


def part_defaults() -> dict:
    """Each searched part's default settings, as run_car builds it when no JSON is given."""
    import dataclasses
    import beam_support as bsm
    import nose as ns
    import wings as wg
    nk = dict(blend_after_ref_a_mm=1.0, root_scale=1.0, material="ABS", wall_mm=1.0)   # run_car's nose defaults
    objs = {"front_wing": wg.FrontWing(), "rear_wing": wg.RearWing(), "nose": ns.NoseCone(**nk),
            "supports": bsm.BeamSupport()}
    return {k: dataclasses.asdict(o) for k, o in objs.items()}


def with_floor(start: dict) -> dict:
    """A start car with its tunnel: pattern.FLOOR_START (ft_h 3 mm, other ft_* at Part 1 defaults) unless
    the start names its own floor (an empty floor = no tunnel)."""
    import pattern
    return {**start, "floor": dict(start.get("floor", pattern.FLOOR_START))}


def init(state_path: Path, starts: list, ref: str, centres: list, full: bool = True, remap: str = "keep") -> dict:
    """full: modes + layout + every part setting; False: modes only."""
    assert len(ref) == 40
    if remap not in ("keep", "round"):
        raise ValueError(f"remap must be keep or round, not {remap!r}")
    st = {"ref": ref, "remap": remap, "chains": []}
    pd = part_defaults() if full else None
    for i, (s, C) in enumerate(zip(starts, centres)):
        s = with_floor(s)
        V = search_vars(C, s["layout"], pd, floor=s["floor"]) if full else [{"kind": "mode", "k": k, "h": A_MM} for k in range(len(C))]
        c = cl.new_chain(i, [0.0] * len(V), 0.5)
        c.update(start=s, centres=C, vars=V, maps={})
        st["chains"].append(c)
    state_path.write_text(json.dumps(st))
    return st


def refine(c: dict, centres: list, r_mm: float, a_mm: float) -> None:
    """The next, finer pass of a converged chain (the 5 mm pass: r_mm 5, centres from car_modes with
    P3_MODE_R_MM=5 and enough modes to cover the body). The car it converged on becomes the new start:
    its bumps fold into the start edits and its moved settings into start parts (the same recipe, so the
    same id: it is not timed again). Search variables are rebuilt around it; x, maps and the step
    state start fresh; the finished pass is kept under \"passes\"."""
    if c["status"] != "converged":
        raise ValueError(f"chain {c['id']} is {c['status']}, only a converged chain is refined")
    rec = recipe(c, c["x"])
    pd = part_defaults()
    for part, kv in rec.get("parts", {}).items():
        pd[part].update(kv)
    for v, xv in zip(c.get("vars") or [], c["x"]):              # strip width kept while the strip is off
        if v.get("part") == "supports" and v.get("key") == "strip_w_mm":
            pd["supports"]["strip_w_mm"] = _phys(v, xv)
    start = {**{k: v for k, v in c["start"].items() if k not in ("layout", "edits", "parts")},
             "layout": rec["layout"], "edits": rec["edits"], **({"parts": rec["parts"]} if rec.get("parts") else {})}
    if rec.get("floor"):
        start["floor"] = rec["floor"]
    if c.get("vars") and any(v["kind"] != "mode" for v in c["vars"]):
        V = search_vars(centres, start["layout"], pd, r_mm, a_mm, start.get("floor"))
    else:
        V = [{"kind": "mode", "k": k, "h": a_mm, "r": r_mm} for k in range(len(centres))]
    off = _strip_off(c, c["x"])
    done = {k: c[k] for k in ("x", "history", "round", "status", "start", "centres", "d10_s") if k in c}
    passes = c.get("passes", []) + [done]
    fresh = cl.new_chain(c["id"], [0.0] * len(V), c["scale0"])
    c.clear()
    c.update(fresh, start=start, centres=centres, vars=V, maps={}, passes=passes)
    c["x"] = [1.0 if (v["kind"] == "switch" and off) else 0.0 for v in V]   # the strip stays as it was
    assert recipe(c, c["x"]) == rec, "the refined start is not the car the chain converged on"


def _clip(chains: list, x_from, x_new) -> list:
    """Keep every layout and part setting inside its search window (rule edges inside the window are
    the referee's: an illegal car is refused, never kept). ponytail: window clip, not Part 4's
    part_ranges.project, which needs the car's built body; wire project() in once a tick can build it."""
    c = next(c for c in chains if json.dumps([round(v, 6) for v in c["x"]]) == json.dumps([round(v, 6) for v in x_from]))
    out = []
    k_from = list(x_from)
    for var, v in zip(c.get("vars") or [{"kind": "mode"}] * len(x_new), x_new):
        if var["kind"] == "switch" or (var["kind"] != "mode" and _frozen(c, len(out))):
            v = k_from[len(out)]                                   # not moved by a gradient step
        elif var["kind"] != "mode":
            w = var["hi"] - var["lo"]
            v = min(max(v, (var["lo"] - var["x0"]) / w), (var["hi"] - var["x0"]) / w)
        out.append(float(v))
    return out



_CARS: dict = {}
_BOUNDS: dict = {}                     # last bounds per chain (tuple keys: kept out of the saved state)


def _part_objs(c: dict, x) -> dict:
    """{part: dataclass instance} of the car at x (defaults + its moved settings)."""
    import beam_support as bsm
    import nose as ns
    import wings as wg
    moved = recipe(c, x).get("parts", {})
    nk = dict(blend_after_ref_a_mm=1.0, root_scale=1.0, material="ABS", wall_mm=1.0)
    make = {"front_wing": wg.FrontWing, "rear_wing": wg.RearWing,
            "nose": lambda **k: ns.NoseCone(**{**nk, **k}), "supports": bsm.BeamSupport}
    return {p: make[p](**moved.get(p, {})) for p in make}


def _project(chains: list, x_from, x_new) -> list:
    """Part 4's projection (part_ranges.bounds/project, the referee's own gates) on the CURRENT car as
    built (its body_half.stl from the queue): every part setting of the step is moved only as far as
    stays legal. Without the body (an old result) the window clip alone stands."""
    key = json.dumps([round(v, 6) for v in x_from])
    c = next(c for c in chains if json.dumps([round(v, 6) for v in c["x"]]) == key)
    if not c.get("_body_url") or not c.get("vars"):
        return list(x_new)
    import part_ranges as pr
    import trimesh
    import urllib.request
    if c["_body_url"] not in _CARS:
        p = Path(f"/tmp/body-{c['id']}-{abs(hash(c['_body_url']))}.stl")
        urllib.request.urlretrieve(c["_body_url"], p)
        lay = recipe(c, x_from)["layout"]
        _CARS[c["_body_url"]] = pr.Car(body=trimesh.load(str(p), force="mesh"),
                                       x_front_mm=lay["x_front"], W_mm=lay["W"])
    car = _CARS[c["_body_url"]]
    cur = _part_objs(c, x_from)
    b = pr.bounds(car, cur, prev=_BOUNDS.get(c["id"]))
    _BOUNDS[c["id"]] = b
    out = pr.project(car, cur, _part_objs(c, x_new), b)
    x = list(x_new)
    for j, var in enumerate(c["vars"]):
        if var["kind"] == "part":
            x[j] = float((getattr(out[var["part"]], var["key"]) - var["x0"]) / (var["hi"] - var["lo"]))
        elif var["kind"] == "switch":
            x[j] = 0.0 if out["supports"].strip else 1.0                # project() takes a switch only where legal
    return x

def _val(results: dict, ref: str, rec: dict):
    r = results.get(rid(ref, rec))
    return None if r is None or r.get("status") != "done" else r["result"]


def tick(st: dict, results: dict, shape_sigma: float, side_check=None) -> list:
    """Move every chain as far as the results allow; return the jobs still missing.

    side_check(c, k, amp) -> bool, optional (the reviewer's tick on the server passes one built on
    map_jobs.side_moves): False = that side of mode k cannot move on the current car, so it is the
    current car itself and no map car is queued for it. After timing, a side whose field hash is the
    current car's is the current car too (exact). A mode slope uses only the sides that moved
    (one-sided if one did, 0 and no car if none: a dead mode); as with a clamped window edge, a side
    that did not move would otherwise halve the slope."""
    ref, want = st["ref"], {}
    ready = []
    for c in st["chains"]:
        if c["status"] != "running":
            continue
        key = json.dumps([round(v, 6) for v in c["x"]])
        cur = recipe(c, c["x"])
        base = _val(results, ref, cur)
        if base is None:
            want[rid(ref, cur)] = job(ref, cur, None, True)          # the current car, its case saved
            continue
        remap = st.get("remap", "keep")                              # "keep": map at the start and after a keep; "round": every round
        if key not in c["maps"] or (remap == "round" and c.get("map_round") != c["round"]):
            g, missing = [], False
            for k in range(len(c["x"])):
                if c.get("vars") and _frozen(c, k):
                    g.append(0.0); continue                          # out of the gradient (strip switch; strip width while off)
                var = c["vars"][k] if c.get("vars") else {"kind": "mode", "h": A_MM}
                T, h = [], var["h"]
                if var["kind"] == "mode":
                    step = 2 * h
                else:                                                # a window edge clamps a side to the same value:
                    step = (_phys(var, c["x"][k] + h) - _phys(var, c["x"][k] - h)) / (var["hi"] - var["lo"])
                    if step == 0:
                        g.append(0.0); continue                      # both sides clamp to one car: no slope, no car
                T0, moved = cl._t(base, True), 0
                for s in (1, -1):
                    if var["kind"] == "mode" and side_check is not None and not side_check(c, k, s * h):
                        T.append(T0)                                 # this side cannot move: it is the current car
                        continue
                    x = list(c["x"]); x[k] += s * h
                    rec = recipe(c, x)
                    v = _val(results, ref, rec)
                    if v is None:
                        want[rid(ref, rec)] = job(ref, rec, base, False); missing = True
                    elif var["kind"] == "mode" and v.get("field_sha") and v.get("field_sha") == base.get("field_sha"):
                        T.append(T0)                                 # timed, but the same field as the current car
                    else:
                        T.append(cl._t(v)); moved += 1
                if var["kind"] == "mode":
                    step = h * moved                                 # only the sides that moved
                if len(T) == 2:
                    g.append((T[0] - T[1]) / step if step else 0.0)  # the step actually taken, in x units
            if missing:
                continue
            c["maps"] = {key: g}                                     # only the current car's map is kept
            modes = [abs(gk) * 2 * c["vars"][k]["h"] for k, gk in enumerate(g) if c["vars"][k]["kind"] == "mode"]
            c.setdefault("d10_s", float(np.median(modes)) if modes else None)   # |T+ - T-| median of the first (start) map
            c["map_round"] = c["round"]
        if base.get("body_url"):
            c["_body_url"] = base["body_url"]                         # the current car as built, for project()
        ready.append(c)
    view = {"chains": ready}
    cl.plan(view, lambda x: np.asarray(next(c["maps"][json.dumps([round(v, 6) for v in x])]
                                            for c in ready if json.dumps([round(v, 6) for v in x]) in c["maps"])),
            lambda x, d, size: _project(ready, x, _clip(ready, x, np.asarray(x) + size * np.asarray(d))))
    for c in ready:                                                  # Part 4 option b: the strip flipped, numbers unchanged
        if c["status"] == "running" and c["phase"] == "search" and c["cands"] and "0" not in c["cands"] and any(v["kind"] == "switch" for v in c.get("vars") or []):
            j = next(i for i, v in enumerate(c["vars"]) if v["kind"] == "switch")
            flip = list(c["x"]); flip[j] = 0.0 if flip[j] >= 0.5 else 1.0
            flip = _project(ready, c["x"], flip)
            if recipe(c, flip) != recipe(c, c["x"]):                  # project() refused the switch: nothing to try
                c["cands"]["0"] = flip                               # key "0": size 0, no gradient step; counted in the bar's k
    res = {}
    for case_id, (x, _) in cl.needed(view).items():
        c = next(c for c in ready if case_id.split("_")[1] == f"c{c['id']}")
        rec = recipe(c, x)
        v = _val(results, ref, rec)
        if v is None:
            want[rid(ref, rec)] = job(ref, rec, _val(results, ref, recipe(c, c["x"])), True)
        else:
            res[case_id] = v                                         # every copy of one car gets its one result
    cl.advance(view, res, prior_sigma=shape_sigma, shape_sigma=shape_sigma)
    return list(want.values())


LIN_MODES = (0, 1, 2)                  # the first three 5 mm modes (farthest-point order: spread over the body)


def linearity_cars(c: dict, a5: float, modes=LIN_MODES) -> dict:
    """The 5 mm linearity check on a refined chain's start car: {(mode, amp): recipe} at +-a5 and
    +-a5/2 on each mode (each one bump on the car the chain converged on)."""
    idx = [i for i, v in enumerate(c["vars"]) if v["kind"] == "mode"]
    out = {}
    for k in modes:
        for amp in (a5, -a5, a5 / 2, -a5 / 2):
            x = list(c["x"])
            x[idx[k]] += amp
            out[(k, amp)] = recipe(c, x)
    return out


def lin_band(shape_sigma: float, n_modes: int = len(LIN_MODES), alpha: float = 0.05) -> float:
    """The linearity band: D = dT(+-a5) - 2 dT(+-a5/2) has SD sqrt(2 + 8) sigma = sqrt(10) sigma (four
    independent timings, the half pair counted twice); z two-sided Bonferroni over the modes at alpha
    family-wise (3 modes, 5 %: z = 2.394), so a linear car passes all modes 95 % of the time."""
    from statistics import NormalDist
    return NormalDist().inv_cdf(1 - alpha / (2 * n_modes)) * 10 ** 0.5 * shape_sigma


def linearity_ok(c: dict, ref: str, results: dict, a5: float, shape_sigma: float, modes=LIN_MODES):
    """(None, []) until every check car is in; else (passed, rows). Passed: on every mode the pair
    T(+a5) - T(-a5) and twice T(+a5/2) - T(-a5/2) agree within lin_band(shape_sigma) (a refused or
    illegal car fails it)."""
    assert shape_sigma > 0
    cars = linearity_cars(c, a5, modes)
    T = {}
    for key, rec in cars.items():
        v = _val(results, ref, rec)
        if v is None:
            return None, []
        T[key] = cl._t(v)
    tol = lin_band(shape_sigma, len(modes))
    rows = []
    for k in modes:
        full = T[(k, a5)] - T[(k, -a5)]
        half = T[(k, a5 / 2)] - T[(k, -a5 / 2)]
        diff = abs(full - 2 * half)
        rows.append({"mode": k, "dT_full_s": full, "dT_half_x2_s": 2 * half, "diff_s": diff, "tol_s": tol,
                     "ok": diff <= tol})
    return all(r["ok"] for r in rows), rows



def main(argv):
    if argv[0] == "init":                       # centres on each start car's own surface (needs the cutter)
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "part3-simulation" / "checks"))
        import map_jobs
        starts = [json.loads(Path(p).read_text()) for p in argv[2:argv.index("--ref")]]
        init(Path(argv[1]), starts, argv[argv.index("--ref") + 1], [map_jobs.centres_mm(s) for s in starts])
    elif argv[0] == "tick":
        st = json.loads(Path(argv[1]).read_text())
        results = json.loads(Path(argv[2]).read_text())
        shape = json.loads(Path(argv[argv.index("--shape-sigma-file") + 1]).read_text())["shape_sigma_s"]
        jobs = tick(st, results, float(shape))
        Path(argv[1]).write_text(json.dumps(st))
        Path(argv[3]).write_text(json.dumps({"batch": {"id": f"p5-loop-{len(jobs)}", "stage": "p5-loop",
                                                       "cars": len(jobs)}, "jobs": jobs}, indent=1))
        print(f"LAB farm: {len(jobs)} jobs; chains " + ", ".join(f"{c['id']} {c['status']} r{c['round']}"
                                                                  for c in st["chains"]))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
