"""Production-model check of a whole loop run, on ONE low-noise mesh lineage.

Production schemes (linearUpwind U, no CFD_DIV_U). Production state A's coarse mesh is morphed onto
the loop's accepted designs in order, each link from the previous link's run (mesh + flow), the
same path the loop itself took. A fresh mesh is never compared with a morphed one: if a link's morph
fails, the chain stops there and says so (Part 2's fresh-mesh noise with the production wake is
several mN).
    python prodchain.py runs/cloud_original 1 3 4 6 7 8 [np]
        -> gate_results_coarse/prodchain_<run>.json, one row per link, written after every link
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
its = [int(a) for a in sys.argv[2:] if a.isdigit() and len(a) < 3]
n = 2
out = HERE / "gate_results_coarse" / f"prodchain_{run.name}.json"
rows = json.loads(out.read_text())["links"] if out.exists() else []
ref = str(HERE / "gate" / "refA_coarse")
seed = json.loads((HERE / "gate_results_coarse" / "prodcheck_seed.json").read_text())
prev_D = seed["D20_half_N"]
done = {r["it"] for r in rows}
keep_prev = None
for it in its:
    if it in done:
        continue
    folder = run / f"it_{it:03d}" / "car"
    half, health, secs = gate.solve(folder, n, 1000, extra={"morph_from": ref, "warm_from": ref}, keep=True)
    rdir = gate.latest_run_of(os.getpid())
    fell = bool(rdir and (Path(rdir) / "MORPH_FALLBACK").exists())
    row = {"it": it, "D20_half_N": float(half.D20), "stderr_N": getattr(health, "force_mean_stderr", None),
           "converged": bool(health.converged), "morph_fallback": fell, "from": Path(ref).name, "wall_s": round(secs, 1),
           "change_vs_seed_mN": (float(half.D20) - seed["D20_half_N"]) * 1e3,
           "change_vs_prev_mN": (float(half.D20) - prev_D) * 1e3}
    rows.append(row)
    out.write_text(json.dumps({"seed_morph_D20_half_N": seed["D20_half_N"], "links": rows}, indent=1, default=float))
    print(json.dumps(row, default=float), flush=True)
    if keep_prev:
        shutil.rmtree(keep_prev, ignore_errors=True)
    if fell:
        print("morph failed: chain stops here (a fresh mesh is not comparable)", flush=True)
        shutil.rmtree(rdir, ignore_errors=True)
        break
    keep_prev, ref, prev_D = rdir, rdir, float(half.D20)
print("CHAIN_DONE", flush=True)
