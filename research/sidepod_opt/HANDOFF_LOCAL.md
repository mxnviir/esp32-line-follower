# Hand-off: the local agent (Claude Code on your PC)

You are Claude Code running on the owner's PC (MintyPC, Windows), with the GitHub CLI (`gh`)
already signed in. A cloud session started this work but cannot reach Codespaces; you can. Your
job is to run the heavy computing on GitHub Codespaces and to own the project log until the
search is done.

**Read first, in this order:**
1. `research/sidepod_opt/ROUTES.md`: the plan, the literature, and the dated status log (every
   result so far). It is the single source of truth; append to it, never rewrite history.
2. This file.
3. Skim `research/sidepod_opt/README.md` (the pipeline: field → milled car → CFD → race time).

Branch: **`claude/dazzling-ritchie-3q792g`**. Work only there. Never push to `main` unless the owner asks.
Before every push: `git pull --no-rebase origin claude/dazzling-ritchie-3q792g` (the cloud session and
the codespace push to it too).

## 1. The goal

Give the optimiser the sidepod region of the STEM Racing car and let it find, on its own, the
lowest-drag sidepod it can: any shape, channel or groove, as long as the team's 3-axis milling
can make it and every rule holds. Drag is judged by real-wall turbulent CFD (OpenFOAM,
k-ω SST, rolling road, rotating wheels).

## 2. Where it stands (2026-11-20, ~17:30 UTC)

- **The method (route A):** a level-set shape optimisation driven by a DAFoam adjoint
  gradient, remeshed each step, with every design projected onto what the mill can make.
  Code: `research/sidepod_opt/shape_loop.py`.
- **Why it now works at all:** the production flow (second-order `linearUpwind` U) never settles
  in the wake, and a steady adjoint of an unsteady flow stalls (GMRES flat at 1.87e-2). With
  **first-order upwind U** the coarse flow is steady (drag swing 0.02 mN instead of 2.8 mN), and the
  DAFoam adjoint converged (2.75e-2 → 1.9e-6) and wrote a gradient:
  `gate_results_coarse_up/dafoam/dafoam_sens.npz`.
- **Cost of that switch:** the upwind model reads 26 % more drag (228.7 vs 181.0 mN half car). A
  gradient of it is only useful if it **ranks sidepod changes like the production model**. Not
  yet tested (task 4).
- **Running in the cloud session now:** the cut-down gradient check, 3 ± 1 mm bump pairs
  (`pod_rear`, `pod_front_low`, `pod_rear_top`) measured on the upwind model. Results land in
  `gate_results_coarse_up/bump_*.json`; the verdict will be `gate_results_coarse_up/pair_judge.json`
  plus a ROUTES.md entry, expected ~18:15 UTC.
- **Manufacturing facts already found:** enclosed lengthwise tunnels cannot be milled (the mill
  fills them); grooves must be ≥ 6.35 mm wide (the ball cutter). The seeds respect this.

## 3. Your tasks, in order

### Task 1: confirm the gradient check

`git pull`, then read `research/sidepod_opt/gate_results_coarse_up/pair_judge.json`.

- **Pass (fixed before the result):** every clear pair (measured ≥ 3σ) has the same sign as the
  prediction, and predicted/measured lies within 0.5–2 for each. Go to task 2.
- **Fail:** do not run the loop. Log it in ROUTES.md and tell the owner. The fallbacks are in ROUTES.md
  (stronger preconditioner on a bigger machine; ESI shape adjoint on the same mesh; route D,
  evolution scored by real-wall CFD with `campaign.py`).
- **If the file never appears** (the cloud session ended): run the check yourself on a codespace.
  Build the upwind state A as ROUTES.md describes (restart coarse state A with
  `div(phi,U) bounded Gauss upwind`), DAFoam on it (`dafoam/make_case.py` + `dafoam/run_dafoam_here.sh`),
  then `CFD_DIV_U="bounded Gauss upwind" SKIP_ZERO=1 LANE_A="pod_rear pod_rear_m pod_rear_top" LANE_B="pod_front_low pod_front_low_m pod_rear_top_m" dafoam/coarse_bumps_here.sh gate_results_coarse_up`,
  then `python dafoam/pair_judge.py gate_results_coarse_up/dafoam/dafoam_sens.npz gate_results_coarse_up`.

### Task 2: launch the search on a Codespace

Use Git Bash (or WSL) from the repo root on the PC:

```bash
bash research/sidepod_opt/codespace_loop.sh machines
```

Pick the largest machine. Each seed needs 4 cores and ~16 GB RAM; DAFoam's adjoint peaks ~15 GB.
16 cores / 64 GB runs 3 seeds; 32 cores / 128 GB runs 5. The script adds swap if RAM is short.

```bash
MACHINE=<name from the list> SEEDS="original lean block" NP=4 ITERS=12 HOURS=10 bash research/sidepod_opt/codespace_loop.sh start
```

On 32 cores, use all five seeds: `SEEDS="original lean blend block channel"`.

**Seeds** (all build and pass the rules):

| seed | start | pod volume |
|---|---|---|
| `original` | the team's pod | 67.5 cm³ |
| `lean` | no pod (cargo cover only) | 5.0 cm³ |
| `blend` | halfway | 11.5 cm³ |
| `block` | the whole region foam, cut back by the rules | 152.6 cm³ |
| `channel` | the team's pod with an 8 mm outboard groove | 57.3 cm³ |

**What one iteration does:** build and mill the design → coarse real-wall solve (steady scheme,
warm-started) → reject and halve the step if drag rose → DAFoam adjoint → smoothed level-set step.
About 40 min per accepted step on 4 cores; the colouring (~15 min) and GMRES (~25 min) dominate.

**Cost:** Codespaces bill per core-hour. 16 cores for 10 h is 160 core-hours. Check the owner's quota
and billing before starting, and tell the owner the expected cost.

### Task 3: monitor

Every 1–3 h (the idle timeout is 240 min; `check` keeps it alive):

```bash
bash research/sidepod_opt/codespace_loop.sh check
```

```bash
git pull --no-rebase origin claude/dazzling-ritchie-3q792g
```

Each seed's history is `research/sidepod_opt/runs/<seed>/log.jsonl`, one line per iteration, with drag
(`D20_half_N`), whether the step was accepted, `dD_mN`, step size, pod volume and DAFoam timings.
`python research/sidepod_opt/shape_loop.py show research/sidepod_opt/runs/<seed>` prints a table.

**What to watch for:**
- **Accepted steps:** drag should fall. Several rejections in a row followed by a step under 0.2 mm
  means converged, or a wrong gradient.
- **An `adjoint_error` line:** read `runs/<seed>/it_NNN/dafoam.out` in the codespace (`log` command).
  An OOM shows as "signal 9 (Killed)".
- **Rejections from the start:** the gradient direction may be wrong in practice even after the
  check passed. Stop and log it.

After each milestone (first accepted step per seed, every few hours, the end), append a dated entry
to ROUTES.md's status log (numbers, not adjectives), commit and push.

### Task 4: does the steady model rank changes like the production model?

On the same codespace, or a second smaller one, once the loop has produced designs: take the best car of
each seed (`runs/<seed>/best_car/`) plus the team's car (`gate/original`) and the no-pod car,
and solve each with **production schemes** (no `CFD_DIV_U`), coarse and then medium mesh, with
the same `run_half_car_cfd` call `gate.py` uses (`gate.solve`). The loop only helped if its best
designs also beat the team pod in the production model. The team pod reads 0.362 N whole car on
coarse production; no pod reads 0.411 N.

If the steady and production rankings disagree, log it, and try a middle scheme (`CFD_DIV_U="bounded Gauss limitedLinearV 1"`):
does it converge steadily, and does the DAFoam GMRES still converge on it?

### Task 5: finish

- Delete the codespace (`... codespace_loop.sh delete`) as soon as `LOOP_DONE` shows or the budget ends.
- Write the outcome in ROUTES.md: per seed, start and best drag (steady model), production-model
  drag of the best, pod volume, a render (`render.py` or `topo/show_mill.py` as a template), and an honest verdict.
- Tell the owner in plain words what was found and what it cost.

## 4. Rules (non-negotiable)

- Pass marks and decision rules are written in ROUTES.md **before** a result; never move them after.
- Never present a steady-model result as a production or real-world result. Every claim of
  "faster than the team pod" needs the production-model check (task 4).
- A failed run is a result: log it. Never fill gaps with made-up numbers.
- Never paste or print tokens. Never push to `main`.
- Keep commits small and frequent; the codespace is reclaimed when deleted or idle for long.

## 5. Files you need (all in the repo on this branch)

| File | What it is |
|---|---|
| `research/sidepod_opt/ROUTES.md` | plan, literature, status log |
| `research/sidepod_opt/shape_loop.py` | the search: `init`, `run`, `show` |
| `research/sidepod_opt/codespace_loop.sh` | run on your PC: `machines`, `start`, `check`, `log`, `delete` |
| `research/sidepod_opt/codespace_loop_remote.sh` | runs inside the codespace: setup + parallel seeds, pushes after every iteration |
| `research/sidepod_opt/geometry.py` | the car, region, rules, 3-axis mill, checks, STL export |
| `research/sidepod_opt/dafoam/` | `make_case.py` (DAFoam case from a solve), `run_docker.sh`, `run_dafoam_here.sh`, `runScript.py` (drag + dD/dXs), `pair_judge.py`, `coarse_bumps_here.sh` |
| `research/sidepod_opt/gate.py` | bump geometry, the gate's solves, `DOMAIN` |
| `research/sidepod_opt/gate_results_coarse_up/` | the steady-model check: base, bumps, DAFoam gradient, verdict |
| `part2-simulation/openfoam_case.py` | the CFD pipeline; `CFD_DIV_U` (opt-in) swaps the U convection scheme |
| `research/LITERATURE.md` | literature review for the whole car |
