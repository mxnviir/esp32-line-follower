"""python run_one.py <method> <seed> <budget>  -> results/runs/<method>_s<seed>.jsonl + _best.npy"""
import sys, json, numpy as np, tempfile
from pathlib import Path
from region import Car
from tunnel import CarTunnel
from score import Scorer
import methods as M

STEPS, AVG_FROM = int(__import__("os").environ.get("STEPS", 1200)), int(__import__("os").environ.get("AVG_FROM", 500))
HERE = Path(__file__).resolve().parent


def setup(log_path, budget):
    car = Car(); tun = CarTunnel(car)
    base = json.loads((HERE / "results/base.json").read_text())
    sc = Scorer(car, base["drag_A"], base["lift_A"])
    warm = np.load(HERE / "results/state_A.npy")
    return M.Problem(car, tun, sc, warm, STEPS, AVG_FROM, budget, log_path)


if __name__ == "__main__":
    method, seed, budget = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    out = HERE / "results/runs"; out.mkdir(parents=True, exist_ok=True)
    tag = f"{method}_s{seed}"
    lp = out / f"{tag}.jsonl"; lp.write_text("")
    P = setup(lp, budget)
    rng = np.random.default_rng(seed)
    if method == "neat":
        M.run_neat(P, rng, tempfile.mkdtemp())
    else:
        M.METHODS[method](P, rng)
    np.save(out / f"{tag}_best.npy", P.best[1])
    print(tag, "best T", P.best[0], "runs", P.used, "illegal", P.illegal, flush=True)
