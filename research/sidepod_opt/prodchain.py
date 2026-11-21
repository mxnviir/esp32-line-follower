"""Production-model check of a whole loop run, on ONE low-noise mesh lineage.

Production schemes (linearUpwind U, no CFD_DIV_U). Production state A's coarse mesh is morphed onto
the loop's accepted designs in order, each link from the previous link's run (mesh + flow), the
same path the loop itself took. A fresh mesh is never compared with a morphed one: if a link's morph
fails, the chain stops there and says so (Part 2's fresh-mesh noise with the production wake is
several mN).
    python prodchain.py runs/cloud_original 1 3 4 6 7 8
        -> gate_results_coarse/prodchain_<run>.json, one row per link, written after every link
    python prodchain.py runs/cloud_original f4 6 7 8
        -> a second lineage: "f4" = design 4 on a FRESH mesh (warm from state A), the base; then
           morphs. Changes are against the seed's fresh-mesh result (prodcheck_seed_fresh), the
           same re-base the loop does. Output: prodchain_<run>_f<N>.json
"""
import json, os, shutil, sys
from pathlib import Path
os.environ.pop("CFD_DIV_U", None)
os.environ["GATE_RES"] = "coarse"
HERE = Path(__file__).resolve().parent
os.environ["GATE_RESULTS"] = str(HERE / "gate_results_coarse")
sys.path.insert(0, str(HERE))
import gate  # noqa: E402

run = Path(sys.argv[1])
args = sys.argv[2:]
base_fresh = args[0].startswith("f")
its = [int(a.lstrip("f")) for a in args]
n = 2
suffix = f"_f{its[0]}" if base_fresh else ""
out = HERE / "gate_results_coarse" / f"prodchain_{run.name}{suffix}.json"
rows = json.loads(out.read_text())["links"] if out.exists() else []
ref = str(HERE / "gate" / "refA_coarse")
seed = json.loads((HERE / "gate_results_coarse" / ("prodcheck_seed_fresh.json" if base_fresh else "prodcheck_seed.json")).read_text())
prev_D = seed["D20_half_N"]
done = {r["it"] for r in rows}
keep_prev = None
for k, it in enumerate(its):
    if it in done:
        continue
    folder = run / f"it_{it:03d}" / "car"
    fresh_here = base_fresh and k == 0
    extra = {"warm_from": ref} if fresh_here else {"morph_from": ref, "warm_from": ref}
    half, health, secs = gate.solve(folder, n, 1000, extra=extra, keep=True)
    rdir = gate.latest_run_of(os.getpid())
    fell = bool(rdir and (Path(rdir) / "MORPH_FALLBACK").exists()) and not fresh_here
    row = {"it": it, "D20_half_N": float(half.D20), "stderr_N": getattr(health, "force_mean_stderr", None),
           "converged": bool(health.converged), "morph_fallback": fell, "fresh_base": fresh_here, "from": Path(ref).name, "wall_s": round(secs, 1),
           "change_vs_seed_mN": (float(half.D20) - seed["D20_half_N"]) * 1e3,
           "change_vs_prev_mN": (float(half.D20) - prev_D) * 1e3}
    rows.append(row)
    out.write_text(json.dumps({"seed_D20_half_N": seed["D20_half_N"], "seed_mesh": "fresh" if base_fresh else "morph",
                               "links": rows}, indent=1, default=float))
    print(json.dumps(row, default=float), flush=True)
    if keep_prev:
        shutil.rmtree(keep_prev, ignore_errors=True)
    if fell:
        print("morph failed: chain stops here (a fresh mesh is not comparable)", flush=True)
        shutil.rmtree(rdir, ignore_errors=True)
        break
    keep_prev, ref, prev_D = rdir, rdir, float(half.D20)
print("CHAIN_DONE", flush=True)
