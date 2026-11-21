"""Early production ranking check (ROUTES.md 2026-11-20 19:00): solve a loop design with the
PRODUCTION schemes (linearUpwind U, no CFD_DIV_U) on production state A's coarse mesh, morphed onto
the design and warm-started from state A's flow, the gate's low-noise path.
    python prodcheck.py <car folder> <tag> [np] [fresh]   -> gate_results_coarse/prodcheck_<tag>.json
"fresh": a fresh snappy mesh warm-started from state A's flow (no morph), for designs too far
from the seed to morph; compare only with other "fresh" results.
"cold": a fresh mesh from a cold start, 2000 iterations (no reference state needed), e.g.
PRODCHECK_RES=medium python prodcheck.py <car folder> <tag> 4 cold  -> gate_results_medium/
Resolutions: coarse, medium, fine, resolved (Part 2's RESOLUTION_REFINEMENT; "resolved" = ~5 M cells,
wall-resolved layers). Switches: PRODCHECK_ITERS, PRODCHECK_TIMEOUT, PRODCHECK_KEEP, PRODCHECK_WALL_RESOLVED.
"""
import json, os, sys
from pathlib import Path
os.environ.pop("CFD_DIV_U", None)
RES = os.environ.get("PRODCHECK_RES", "coarse")              # "medium": the finer check (use mode "cold")
os.environ["GATE_RES"] = RES
HERE = Path(__file__).resolve().parent
OUT = Path(os.environ.get("PRODCHECK_RESULTS", HERE / f"gate_results_{RES}"))   # results folder (smoke tests elsewhere)
OUT.mkdir(parents=True, exist_ok=True)
os.environ["GATE_RESULTS"] = str(OUT)
sys.path.insert(0, str(HERE))
import gate  # noqa: E402

folder, tag = Path(sys.argv[1]), sys.argv[2]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 2
ref = str(HERE / "gate" / "refA_coarse")
mode = sys.argv[4] if len(sys.argv) > 4 else "morph"
fresh = mode in ("fresh", "cold")
extra = {} if mode == "cold" else {"warm_from": ref} if fresh else {"morph_from": ref, "warm_from": ref}
# PRODCHECK_ITERS: iterations (default 2000 cold, 1000 warm); PRODCHECK_TIMEOUT: seconds per OpenFOAM
# stage (Part 2's default 5 h is too short for fine/resolved meshes on few cores); PRODCHECK_KEEP=<dir>:
# keep the run folder there (a base state for bumps and the adjoint) instead of deleting it
iters = int(os.environ.get("PRODCHECK_ITERS", 2000 if mode == "cold" else 1000))
extra["stage_timeout_s"] = int(os.environ.get("PRODCHECK_TIMEOUT", 18000))
if os.environ.get("PRODCHECK_WALL_RESOLVED") == "1":
    extra["wall_resolved"] = True
half, health, secs = gate.solve(folder, n, iters, extra=extra, keep=True)
run = gate.latest_run_of(os.getpid())
fell = bool(run and (Path(run) / "MORPH_FALLBACK").exists())
d = gate.rec(half, health, secs, morph_fallback=fell, folder=str(folder), scheme="production linearUpwind", mesh="fresh" if fresh else "morph",
             resolution=RES, iterations=iters, n_proc=n, y_plus_min=float(health.y_plus_min), y_plus_max=float(health.y_plus_max))
if run:
    import re, shutil
    cm = Path(run) / "logs" / "checkMesh.log"
    if cm.exists():
        m = re.search(r"^\s*cells:\s*(\d+)", cm.read_text(), re.M)
        d["n_cells"] = int(m.group(1)) if m else None
    gate.save_forces(run, f"prodcheck_{tag}")
    keep = os.environ.get("PRODCHECK_KEEP")
    if keep:
        if Path(keep).exists():
            shutil.rmtree(keep)
        shutil.copytree(run, keep, ignore=shutil.ignore_patterns("processor*"))
        d["run_dir_kept"] = str(Path(keep).resolve())
    shutil.rmtree(run, ignore_errors=True)
(OUT / f"prodcheck_{tag}.json").write_text(json.dumps(d, indent=1, default=float))
print(json.dumps(d, default=float))
