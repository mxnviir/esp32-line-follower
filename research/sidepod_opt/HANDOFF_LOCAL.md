# Hand-off: the local agent (Claude Code on your PC)

You are Claude Code running on the owner's PC (MintyPC, Windows), with the GitHub CLI (`gh`)
already signed in. A cloud session started this work but cannot reach Codespaces; you can. Your
job is to run the heavy computing on GitHub Codespaces, fix whatever small problems come up, and
own the project log until the search is done. This file is meant to be enough on its own: the
project, the history, the method in detail, the technical reference, known pitfalls, then your
tasks.

Branch: **`claude/dazzling-ritchie-3q792g`**. Work only there; never push to `main` unless the
owner asks. Before every push: `git pull --no-rebase origin claude/dazzling-ritchie-3q792g` (the
cloud session and the codespace push to it too).

**Read next, in this order:** `research/sidepod_opt/ROUTES.md` (the dated status log, the single
source of truth: append to it, never rewrite history), then the rest of this file.

---

## 1. The project

**STEM Racing (formerly F1 in Schools), Professional Class.** Small CO₂-cartridge-powered cars
race 20 m on a track. The body is **milled from one foam block** (team process: 3-axis, 6.35 mm
ball-end cutter, set-ups from top, bottom, left and right); wheels, supports, nose and wings are
printed. The car is scored on **race time**. Rules come from the STEM Racing regulations (not in
the repo; rule numbers like T3.7, T4.2, T7.9 refer to them).

**The repository** (`mxnviir/stem-racing-paper`, formerly `esp32-line-follower`; codespace folder `/workspaces/stem-racing-paper`) holds the team's car
optimiser. The five parts must stay side by side:

| Folder | What it does |
|---|---|
| `part1-simulation` | the milled body as a level-set field with every rule as a hard mask; `machining.py` is the team's milling rule |
| `part2-simulation` | OpenFOAM half-car CFD (`openfoam_case.py`, `cfd_wrapper.run_half_car_cfd`) and the race-time model (`race_objective.py`, JAX) |
| `part3-simulation` | the links between 1 and 2; the "compass" (surface sensitivity map); its known-answer tests failed the ESI adjoint |
| `part4-simulation` | wheels, wings, supports, nose, joints, print files |
| `part5-simulation` | runs a whole car, the rule referee (`legality.py`), the search state machine |
| `research/` | **this work**: `APPROACH.md` (why the old search was wrong), `LITERATURE.md`, `sidepod_opt/` (the sidepod search) |

The car has never been built or track-tested. Every race time is a model number.

**The trial car.** `research/sidepod_opt/cad/trial_car.step`, the team's current design. The
sidepod search changes **only the sidepod region**; everything else is the team's exact CAD.

## 2. The problem we are solving

Give the optimiser the sidepod region and let it find, **on its own**, the lowest-drag sidepod:
any organic shape, channel or groove, as long as the team can mill it and every rule holds.
The owner's words: "I don't care about tunnels specifically, I just care about having the most
aerodynamic thing." Drag is judged by real-wall turbulent CFD (OpenFOAM, k-ω SST, rolling road,
rotating wheels, ~2.7×10⁵ Reynolds number).

**Why drag only:** at the 48.2 g weight floor (T3.6) the race-time slopes for this car are
0.18 ms per mN of drag and 7.5 ms per gram over the floor; the COM has no effect. Light designs
get lead up to the floor, so below it the sidepod question is a pure drag question. (The race
model is in `objective.py` if mass ever matters, e.g. a pod much bigger than the team's.)

**Reference numbers** (coarse mesh, production schemes, whole car D20 at 20 m/s):
team pod **0.362 N**, no pod **0.411 N**. Pods help on this car (~12 %), so the search is worth doing.

## 3. History: what was tried and what it taught (details in ROUTES.md)

1. **LBM test bench** (`research/sidepod_region`): lattice-Boltzmann at Re ~2×10³. Ranked sidepods
   wrongly (the car runs at ~2.7×10⁵). Removed; only full-Reynolds RANS is used now.
2. **Optimiser benchmark** (`research/optimiser_bench`): how CMA-ES, BO, SAIL, NEAT and SPSA cope
   with CFD noise. The production framework `sidepod_opt` (`campaign.py`, `methods.py`) supports
   them all; it is **route D**, the fallback.
3. **ESI adjoint gate** (`gate_results/RESULT.md`): the ESI adjoint's sensitivity vs measured ±1 mm
   bumps gave r = −0.5 with wrong signs. Later found to have solved a **different mesh** (375 k
   vs 520 k cells), so it was a setup mismatch, not a proven failure; still unretested on the
   matched mesh.
4. **First DAFoam attempts** (medium mesh, 520 k cells): out of memory (preconditioner > 15 GB,
   Jacobian colouring > 40 GB). The coarse test was set up but abandoned before DAFoam ran.
5. **Porous topology optimisation** (`topo/`, ESI `topO`): from an empty region it stalled; the
   carving run ended slower than no sidepod. Its gradient check failed, and we later found that
   check was **invalid**: `topologySens` is per unit volume and already includes the objective's
   porous term; `mill_topo.py` used it per cell and added the term again (fixed 2026-11-20).
6. **Evolution scored by the porous model** (`topo/mill_cma.py`): 18 % better than no pod in the
   porous model, **11 % worse** in real-wall CFD. Porous "solid" has no boundary layer, so thin,
   high-surface shapes look free. **Any optimiser driven by the porous model is steered wrongly.**
7. **2026-11-20 (this session), the breakthrough diagnosis:**
   - DAFoam Krylov on coarse production state A: colouring OK, then **GMRES stalled** at 1.87e-2.
   - Cause: the production flow (second-order `linearUpwind` U) **never settles** in the wake:
     residuals floor at ~1e-3 (U) and ~1e-2 (p), drag swings ±1.4 mN. A steady adjoint of an
     unsteady flow is ill-posed (the literature's "unstable in separated flow").
   - DAFoam's memory-light fixed-point adjoint is **Spalart-Allmaras only** (looks up `nuTilda`),
     so not an option with k-ω SST.
   - **First-order upwind U** makes the coarse flow steady: residuals 3e-6 / 1e-5, drag swing
     0.02 mN. But it reads **26 % more drag** (228.7 vs 181.0 mN half car).
   - DAFoam on that steady state: primal matches OpenFOAM exactly (228.722 vs 228.72 mN). GMRES
     converged 2.75e-2 → 1.9e-6 in 2000 iterations, then was **OOM-killed** at the last step (the
     product dR/dXv^T·ψ). With a 16 GB swap file the re-run finished: gradient written
     (`gate_results_coarse_up/dafoam/dafoam_sens.npz`, 3,457 surface points).
   - **Manufacturing:** an enclosed lengthwise tunnel cannot be milled (the mill fills it);
     grooves must be ≥ 6.35 mm (the cutter). Design within that.

## 4. The method (route A): what `shape_loop.py` does

A level-set shape optimisation of the sidepod, driven by the DAFoam discrete adjoint on real
walls, remeshed every step, every design projected onto what the mill can make.

**Design variable:** a field `f` on the car's 1 mm grid (`geometry.Car(h=1.0)`, STEP frame,
mm), **positive = foam**. Only cells in `car.region` matter; the rest is the team's CAD.

**One iteration:**
1. **Candidate.** The first time it is the seed itself; afterwards `f_try = f_cur − step·g/max|g|`.
2. **Build** (`Car.build`): `finish` (symmetrise, forced air: T7.9.2/T7.9.3 wheel wedges and the
   halo zone, forced foam: T4.2 cargo, locked spine) → `mill` (Part 1's rule: air the cutter can't
   reach becomes foam, sealed voids filled, loose pieces dropped) → `min_wall` (3 mm) → `check`
   (one piece, nothing outside the region changed, cargo inside, T3.7 clearance, walls ≥ 3 mm) →
   exact mesh (marching cubes clipped to the region, unioned with the exact CAD). Illegal → step halved.
3. **Export** the car folder (`car_half.stl` in the car frame, wheels, `assembly.json`, mass).
4. **Solve:** coarse real-wall OpenFOAM via `run_half_car_cfd`, `CFD_DIV_U="bounded Gauss upwind"`,
   cold the first time (2,500 iterations), afterwards a fresh snappy mesh warm-started from the
   last accepted run with `mapFields` (1,200 iterations).
5. **Accept or reject:** if D20 is not lower than the current design's, reject, halve the step and
   retry from the current design with the same gradient. Steps < 0.2 mm mean stop.
6. **On accept:** re-initialise `f` as the signed distance of the **milled** body (this folds every
   rule into the field), then the DAFoam adjoint on the accepted run.
7. **Gradient to the grid** (`grid_gradient`): per DAFoam surface point, dD/dn = dD/dXs · n (n =
   nearest vertex normal of the exported half-car STL), in N per mm; summed into the 1 mm cell
   holding the point (and its mirror, since the car is symmetric), region only, then Gaussian
   smoothing (σ = 2 mm). This is a crude Sobolev step that keeps the surface smooth.
8. **Sign:** dD/dn > 0 means moving that bit outward adds drag, so the field there **decreases**
   (the surface moves in). Hence `f − step·g`.

**What it can and can't do.** The surface can grow or carve anywhere in the region, and merge or
split pods; a gap between two growing parts can close over into a channel. It does **not** open a
hole in solid on its own, and it only takes steps that help **now**: a feature that is only good
once complete won't appear. Hence the multi-start seeds, and route D (global evolution) as a
complement.

**Seeds** (`shape_loop.seeds`, all build and pass the rules):

| seed | start | pod volume |
|---|---|---|
| `original` | the team's pod | 67.5 cm³ |
| `lean` | no pod (cargo cover only) | 5.0 cm³ |
| `blend` | halfway | 11.5 cm³ |
| `block` | the whole region foam, cut back by the rules | 152.6 cm³ |
| `channel` | the team's pod with an 8 mm outboard groove (open to the side, millable) | 57.3 cm³ |

**The gradient check (fixed before results).** ±1 mm Gaussian bumps at pod sites, each measured
by real CFD on the same steady model; the pair half-difference (D₊ − D₋)/2 needs no zero run.
Pass: every clear pair (≥ 3σ) has the predicted sign, and predicted/measured is within 0.5–2.
Judge: `dafoam/pair_judge.py`. (Full marks, for a longer check: Pearson r ≥ 0.9, signs ≥ 80 %.)

**The open question:** the steady model is a smoothed flow model (+26 % drag). Its gradient helps
only if it **ranks sidepod changes like the production model**. That is task 4, and no result may
be called "faster than the team's pod" before it.

## 5. Technical reference

**Frames and units**
- STEP frame: x forward (nose at +x), y left, z up, mm. The design grid lives here.
- Car frame (CFD): x from the nose tip towards the tail, z up from the track, m.
  `x_car = (x_nose_mm − x_step)/1000`, `x_nose_mm = 228.625`. Half car, y ≥ 0, symmetry plane at y = 0.
- D20, L20: drag and lift at 20 m/s. A half-car D20 is the mean of `total_x` in
  `postProcessing/forces/*/force.dat` (car + wheels); the whole car is 2×.

**Trial car spec** (`geometry.CarSpec`): region x 49.4–159.1 mm (STEP), |y| ≤ 32.5, z 1.5–40;
front axle x 173.25, rear 35.25, wheel r 14.12; cargo (T4.2, assumed) x 76–136, z 17–27; spine
|y| ≤ 13.5 & z ≥ 17 locked; halo zone x ≥ 115 & z > 27 forced air; mill set-ups "zy" (top,
bottom, left, right); floor 48.2 g; foam 0.163 g/cm³.

**CFD pipeline** (`part2-simulation`)
- Entry point: `cfd_wrapper.run_half_car_cfd(body_stl, n_subdomains, extra_surfaces, keep_run_dir, resolution, max_iterations, warm_from, morph_from, domain_reference_bounds, layer_overrides)`.
  `stopwatch.body_stl` extracts solid `car`; `stopwatch.extra_surfaces(folder)` gives the rotating wheels.
- Resolutions: `coarse` (~100 k cells here; ~7 min for 2,000 iterations on 4 cores), `medium`
  (~520 k, ~38 min), `fine`, `resolved`. The gate's domain: `gate.DOMAIN`.
- Run folders: `part2-simulation/cfd_case_template/runs/run_<pid>_<id>`, tagged per process, so
  parallel seeds don't collide.
- `morph_from` reshapes a reference mesh (lowest noise, small changes only; falls back to a fresh
  mesh and writes `MORPH_FALLBACK`). `warm_from` maps the reference's latest flow with `mapFields`.
- **`CFD_DIV_U`** (env, opt-in, added 2026-11-20): replaces `div(phi,U)`'s scheme. Unset = production.
- There is no `residualControl`: every solve runs its full iteration count, and health comes from
  force mean, stderr and drift.

**DAFoam** (Docker image `dafoam/opt-packages:v5.1.1`, 11 GB)
- `dafoam/make_case.py --src <run dir> --time <t> --out <case>`: copies mesh, fields, schemes;
  DAFoam runs 300 primal iterations from the converged state.
- `dafoam/run_docker.sh <case> <np>`: on first use it renumbers the mesh, converts it to ASCII and
  **deletes any colouring file**; afterwards (`.renumbered` present) it keeps the colouring.
- `dafoam/runScript.py`: objective D (`car`, `wheelF`, `wheelR`, x direction, ρ-scaled); output
  `dafoam_sens.npz` (`Xs`: surface points of `car`, car frame m; `dD_dXs`: N/m per coordinate; `D_N`).
- Settings that work: `DAF_ADJ=Krylov DAF_PC_FILL=0 DAF_PC_LEVEL=1 DAF_GMRES_RESTART=200 DAF_GMRES_ITERS=2000`.
  Hitting the iteration cap (PETSc reason −3) still writes the gradient.
- Costs (coarse, 4 ranks): primal ~50 s, colouring ~15 min (reusable while the mesh is unchanged),
  GMRES ~25 min, **memory peak ~15 GB plus the final product: needs RAM + swap ≥ ~24 GB per run**.

**OpenFOAM install** (Ubuntu): `curl -s https://dl.openfoam.com/add-debian-repo.sh | sudo bash`, then
`sudo apt-get install -y openfoam2412-default`, then source
`/usr/lib/openfoam/openfoam2412/etc/bashrc`. Python 3.11 venv with the pinned packages in
`codespace_loop_remote.sh`. Run everything on Linux (a Codespace), not on Windows.

## 6. Known pitfalls and their fixes

| Symptom | Cause | Fix |
|---|---|---|
| GMRES residual flat after ~100 iterations | unsteady primal (production linearUpwind U) | steady scheme `CFD_DIV_U="bounded Gauss upwind"` |
| `failed lookup of nuTilda` | DAFoam fixed-point adjoint is SA-only | use `DAF_ADJ=Krylov` |
| `signal 9 (Killed)` after "Computing d[aero_residuals]/d[aero_vol_coords]" | OOM in the final product | swap file (`fallocate -l 16G /swapfile; mkswap; swapon`), or ≤ 1 DAFoam run per ~24 GB |
| `docker pull` 429 Too Many Requests | Docker Hub rate limit | retry after a minute (the remote script retries) |
| restart from a converged state starts at time 0 | `startFrom startTime` in controlDict | `startFrom latestTime` |
| last time folder missing after a run | `writeInterval` not a divisor of the run length | pick an interval that divides it, or use the last written time |
| the fdcheck predicted 10⁸× too much | ESI `topologySens` is per unit volume | multiply by cell volume; don't re-add the direct term |
| a seed's channel or tunnel disappears | the mill fills what the cutter can't reach (≥ 6.35 mm, open to a set-up) | design grooves open to a side and ≥ 8 mm |
| a grep "error" watch fires on a healthy OpenFOAM log | "Time step continuity errors" is normal output | match `FOAM FATAL`, `Killed`, `Traceback`, `MPI_ABORT` instead |
| bump STL vertex count mismatch in a judge | bumps built on `gate/original_rm` (re-meshed original) | rebuild with `gate.py bumps` and `gate.py variant` |
| `gate/` folder missing on a fresh machine | it's git-ignored | rebuild: export `gate/original` (see `gate_cs_queue.sh`), `gate.py bumps`, variants |

**Stuck-loop symptoms:** steps rejected from the start (gradient direction wrong in practice), the
pod collapsing to the cargo cover (drag-only plus the 3 mm wall rule can favour nothing), or
`MORPH_FALLBACK` / meshing failures on odd shapes. Log the run, then lower `--step_mm`, raise
`--sigma_mm`, or move to another seed.

## 7. Your tasks, in order

### Task 1: confirm the gradient check

`git pull`, then read `research/sidepod_opt/gate_results_coarse_up/pair_judge.json` and the
latest ROUTES.md entry. The cloud session is measuring 3 pairs (`pod_rear`, `pod_front_low`,
`pod_rear_top`) on the steady model, verdict expected ~18:15 UTC on 2026-11-20.

- **Pass** (rule above): go to task 2.
- **Fail:** do not run the loop. Log it and tell the owner. Fallbacks: a stronger preconditioner on
  a bigger machine; the ESI shape adjoint on the same mesh; route D (`campaign.py`).
- **No result ever appears:** run the check yourself on a codespace.
  1. Build the steady state A: restart coarse state A with `div(phi,U) bounded Gauss upwind` (ROUTES.md 15:42 entry).
  2. Run DAFoam on it: `dafoam/make_case.py`, then `dafoam/run_dafoam_here.sh`.
  3. Measure the pairs: `CFD_DIV_U="bounded Gauss upwind" SKIP_ZERO=1 LANE_A="pod_rear pod_rear_m pod_rear_top" LANE_B="pod_front_low pod_front_low_m pod_rear_top_m" dafoam/coarse_bumps_here.sh gate_results_coarse_up`.
  4. Judge: `python dafoam/pair_judge.py gate_results_coarse_up/dafoam/dafoam_sens.npz gate_results_coarse_up`.

### Task 2: launch the search on a Codespace

Use Git Bash (or WSL) from the repo root on the PC:

```bash
bash research/sidepod_opt/codespace_loop.sh machines
```

Pick the largest machine: each seed needs 4 cores and ~16 GB RAM, plus swap (added automatically).
16 cores / 64 GB runs 3 seeds; 32 cores / 128 GB runs 5.

```bash
MACHINE=<name from the list> SEEDS="original lean block" NP=4 ITERS=12 HOURS=10 bash research/sidepod_opt/codespace_loop.sh start
```

On 32 cores, use all five seeds: `SEEDS="original lean blend block channel"`.

**Before starting:** codespaces bill per core-hour (16 cores × 10 h = 160 core-hours). Check the
owner's quota and billing and tell them the expected cost. About 40 min per accepted step per seed.

**First run = first real test of the loop.** The loop's geometry and gradient-mapping parts were
tested in the cloud, but it has **never run a full iteration with CFD and DAFoam**. Watch the first
iteration closely (`log`, `check`); expect to fix small things: paths, environment variables,
timeouts. Fix them in the repo, commit, `git pull` in the codespace (`gh codespace ssh`), restart.

### Task 3: monitor

Every 1–3 h (the idle timeout is 240 min; `check` keeps it alive):

```bash
bash research/sidepod_opt/codespace_loop.sh check
```

```bash
git pull --no-rebase origin claude/dazzling-ritchie-3q792g
```

Each seed's history is in `research/sidepod_opt/runs/<seed>/log.jsonl`. For a table:

```bash
python research/sidepod_opt/shape_loop.py show research/sidepod_opt/runs/<seed>
```

Watch for accepted steps with falling drag, rejections from the start, and `adjoint_error`
(`log` shows the job log; DAFoam's own output is at `runs/<seed>/it_NNN/dafoam.out` in the
codespace). After each milestone (first accepted step per seed, every few hours, the end), append
a dated entry to ROUTES.md with numbers, not adjectives, then commit and push.

### Task 4: does the steady model rank changes like the production model?

Solve each seed's best car (`runs/<seed>/best_car/`), the team's car and the no-pod car with
**production schemes** (no `CFD_DIV_U`), coarse then medium, using the same call as `gate.solve`.
The loop only helped if its best designs also beat the team pod there (0.362 N whole car, coarse).
If the rankings disagree, log it, then try a middle scheme (`CFD_DIV_U="bounded Gauss limitedLinearV 1"`):
does it converge steadily, and does GMRES still converge on it?

### Task 5: finish

- Delete the codespace (`codespace_loop.sh delete`) once `LOOP_DONE` shows or the budget ends.
- In ROUTES.md, per seed, record:
  - start and best drag on the steady model, and the best's drag on the production model;
  - pod volume;
  - a render (`render.py` or `topo/show_mill.py` as a template);
  - an honest verdict.
- Tell the owner in plain words what was found and what it cost.

## 8. Rules (non-negotiable)

- Pass marks and decision rules are written in ROUTES.md **before** a result and never moved after.
- Never present a steady-model result as a production or real-world result.
- A failed run is a result: log it. Never fill gaps with made-up numbers.
- Never paste or print tokens. Never push to `main`.
- Keep commits small and frequent: a codespace is reclaimed when deleted or idle for long.

## 9. Files and documentation

**Code you will run or fix**

| File | What it is |
|---|---|
| `research/sidepod_opt/shape_loop.py` | the search: `init`, `run`, `show`; `seeds()`, `grid_gradient()` |
| `research/sidepod_opt/codespace_loop.sh` | on your PC: `machines`, `start`, `check`, `log`, `delete` |
| `research/sidepod_opt/codespace_loop_remote.sh` | inside the codespace: setup, parallel seeds, push after every iteration |
| `research/sidepod_opt/geometry.py` | the car, region, rules, mill, checks, exact mesh, export |
| `research/sidepod_opt/design.py` | representations (Lattice, LevelSet, CPPN) for route D |
| `research/sidepod_opt/evaluators.py`, `campaign.py`, `methods.py` | route D (evolution / BO / SAIL scored by real CFD) |
| `research/sidepod_opt/gate.py` | the gate's solves, bump geometry, `DOMAIN`, `solve()` |
| `research/sidepod_opt/dafoam/` | `make_case.py`, `run_docker.sh`, `run_dafoam_here.sh`, `runScript.py`, `pair_judge.py`, `judge.py`, `coarse_bumps_here.sh` |
| `research/sidepod_opt/topo/` | the porous topology work (`mill_topo.py`, fixed); not used by route A |
| `part2-simulation/openfoam_case.py`, `cfd_wrapper.py`, `stopwatch.py` | the CFD pipeline |
| `part1-simulation/machining.py` | the team's milling rule |

**Documentation**

| File | Read for |
|---|---|
| `research/sidepod_opt/ROUTES.md` | **the status log**: routes, literature, every result |
| `research/sidepod_opt/README.md` | the sidepod pipeline, methods, evaluators, rates |
| `research/sidepod_opt/gate_results/RESULT.md` | the ESI adjoint gate and its correction |
| `research/APPROACH.md` | why the old whole-car search went wrong, and the plan |
| `research/LITERATURE.md` | literature for the whole car (adjoint, topology, milling constraints) |
| `research/sidepod_opt/EVOLUTION_SIMSCALE.md`, `SIMSCALE.md` | route D on SimScale (an alternative to codespaces) |
| `research/sidepod_opt/PARTS_PLAN.md` | wings, nose and wheel-support plan (next after the sidepods) |
| `part2-simulation/README.md`, `PROOF.md`, `CODESPACES.md` | the CFD: resolutions, noise, frozen states, earlier codespace use |
| `part3-simulation/README.md` | the compass and its known-answer tests |
| `part1-…/part5-…/README.md` | each part's modules |
