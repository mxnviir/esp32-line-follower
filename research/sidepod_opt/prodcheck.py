"""Early production ranking check (ROUTES.md 2026-11-20 19:00): solve a loop design with the
PRODUCTION schemes (linearUpwind U, no CFD_DIV_U) on production state A's coarse mesh, morphed onto
the design and warm-started from state A's flow, the gate's low-noise path.
    python prodcheck.py <car folder> <tag> [np] [fresh]   -> gate_results_coarse/prodcheck_<tag>.json
"fresh": a fresh snappy mesh warm-started from state A's flow (no morph), for designs too far
from the seed to morph; compare only with other "fresh" results.
"""
import json, os, sys
from pathlib import Path
os.environ.pop("CFD_DIV_U", None)
os.environ["GATE_RES"] = "coarse"
os.environ["GATE_RESULTS"] = str(Path(__file__).resolve().parent / "gate_results_coarse")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gate  # noqa: E402

folder, tag = Path(sys.argv[1]), sys.argv[2]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 2
ref = str(HERE / "gate" / "refA_coarse")
fresh = len(sys.argv) > 4 and sys.argv[4] == "fresh"
extra = {"warm_from": ref} if fresh else {"morph_from": ref, "warm_from": ref}
half, health, secs = gate.solve(folder, n, 1000, extra=extra, keep=True)
run = gate.latest_run_of(os.getpid())
fell = bool(run and (Path(run) / "MORPH_FALLBACK").exists())
d = gate.rec(half, health, secs, morph_fallback=fell, folder=str(folder), scheme="production linearUpwind", mesh="fresh" if fresh else "morph")
if run:
    import shutil
    gate.save_forces(run, f"prodcheck_{tag}")
    shutil.rmtree(run, ignore_errors=True)
(HERE / "gate_results_coarse" / f"prodcheck_{tag}.json").write_text(json.dumps(d, indent=1, default=float))
print(json.dumps(d, default=float))
