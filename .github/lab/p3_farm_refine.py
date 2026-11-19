"""Part 3: move every converged chain on to the 5 mm pass (lab script).

    P3_MODE_R_MM=5 P3_NMODES=<n> python ../.github/lab/p3_farm_refine.py <state_url> <results_url> <sigma_url>

Run by the reviewer on the server, not a queue job (results_url is the local-only /api/results;
ADMIN_KEY, if set, is sent as X-Admin-Key and never goes in a recipe). sigma_url is Part 2's
fine_noise.json; its ref must be the state's ref. P3_NMODES must be the count the 5 mm coverage
check gives (car_modes.py coverage with P3_MODE_R_MM=5; 278 on the start block): it is not guessed.

The 5 mm bump height a5 is computed here from data, never typed:
    D10 = median over the 96 modes of |T+ - T-| in chain 1's first 10 mm map (the c1-scan map,
          A = 1 mm; stored by farm.tick as d10_s)
    a5  = clamp(4 * max(1, 1.3 ms / D10), 1, 7.87) mm
  4: a 5 mm Gaussian has 1/4 the volume of a 10 mm one at equal height (signal ~ a * sigma^2).
  1.3 ms: 3 x sqrt(2) x 0.3 ms, a pair clearly above Part 2's fine shape noise.
  7.87 mm: peak curvature a / sigma^2 under 1 / 3.175 mm (ball cutter) at sigma 5 mm.

The linearity check is MANDATORY: a5 is always >= 4 mm (peak slope over ~20 deg), so the pass never
starts without it. On chain 1's converged car, 5 mm modes 0, 1, 2 (farm.LIN_MODES) are timed at +-a5
and +-a5/2. It passes only if on every mode T(+a5) - T(-a5) and 2 x (T(+a5/2) - T(-a5/2)) agree
within farm.lin_band: z sqrt(10) sigma_shape, z two-sided Bonferroni over the 3 modes at
5 % family-wise (2.394), since D = dT(+-a5) - 2 dT(+-a5/2) has SD sqrt(10) sigma. The lab prints that
band next to the expected 5 mm pair signal D10 x a5 / (4 A10) (the 1/4: volume at half the radius) and
prints a WARNING when the band is not below it: the check then has little power. Runs:
  1st run: no check results yet -> prints `LAB job {...}` for the 12 check cars, no state.
  later runs: check failed -> refuses (exit, rows printed); passed -> prints `LAB state {...}` with
  every converged chain moved to the 5 mm pass (its car becomes the new start; centres on that car).
Chains not converged are left as they are."""
import json
import os
import sys
import urllib.request

sys.path[:0] = ['.', '../part3-simulation/checks']
import farm  # noqa: E402
import map_jobs  # noqa: E402


def get(url):
    req = urllib.request.Request(url, headers={"X-Admin-Key": os.environ["ADMIN_KEY"]} if os.environ.get("ADMIN_KEY") else {})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


def main(argv, centres=map_jobs.centres_mm):
    assert os.environ.get("P3_MODE_R_MM") == "5" and os.environ.get("P3_NMODES"), "set P3_MODE_R_MM=5 and P3_NMODES"
    st, results, noise = (get(u) for u in argv[:3])
    if noise.get("ref") != st["ref"]:
        raise SystemExit(f"fine_noise ref {noise.get('ref')} is not the loop's ref {st['ref']}")
    sigma = float(noise["shape_sigma_s"])
    c1 = st["chains"][0]
    if c1["status"] != "converged" or c1.get("passes"):
        raise SystemExit(f"chain 1 is {c1['status']}{' (already refined)' if c1.get('passes') else ''}: nothing to check on")
    d10 = c1.get("d10_s")
    if not d10:
        raise SystemExit("no D10: chain 1's first map is not in the state")
    a5 = min(max(4 * max(1.0, 1.3e-3 / d10), 1.0), 7.87)
    print(f"LAB a5 {a5:.3f} mm from D10 {d10 * 1e3:.3f} ms", flush=True)
    moved = []
    for c in st["chains"]:
        if c["status"] == "converged" and not c.get("passes"):
            rec = farm.recipe(c, c["x"])
            farm.refine(c, centres({"layout": rec["layout"], "edits": rec["edits"]}), 5.0, a5)
            moved.append(c["id"])
    band, expect = farm.lin_band(sigma), d10 * a5 / (4 * farm.A_MM)
    print(f"LAB linearity band {band * 1e3:.3f} ms (detectable nonlinearity) vs expected 5 mm pair signal "
          f"{expect * 1e3:.3f} ms (D10 x a5 / (4 A10))", flush=True)
    if band >= expect:
        print("LAB WARNING: the linearity band is not below the expected signal: the check is weak "
              "(it can only catch nonlinearity larger than the signal itself)", flush=True)
    ok, rows = farm.linearity_ok(c1, st["ref"], results, a5, sigma)
    if ok is None:
        for rec in farm.linearity_cars(c1, a5).values():
            print("LAB job " + json.dumps(farm.job(st["ref"], rec, None, False)), flush=True)
        print("LAB linearity: check cars written; run again when they are in", flush=True)
        return 0
    for r in rows:
        print("LAB linearity " + json.dumps(r), flush=True)
    if not ok:
        raise SystemExit(f"linearity check FAILED at a5 {a5:.3f} mm: the 5 mm pass is not started")
    print("LAB state " + json.dumps(st), flush=True)
    print(f"LAB refine: chains {moved} moved to the 5 mm pass at a5 {a5:.3f} mm", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
