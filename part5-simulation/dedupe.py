"""Never time the same car twice (reviewer, 2026-11-15).

The stopwatch is deterministic (2 cores: 0.01 ms repeat), and carve.carve gives the identical
body for identical settings, so a case whose settings x match a car already timed (or being
timed) gets that car's time instead of a new CFD job. Used by the farm adapter between
carve_loop.needed() and dispatch:

    todo = dedupe.plan(needed(state), results, running)   # cases that need a real job
    dedupe.fill(needed(state), results)                    # copy times onto the duplicates
"""
from __future__ import annotations

import hashlib

import numpy as np


def key(x) -> str:
    """Identity of a car's settings: exact float64 bytes (no rounding: 'nearly equal' is not equal)."""
    return hashlib.sha256(np.ascontiguousarray(np.asarray(x, dtype=np.float64)).tobytes()).hexdigest()


def plan(needed: dict, results: dict, running: set) -> list:
    """Case ids that need a real timing: one per distinct car not already timed or running."""
    seen = {key(needed[k][0]) for k in list(results) + list(running) if k in needed}
    out = []
    for k, (x, _) in needed.items():
        if k in results or k in running:
            continue
        h = key(x)
        if h not in seen:
            seen.add(h)
            out.append(k)
    return out


def fill(needed: dict, results: dict) -> int:
    """Give every untimed duplicate the time of its identical timed car; returns how many."""
    by = {key(needed[k][0]): results[k] for k in needed if k in results}
    n = 0
    for k, (x, _) in needed.items():
        if k not in results and key(x) in by:
            results[k] = by[key(x)]
            n += 1
    return n
