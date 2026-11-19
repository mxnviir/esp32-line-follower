"""The queue driver on a fake queue: every car is timed once (copies share one result), maps are taken
only at the start and after a keep, and chains on a deterministic stopwatch with shape noise reach the
minimum of a bowl without keeping a step that is not faster beyond the bar."""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

import farm

REF = "0" * 40


def _start(i):
    return {"name": f"c{i}", "layout": {"W": 120.3, "x_front": 46.0, "d_halo": 43.72}, "edits": []}


def _amps(rec):
    b = rec["edits"][-1]["bumps"] if rec["edits"] else []
    return b


def test_farm_on_a_fake_queue(tmp_path):
    centres = [[float(k), 0.0, 0.0] for k in range(3)]
    st = farm.init(tmp_path / "s.json", [_start(0), _start(1)], REF, [centres, centres], full=False)
    opt = np.array([2.0, -1.0, 0.5])
    shape = 0.3e-3
    timed = {}

    def T(rec):
        x = np.zeros(3)
        for b in _amps(rec):
            x[int(b["c_mm"][0])] = b["amp_mm"]
        h = int(hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).hexdigest()[:8], 16)
        return 1.0 + 1e-3 * float(np.sum((x - opt) ** 2)) + shape * np.random.default_rng(h).normal()

    results = {}
    for _ in range(3000):
        jobs = farm.tick(st, results, shape)
        if not jobs and all(c["status"] != "running" for c in st["chains"]):
            break
        for j in jobs:
            rec = json.loads(j["recipe"]["args"][1])
            assert j["id"] not in timed, "a car was asked for twice"
            timed[j["id"]] = 1
            results[j["id"]] = {"status": "done", "result": {"legal": True, "T_s": T(rec), "expect_field_sha": j["id"],
                                                             "field_sha": j["id"], "judged_field_sha": j["id"],
                                                             "case_url": "u"}}
    for c in st["chains"]:
        assert c["status"] != "running"
        assert len(c["maps"]) <= 1
        x = np.asarray(c["x"])
        assert float(np.sum((x - opt) ** 2)) < float(np.sum(opt ** 2))      # better than the start
        assert all(h["gain_confirm"] > h["bar"] for h in c["history"] if h["kept"])


def test_recipe_moves_layout_and_parts_in_window_units():
    V = [{"kind": "mode", "k": 0, "h": 1.0},
         {"kind": "layout", "key": "W", "lo": 120.3, "hi": 140.0, "x0": 120.3, "h": 0.02},
         {"kind": "part", "part": "front_wing", "key": "aoa_deg", "lo": -20.0, "hi": 30.0, "x0": 4.0, "h": 0.02}]
    c = {"start": _start(0), "centres": [[1.0, 2.0, 3.0]], "vars": V, "x": [0.5, 0.1, -0.04]}
    rec = farm.recipe(c, c["x"])
    assert rec["layout"]["W"] == round(120.3 + 0.1 * 19.7, 6)
    assert rec["parts"] == {"front_wing": {"aoa_deg": 2.0}}
    assert rec["edits"][-1]["bumps"][0]["amp_mm"] == 0.5
    job = farm.job(REF, rec, None, True)
    a = job["recipe"]["args"]
    assert a[a.index("--fwing-json") + 1] == '{"aoa_deg": 2.0}' and "parts" not in a[1]
    assert farm.recipe(c, [0.0, 0.0, 0.0]).get("parts") is None          # nothing moved: defaults, no part JSON
    # a step outside the window is clipped so the built value lands exactly on the edge, never outside
    for step in ([0.0, 5.0, -5.0], [0.0, -5.0, 5.0], [0.0, 0.3, -0.2]):
        rec = farm.recipe(c, farm._clip([c], c["x"], step))
        W, aoa = rec["layout"]["W"], rec.get("parts", {}).get("front_wing", {}).get("aoa_deg", 4.0)
        assert 120.3 <= W <= 140.0 and -20.0 <= aoa <= 30.0
    assert farm.recipe(c, farm._clip([c], c["x"], [0.0, 5.0, -5.0]))["layout"]["W"] == 140.0
    assert farm.recipe(c, farm._clip([c], c["x"], [0.0, 5.0, -5.0]))["parts"]["front_wing"]["aoa_deg"] == -20.0
    assert farm.recipe(c, farm._clip([c], c["x"], [0.0, -5.0, 5.0]))["layout"]["W"] == 120.3
    assert farm.recipe(c, farm._clip([c], c["x"], [0.0, -5.0, 5.0]))["parts"]["front_wing"]["aoa_deg"] == 30.0


def _done(T=1.0, field=None):
    """A finished car; its field hash is its time unless given (cars with different times are different
    fields; one with the current car's field hash is the current car)."""
    f = field or f"f{T!r}"
    return {"status": "done", "result": {"legal": True, "T_s": T, "expect_field_sha": f, "field_sha": f,
                                         "judged_field_sha": f, "case_url": "u"}}


def _mapped(tmp_path, remap):
    """One chain, its start car and full map already timed."""
    centres = [[float(k), 0.0, 0.0] for k in range(2)]
    st = farm.init(tmp_path / f"{remap}.json", [_start(0)], REF, [centres], full=False, remap=remap)
    results = {}
    for _ in range(3):
        for j in farm.tick(st, results, 0.3e-3):
            rec = json.loads(j["recipe"]["args"][1])
            results[j["id"]] = _done(1.0 + 1e-3 * sum(b["amp_mm"] for b in _amps(rec)))
        if st["chains"][0]["maps"]:
            break
    assert st["chains"][0]["maps"]
    return st, results


def _canon(o):
    """A canonical JSON text of a state (numpy arrays and scalars as plain lists and numbers)."""
    return json.dumps(o, sort_keys=True, default=lambda v: v.tolist())


def test_remap_round_after_a_reject_asks_nothing_new_and_matches_keep(tmp_path):
    import copy
    out = {}
    for remap in ("keep", "round"):
        st, results = _mapped(tmp_path, remap)
        c = st["chains"][0]
        c["round"] += 1                                  # a reject: x unchanged, next round
        n = len(results)
        jobs = farm.tick(st, results, 0.3e-3)
        map_ids = {farm.rid(REF, farm.recipe(c, [c["x"][i] + s * (k == i) for i in range(2)]))
                   for k in range(2) for s in (1.0, -1.0)}
        assert map_ids <= set(results) and not map_ids & {j["id"] for j in jobs}
        assert len(results) == n
        s = copy.deepcopy(st); s.pop("remap"); s["chains"][0].pop("map_round", None)
        out[remap] = _canon([s, sorted(j["id"] for j in jobs)])
    assert out["keep"] == out["round"]
    s["chains"][0]["x"][0] = float(s["chains"][0]["x"][0]) + 1e-6      # the comparison is real: one changed field shows
    assert _canon([s, sorted(j["id"] for j in jobs)]) != out["round"]


def test_remap_after_a_keep_both_modes_map_again(tmp_path):
    for remap in ("keep", "round"):
        st, results = _mapped(tmp_path, remap)
        c = st["chains"][0]
        c["x"] = [0.5, -0.5]; c["round"] += 1             # a keep: the current car moved
        jobs = farm.tick(st, results, 0.3e-3)
        assert [j for j in jobs if j["recipe"]["save_case"]], "the new current car is asked for first"


def test_unknown_remap_raises(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        farm.init(tmp_path / "s.json", [_start(0)], REF, [[[0.0, 0.0, 0.0]]], full=False, remap="always")


def test_refine_starts_a_5mm_pass_on_the_converged_car(tmp_path):
    import pytest
    centres = [[float(k), 0.0, 0.0] for k in range(3)]
    st = farm.init(tmp_path / "s.json", [_start(0)], REF, [centres], full=False)
    c = st["chains"][0]
    c["x"] = [0.5, 0.0, -1.0]
    old = farm.recipe(c, c["x"])
    with pytest.raises(ValueError):                       # only a converged chain moves on
        farm.refine(c, centres, 5.0, 0.5)
    c["status"] = "converged"
    fine = [[float(k) / 2, 1.0, 0.0] for k in range(6)]
    farm.refine(c, fine, 5.0, 0.5)
    assert farm.rid(REF, farm.recipe(c, c["x"])) == farm.rid(REF, old)   # same car, same id: not timed again
    assert c["status"] == "running" and c["x"] == [0.0] * 6 and c["maps"] == {}
    assert [v["r"] for v in c["vars"]] == [5.0] * 6 and [v["h"] for v in c["vars"]] == [0.5] * 6
    assert c["passes"][0]["x"] == [0.5, 0.0, -1.0]
    b = farm.recipe(c, [0.5] + [0.0] * 5)["edits"][-1]["bumps"]
    assert b == [{"c_mm": [0.0, 1.0, 0.0], "amp_mm": 0.5, "sigma_mm": 5.0}]
    j = farm.tick(st, {}, 0.3e-3)
    assert [x["id"] for x in j] == [farm.rid(REF, old)]   # the tick asks only for the start car (already timed in practice)


def _switch_chain(tmp_path):
    centres = [[float(k), 0.0, 0.0] for k in range(2)]
    st = farm.init(tmp_path / "sw.json", [_start(0)], REF, [centres], full=False)
    c = st["chains"][0]
    c["vars"] += [{"kind": "part", "part": "supports", "key": "strip_w_mm", "lo": 1.0, "hi": 20.0, "x0": 7.0, "h": 0.02},
                  {"kind": "switch", "part": "supports", "key": "strip", "h": 0.0}]
    c["x"] = [0.0, 0.0, 0.1, 0.0]
    return st, c


def test_strip_switch_recipe_and_clip(tmp_path):
    st, c = _switch_chain(tmp_path)
    assert farm.recipe(c, c["x"])["parts"] == {"supports": {"strip_w_mm": 8.9}}
    off = farm.recipe(c, [0.0, 0.0, 0.1, 1.0])
    assert off["parts"] == {"supports": {"strip": False}}                  # width unused with the strip off
    a = farm.job(REF, off, None, True)["recipe"]["args"]
    assert a[a.index("--support-json") + 1] == '{"strip": false}'
    assert farm.recipe(c, [0.0, 0.0, 0.0, 0.0]).get("parts") is None       # strip on, width default: no JSON
    out = farm._clip([c], c["x"], [1.0, -1.0, 0.3, 0.9])                  # a gradient step never moves the switch
    assert out[3] == 0.0 and out[2] == 0.3
    c["x"] = [0.0, 0.0, 0.1, 1.0]                                          # strip off: width frozen at its last value
    assert farm._frozen(c, 2) and farm._frozen(c, 3) and not farm._frozen(c, 0)
    assert farm._clip([c], c["x"], [0.0, 0.0, 0.5, 1.0])[2] == 0.1


def test_strip_flip_is_a_candidate_each_round(tmp_path):
    st, c = _switch_chain(tmp_path)
    results = {}
    for _ in range(4):
        for j in farm.tick(st, results, 0.3e-3):
            rec = json.loads(j["recipe"]["args"][1])
            results[j["id"]] = _done(1.0 + 1e-3 * sum(b["amp_mm"] for b in _amps(rec)))
        if c["cands"]:
            break
    assert list(c["maps"].values())[0][3] == 0.0                          # the switch is never in the gradient
    assert "0" in c["cands"]
    flip = c["cands"]["0"]
    assert flip[:3] == c["x"][:3] and flip[3] == 1.0                       # numbers unchanged, strip flipped
    assert farm.recipe(c, flip)["parts"]["supports"]["strip"] is False


def _kinds(c):
    k = {}
    for v in c["vars"]:
        k[v["kind"]] = k.get(v["kind"], 0) + 1
    return k


def test_init_full_has_every_variable(tmp_path):
    """The real path (full=True): farm itself puts part 4 on the path (no help from this test)."""
    centres = [[float(k), 0.0, 0.0] for k in range(96)]
    st = farm.init(tmp_path / "f.json", [_start(0)], REF, [centres])
    c = st["chains"][0]
    assert _kinds(c) == {"mode": 96, "layout": 3, "floor": 5, "part": 23, "switch": 1}
    assert len(c["x"]) == 128 and farm.recipe(c, c["x"]) == {"layout": _start(0)["layout"], "edits": [], "floor": {"ft_h": 3.0}}


def test_refine_on_a_full_chain(tmp_path):
    centres = [[float(k), 0.0, 0.0] for k in range(96)]
    st = farm.init(tmp_path / "f.json", [_start(0)], REF, [centres])
    c = st["chains"][0]
    j = next(i for i, v in enumerate(c["vars"]) if v.get("key") == "strip_w_mm")
    s = next(i for i, v in enumerate(c["vars"]) if v["kind"] == "switch")
    c["x"][0], c["x"][96], c["x"][j] = 0.7, 0.05, 0.1
    old = farm.recipe(c, c["x"])
    c["status"] = "converged"
    farm.refine(c, [[float(k) / 2, 1.0, 0.0] for k in range(200)], 5.0, 4.0)
    assert farm.rid(REF, farm.recipe(c, c["x"])) == farm.rid(REF, old)
    assert _kinds(c) == {"mode": 200, "layout": 3, "floor": 5, "part": 23, "switch": 1}
    assert c["x"][s] == 0.0 and all(v["r"] == 5.0 and v["h"] == 4.0 for v in c["vars"] if v["kind"] == "mode")


def test_farm_init_lab_end_to_end(tmp_path):
    """p3_farm_init.py as the reviewer runs it: its own sys.path only (python -I), results from a file URL."""
    import subprocess
    here = Path(__file__).resolve().parents[1]
    res = tmp_path / "results.json"
    res.write_text("{}")
    p = subprocess.run([sys.executable, "-I", "../.github/lab/p3_farm_init.py", REF, res.as_uri(), json.dumps(_start(0))],
                       cwd=here, capture_output=True, text=True, timeout=3600)
    assert p.returncode == 0, p.stderr[-3000:]
    lines = p.stdout.splitlines()
    st = json.loads(next(l for l in lines if l.startswith("LAB state "))[len("LAB state "):])
    jobs = [json.loads(l[len("LAB job "):]) for l in lines if l.startswith("LAB job ")]
    assert _kinds(st["chains"][0])["part"] == 23
    assert [j["id"] for j in jobs] == [farm.rid(REF, {"layout": _start(0)["layout"], "edits": [], "floor": {"ft_h": 3.0}})]   # no result yet: the start car


def test_tunnel_variables(tmp_path):
    centres = [[float(k), 0.0, 0.0] for k in range(96)]
    st = farm.init(tmp_path / "t.json", [{**_start(0), "floor": {}}], REF, [centres])
    c = st["chains"][0]
    ix = {v["key"]: i for i, v in enumerate(c["vars"]) if v["kind"] == "floor"}
    assert set(ix) == {"ft_h", "ft_w", "ft_x0", "ft_x1", "ft_ramp"}
    assert farm.recipe(c, c["x"]).get("floor") is None                      # a start with no tunnel (floor {})
    assert farm._frozen(c, ix["ft_w"]) and not farm._frozen(c, ix["ft_h"])   # no tunnel: only its depth is searched
    x = list(c["x"]); x[ix["ft_h"]] = 0.3; x[ix["ft_w"]] = 0.1
    rec = farm.recipe(c, x)
    assert rec["floor"]["ft_h"] == 3.0 and rec["floor"]["ft_w"] == round(c["vars"][ix["ft_w"]]["x0"] + 0.1 * 10.8, 6)
    a = farm.job(REF, rec, None, True)["recipe"]["args"]
    assert json.loads(a[a.index("--body-json") + 1]) == rec["floor"]
    c["x"] = x
    assert not farm._frozen(c, ix["ft_w"])                                  # a tunnel: its shape is searched too


def _converged_c1(tmp_path):
    centres = [[float(k), 0.0, 0.0] for k in range(4)]
    st = farm.init(tmp_path / "l.json", [_start(0)], REF, [centres], full=False)
    c = st["chains"][0]
    c["x"], c["status"], c["d10_s"] = [0.5, 0.0, 0.0, 0.0], "converged", 0.4e-3
    return st, c


def _time_cars(c, a5, curve):
    """Fake results for the check cars: T = 1 + 1e-3 * curve(amp) per car."""
    return {farm.rid(REF, rec): _done(1.0 + 1e-3 * curve(amp)) for (k, amp), rec in farm.linearity_cars(c, a5).items()}


def test_linearity_check_passes_on_a_line_and_fails_on_a_curve(tmp_path):
    st, c = _converged_c1(tmp_path)
    farm.refine(c, [[float(k), 2.0, 0.0] for k in range(4)], 5.0, 4.0)
    a5, sig = 4.0, 0.3e-3
    assert farm.linearity_ok(c, REF, {}, a5, sig) == (None, [])          # nothing timed yet
    ok, rows = farm.linearity_ok(c, REF, _time_cars(c, a5, lambda a: 0.5 * a), a5, sig)
    assert ok and len(rows) == 3 and all(abs(r["diff_s"]) < 1e-12 for r in rows)
    # odd but not linear: full = 2 * (0.5 * 64) = 64e-3, 2 * half = 2 * 2 * (0.5 * 8) = 16e-3 -> far over 0.85 ms
    ok, rows = farm.linearity_ok(c, REF, _time_cars(c, a5, lambda a: 0.5 * a ** 3), a5, sig)
    assert ok is False and all(not r["ok"] for r in rows)
    # just inside / just outside the band
    tol = farm.lin_band(sig)
    for eps, want in ((0.9, True), (1.1, False)):
        res = _time_cars(c, a5, lambda a: 0.5 * a)
        rec = farm.linearity_cars(c, a5)[(0, a5)]
        res[farm.rid(REF, rec)]["result"]["T_s"] += eps * tol
        assert farm.linearity_ok(c, REF, res, a5, sig)[0] is want


def test_refine_lab_refuses_without_a_passing_check(tmp_path, monkeypatch):
    import importlib.util
    here = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(here)
    monkeypatch.setenv("P3_MODE_R_MM", "5")
    monkeypatch.setenv("P3_NMODES", "4")
    spec = importlib.util.spec_from_file_location("p3_farm_refine", here.parent / ".github" / "lab" / "p3_farm_refine.py")
    lab = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab)
    fine = [[float(k), 2.0, 0.0] for k in range(4)]
    a5 = min(max(4 * max(1.0, 1.3e-3 / 0.4e-3), 1.0), 7.87)

    def run(results, noise_ref=REF):
        st, _ = _converged_c1(tmp_path)
        f = {n: tmp_path / f"{n}.json" for n in ("s", "r", "n")}
        f["s"].write_text(json.dumps(st))
        f["r"].write_text(json.dumps(results))
        f["n"].write_text(json.dumps({"ref": noise_ref, "shape_sigma_s": 0.3e-3}))
        return lab.main([f[n].as_uri() for n in ("s", "r", "n")], centres=lambda start: fine)

    def check_cars():
        st, c = _converged_c1(tmp_path)
        farm.refine(c, fine, 5.0, a5)
        return c

    import pytest
    with pytest.raises(SystemExit):
        run({}, noise_ref="1" * 40)                        # noise from another ref
    assert run({}) == 0                                    # 1st run: writes the check cars only
    with pytest.raises(SystemExit):
        run(_time_cars(check_cars(), a5, lambda a: 0.5 * a ** 3))
    assert run(_time_cars(check_cars(), a5, lambda a: 0.5 * a)) == 0


def test_start_has_the_3mm_tunnel(tmp_path):
    centres = [[float(k), 0.0, 0.0] for k in range(96)]
    c = farm.init(tmp_path / "t3.json", [_start(0)], REF, [centres])["chains"][0]
    ix = {v["key"]: i for i, v in enumerate(c["vars"]) if v["kind"] == "floor"}
    rec = farm.recipe(c, c["x"])
    assert rec["floor"] == {"ft_h": 3.0}                                    # pattern.FLOOR_START, other ft_* at defaults
    a = farm.job(REF, rec, None, True)["recipe"]["args"]
    assert json.loads(a[a.index("--body-json") + 1]) == {"ft_h": 3.0}
    assert not any(farm._frozen(c, i) for i in ix.values())                # all five live from round 0
    assert c["vars"][ix["ft_h"]]["x0"] == 3.0


def test_map_slope_at_a_window_edge(tmp_path):
    """W starts on its lo edge: the -h side clamps to the start car itself. The slope uses the step
    actually taken, so a linear T gives the exact slope; an interior variable is unchanged; the
    clamped side reuses the start car's time (no duplicate id is asked for)."""
    st = farm.init(tmp_path / "e.json", [_start(0)], REF, [[[0.0, 0.0, 0.0]]], full=False)
    c = st["chains"][0]
    c["vars"] = [{"kind": "mode", "k": 0, "h": 1.0},
                 {"kind": "layout", "key": "W", "lo": 120.3, "hi": 140.0, "x0": 120.3, "h": 0.02},
                 {"kind": "layout", "key": "d_halo", "lo": 25.0, "hi": 75.0, "x0": 43.72, "h": 0.02}]
    c["x"] = [0.0, 0.0, 0.0]
    kW, kd = 2e-3, -1e-3                                                    # s per x unit, linear in the physical value

    def T(rec):
        lay = rec["layout"]
        return 1.0 + kW * (lay["W"] - 120.3) / 19.7 + kd * (lay["d_halo"] - 43.72) / 50.0

    results, asked = {}, []
    for _ in range(3):
        jobs = farm.tick(st, results, 0.3e-3)
        asked += [j["id"] for j in jobs]
        for j in jobs:
            rec = {"layout": json.loads(j["recipe"]["args"][1])["layout"], "edits": []}
            results[j["id"]] = _done(T(rec))
        if c["maps"]:
            break
    g = list(c["maps"].values())[0]
    assert abs(g[1] - kW) < 1e-9 and abs(g[2] - kd) < 1e-9 and g[0] == 0.0
    assert len(asked) == len(set(asked))                                    # no car asked for twice
    start_id = farm.rid(REF, farm.recipe(c, [0.0, 0.0, 0.0]))
    assert farm.rid(REF, farm.recipe(c, [0.0, -0.02, 0.0])) == start_id    # the clamped side is the start car


def test_linearity_band_is_honest():
    """A linear car with N(0, sigma) timings passes the 3-mode check >= 94 % of 2,000 seeds; a
    nonlinearity of 3 x band on one mode fails >= 90 %."""
    import tempfile
    st, c = _converged_c1(Path(tempfile.mkdtemp()))
    farm.refine(c, [[float(k), 2.0, 0.0] for k in range(4)], 5.0, 4.0)
    a5, sig = 4.0, 0.3e-3
    band = farm.lin_band(sig)
    assert abs(band - 2.394 * 10 ** 0.5 * sig) < 0.01 * band
    cars = farm.linearity_cars(c, a5)
    ids = {key: farm.rid(REF, rec) for key, rec in cars.items()}
    passed = {0.0: 0, 3.0: 0}
    for seed in range(2000):
        rng = np.random.default_rng(seed)
        noise = {key: sig * rng.normal() for key in cars}
        for bend in passed:
            res = {}
            for (k, amp), i in ids.items():
                t = 1.0 + 1e-3 * 0.5 * amp + noise[(k, amp)]
                if k == 0 and amp == a5:
                    t += bend * band                                       # D on mode 0 shifted by bend x band
                res[i] = _done(t)
            passed[bend] += bool(farm.linearity_ok(c, REF, res, a5, sig)[0])
    assert passed[0.0] / 2000 >= 0.94, passed
    assert 1 - passed[3.0] / 2000 >= 0.90, passed


def _one_mode(tmp_path, name):
    st = farm.init(tmp_path / f"{name}.json", [_start(0)], REF, [[[0.0, 0.0, 0.0]]], full=False)
    return st, st["chains"][0]


def _map_once(st, c, T_of, field_of=None, side_check=None):
    results, asked = {}, []
    for _ in range(3):
        jobs = farm.tick(st, results, 0.3e-3, side_check=side_check)
        asked += [j["id"] for j in jobs]
        for j in jobs:
            amps = _amps(json.loads(j["recipe"]["args"][1]))
            a = amps[0]["amp_mm"] if amps else 0.0
            results[j["id"]] = _done(T_of(a), field=field_of(a) if field_of else None)
        if c["maps"]:
            return list(c["maps"].values())[0], asked
    raise AssertionError("no map")


def test_mode_side_that_does_not_move_gives_a_one_sided_slope(tmp_path):
    """+side grows into the block's edge: carved and timed, but its field is the current car's."""
    st, c = _one_mode(tmp_path, "one")
    k = 2e-3
    g, _ = _map_once(st, c, lambda a: 1.0 + k * min(a, 0.0), field_of=lambda a: "base" if a >= 0 else f"m{a}")
    assert abs(g[0] - k) < 1e-12                       # (T0 - T-) / h, not halved


def test_side_check_skips_dead_sides_and_a_dead_mode(tmp_path):
    st, c = _one_mode(tmp_path, "skip")
    k = 2e-3
    g, asked = _map_once(st, c, lambda a: 1.0 + k * a, side_check=lambda c, kk, amp: amp < 0)
    side = {a: farm.rid(REF, farm.recipe(c, [a])) for a in (1.0, -1.0)}
    assert abs(g[0] - k) < 1e-12 and side[1.0] not in asked and side[-1.0] in asked   # the dead + side never queued
    st, c = _one_mode(tmp_path, "dead")
    g, asked = _map_once(st, c, lambda a: 1.0 + k * a, side_check=lambda c, kk, amp: False)
    side = {a: farm.rid(REF, farm.recipe(c, [a])) for a in (1.0, -1.0)}
    assert g[0] == 0.0 and not set(side.values()) & set(asked)        # dead mode: no map car at all
