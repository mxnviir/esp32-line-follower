"""Dead bump modes on the start block. The reviewer measured mode 9 (the one centre over the ft_h 3
tunnel slot) on the start block: carve status ok, but the surface did not move for +1 or -1 mm (disp p90
3.5e-10 m, 0 cells), untunnelled and tunnelled, so the tunnel is not the reason. farm.tick freezes such
sides before queuing with map_jobs.side_moves (no carve: the bump's speed, splatted as phi_updater does,
on the surface cells a rule mask lets it move). This test holds side_moves to the full carve on mode 9
(measured dead under the despike clip; with exact_speed it may move, so its verdict is not assumed:
the screen must agree with the carve whatever it is) and on 3 modes whose -1 mm carve moves (each sign
compared). Run with -s for the rows."""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "part3-simulation" / "checks"))
sys.path.insert(0, str(ROOT / "part5-simulation"))


def _moves(start, c_mm, amp):
    import carve
    g, rep = carve.carve(start["layout"], start["edits"] + [
        {"bumps": [{"c_mm": c_mm, "amp_mm": amp, "sigma_mm": 10.0}], "unit": False}])
    r = rep[-1]
    return r.get("status") == "ok" and bool(r["moved"]), r          # Part 1's cut report: any cell changed side


def test_side_moves_agrees_with_the_full_carve():
    import farm
    import map_jobs
    import paths  # noqa: F401
    import carve
    start = farm.with_floor({"name": "chain1", "layout": {"W": 120.3, "x_front": 46.0, "d_halo": 43.72}, "edits": []})
    C = map_jobs.centres_mm(start)
    g0, _ = carve.carve(start["layout"], start["edits"])
    rows, live = [], []
    for k in [9] + [k for k in range(len(C)) if k != 9]:
        if k != 9 and len(live) == 3:
            break
        full = {amp: _moves(start, C[k], amp) for amp in (1.0, -1.0)}
        if k != 9 and not full[-1.0][0]:
            continue                                     # not a live mode: look further
        cheap = {amp: map_jobs.side_moves(g0, C[k], 10.0, amp) for amp in (1.0, -1.0)}
        for amp in (1.0, -1.0):
            rows.append({"mode": k, "amp": amp, "carve_moves": full[amp][0], "side_moves_cells": cheap[amp],
                         "cells_flipped": full[amp][1].get("cells_flipped"), "dvol_mm3": full[amp][1].get("dvol_mm3"), "status": full[amp][1].get("status")})
            print("P3 dead-mode check " + json.dumps(rows[-1]))
        if k != 9:
            live.append(k)
    assert len(live) == 3, rows
    assert all(r["carve_moves"] is False for r in rows if r["side_moves_cells"] == 0), rows   # one-way: screened dead => dead
    assert all((r["side_moves_cells"] > 0) == r["carve_moves"] for r in rows), rows     # the screen agrees

def test_grow_screen_against_the_measured_truth():
    """Truth: data/grow_truth_96_0de1e3e.txt, the reviewer's full carve of all 96 modes at +1 on the start
    block (carve.carve, default 1 mm grid, code 0de1e3e via 0054a2c; GROW line per mode, rep "moved").
    82 are dead, 14 live (the start block is not the whole envelope everywhere). (b) The screen must never
    call a live side dead: a hard fail. (c) Dead sides it still lets through cost one fine car each per
    map; the bar is 75 / 82, the count measured on 0054a2c (75 / 96 screened 0, all 14 live kept), so it
    can only stop a regression. Tightening the 2x margin to catch the 4-cell leftovers is not done: the
    live modes 44 and 48 flip only 4 cells, so a tighter margin is the one way to break (b)."""
    import farm
    import map_jobs
    import paths  # noqa: F401
    import carve
    truth = {}
    for ln in (Path(__file__).parent / "data" / "grow_truth_96_0de1e3e.txt").read_text().splitlines():
        r = json.loads(ln.split(" ", 1)[1])
        truth[r["mode"]] = r["status"] == "ok" and r["moved"]
    start = farm.with_floor({"name": "chain1", "layout": {"W": 120.3, "x_front": 46.0, "d_halo": 43.72}, "edits": []})
    C = map_jobs.centres_mm(start)
    assert len(C) == len(truth) == 96
    g0, _ = carve.carve(start["layout"], start["edits"])
    cells = {k: map_jobs.side_moves(g0, C[k], 10.0, 1.0) for k in range(96)}
    live = [k for k in truth if truth[k]]
    dead = [k for k in truth if not truth[k]]
    frozen_live = [k for k in live if cells[k] == 0]
    caught = sum(cells[k] == 0 for k in dead)
    print(f"P3 grow-side screen: caught {caught} / {len(dead)} dead; live kept {len(live) - len(frozen_live)} / {len(live)};"
          f" dead let through (mode, cells) {[(k, cells[k]) for k in dead if cells[k]]}")
    assert len(live) == 14 and not frozen_live, frozen_live          # (b) never freeze a live side
    assert caught >= 75, caught                                      # (c) measured on 0054a2c
