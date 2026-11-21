"""Early production ranking check (ROUTES.md 2026-11-20 19:00): solve a loop design with the
PRODUCTION schemes (linearUpwind U, no CFD_DIV_U) on production state A's coarse mesh, morphed onto
the design and warm-started from state A's flow, the gate's low-noise path.
    python prodcheck.py <car folder> <tag> [np] [fresh]   -> gate_results_coarse/prodcheck_<tag>.json
"fresh": a fresh snappy mesh warm-started from state A's flow (no morph), for designs too far
from the seed to morph; compare only with other "fresh" results.
"cold": a fresh mesh from a cold start, 2000 iterations (no reference state needed), e.g.
PRODCHECK_RES=medium python prodcheck.py <car folder> <tag> 4 cold  -> gate_results_medium/
"""
import json, os, sys
from pathlib import Path
os.environ.pop("CFD_DIV_U", None)
RES = os.environ.get("PRODCHECK_RES", "coarse")              # "medium": the finer check (use mode "cold")
os.environ["GATE_RES"] = RES
os.environ["GATE_RESULTS"] = str(Path(__file__).resolve().parent / f"gate_results_{RES}")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gate  # noqa: E402

folder, tag = Path(sys.argv[1]), sys.argv[2]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 2
ref = str(HERE / "gate" / "refA_coarse")
mode = sys.argv[4] if len(sys.argv) > 4 else "morph"
fresh = mode in ("fresh", "cold")
extra = {} if mode == "cold" else {"warm_from": ref} if fresh else {"morph_from": ref, "warm_from": ref}
half, health, secs = gate.solve(folder, n, 2000 if mode == "cold" else 1000, extra=extra, keep=True)
run = gate.latest_run_of(os.getpid())
fell = bool(run and (Path(run) / "MORPH_FALLBACK").exists())
d = gate.rec(half, health, secs, morph_fallback=fell, folder=str(folder), scheme="production linearUpwind", mesh="fresh" if fresh else "morph")
if run:
    import shutil
    gate.save_forces(run, f"prodcheck_{tag}")
    shutil.rmtree(run, ignore_errors=True)
(HERE / f"gate_results_{RES}" / f"prodcheck_{tag}.json").write_text(json.dumps(d, indent=1, default=float))
print(json.dumps(d, default=float))
