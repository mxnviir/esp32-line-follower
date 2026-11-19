"""Write data/part2/fine_noise.json from fine-mesh results (b02-p2-fine).

Same-ref rule (2026-11-17): a bit-equality or noise check compares only runs on
ONE code sha. writePrecision sets force.dat's digits (v2412 writeFile.C), so T
moves ~1e-8 s between refs; mixing refs would hide or fake a difference.
Each group (the shape ladder, the repeats) must have one ref, or this refuses.

    python fine_noise.py results.json out.json
results.json: [{"id", "ref", "group": "shape"|"repeat", "scale", "T_at_target_s"}, ...]
"""
import json
import sys

from noise_stats import residual_sd


def one_ref(rows: list, group: str) -> str:
    refs = {r["ref"] for r in rows}
    if len(refs) != 1:
        raise ValueError(f"{group}: runs from {len(refs)} code refs {sorted(refs)}; "
                         "a sigma/repeat group must use one code sha")
    return refs.pop()


def build(results: list, batch: str = "b02-p2-fine") -> dict:
    shape = [r for r in results if r["group"] == "shape"]
    rep = [r for r in results if r["group"] == "repeat"]
    ref = one_ref(shape, "shape")
    out = {"mesh": "fine", "cores": 4, "decompose": "hierarchical", "batch": batch,
           "method": "smooth body_scale_y ladder, residual SD about a line (noise_stats)",
           "ref": ref, "n_cars": len(shape)}
    s, lo, hi, _ = residual_sd([r["scale"] for r in shape], [r["T_at_target_s"] for r in shape])
    out["shape_sigma_s"], out["shape_sigma_ci_s"] = s, [lo, hi]
    if rep:
        out["repeat_ref"] = one_ref(rep, "repeat")
        t = [r["T_at_target_s"] for r in rep]
        out["repeat_spread_s"] = max(t) - min(t)
    return out


if __name__ == "__main__":
    json.dump(build(json.load(open(sys.argv[1]))), open(sys.argv[2], "w"), indent=1)
