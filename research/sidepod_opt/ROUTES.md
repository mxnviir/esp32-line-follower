# How to let the optimiser invent the sidepod: routes, literature, status

Started 2026-11-20. This is a living log: every result gets a dated entry under **Status log**.

**Goal:** give the optimiser the sidepod region and let it decide on its own what goes there
(channels, tunnels, undercuts, organic surfaces), judged by real turbulent CFD at the car's
Reynolds number (~2.7×10⁵, k-ω SST).

## Where we stand

| What was tried | Result | What it does and doesn't prove |
|---|---|---|
| ESI shape adjoint vs measured ±1 mm bumps (`gate_results/RESULT.md`) | r = -0.5, signs 3/6 | The two ESI adjoints solved **different meshes** (375 k cells) from the bumps (520 k). Setup mismatch, not proof that adjoint fails. |
| ESI porous topology from an empty region (`topo/`) | Stalled at the seed skin; the carving run ended slower than no sidepod | Porous solid with ~1.4 mm cells and no wall layers. |
| Gradient check of the millable topology adjoint (`topo/mill_coarse/fdcheck.json`) | Predicted dJ ≈ 2.6×10⁶, measured ≈ 0.02 | **The check is invalid, not the adjoint.** The prediction is ~10⁸ too large: a units bug in how `mill_topo.py` turns `topologySens` into dJ/dz is likely (e.g. a per-volume sensitivity not multiplied by cell volume, ~3×10⁻¹⁰ m³, or the alpha/betaMax scaling). The 3 mm step is too large: the front patch rose for both +3 and −3 mm. **The topology adjoint is untested.** |
| CMA-ES evolution scored by the porous model (`topo/mill_cma.py`) | 18 % better than no pod in the porous model, **11 % worse** in real-wall CFD | Stands on its own data: the porous model (no boundary layer on the solid) misranks thin, high-surface shapes. Any optimiser driven by it, gradient or not, is steered wrongly. |

Real-wall coarse CFD, whole car D20: team pod **0.362 N**, no pod **0.411 N**, evolved porous
design 0.456 N. Pods clearly help on this car (team is ~12 % better than none), so the search is
worth doing.

## The four routes

| Route | Can it invent? | Real walls in the loop? | Literature | Main risk here |
|---|---|---|---|---|
| **A. Free surface + real-wall adjoint, remeshed every step** | Yes: surfaces merge, split, close; new holes rarely open unaided (seed several starts, some with tunnels) | Yes | 3D, body-fitted, remeshed each step: published for **laminar** fluid and heat exchangers (Feppon, Allaire, Dapogny, Jolivet). Real-wall adjoint on cars: published, a few cycles, unstable in separated flow. 3D turbulent external drag: **not found** | Needs a gradient that passes its check (none yet) |
| **B. Porous cells (density topology)** | Most freedom | No (Brinkman penalisation) | Standard for internal ducts; turbulent versions exist; 3D external drag from empty: **not found** | Misranks shapes (measured above) |
| **C. Sharp surface on a fixed grid (immersed boundary + wall model)** | Yes | Approximately | 2D turbulent ducts published; a 2026 preprint says no established IB+RANS framework exists | Research code; nothing ready to run |
| **D. Evolution scored by real-wall CFD** | As much as the shape description allows (level set, CPPN) | Yes | Common and dependable | Many CFD runs; no gradient to speed it up |

**Two-stage A+B** (porous for a layout idea, export as surface, then polish with real-wall shape
optimisation) is supported by OpenFOAM since v2312 (porous or level-set topology, STL export) and
published as "topology to shape transition" in **2D internal** flow only (Koch et al. 2017).

**Commercial tools:** Siemens presents STAR-CCM+ adjoint topology optimisation for internal
fluid/thermal design (e.g. the HP duct) and adjoint **shape** morphing for external car aero. An
external topology case was **not found** in their material (that is not proof it can't be done).

**Bottom line:** route A assembles proven parts, but nobody has published the whole thing for a
3D turbulent external drag problem. Route D is the dependable fallback and is already built
(`methods.py`: cma, bo, sail, neat, spsa).

## Plan (route A, with D as fallback)

1. **Gradient gate on the coarse mesh** (this machine, ~100 k cells, ~5 min per solve).
   - Re-solve state A here; it must reproduce the committed 180.99 mN half-car D20 within ~0.5 mN.
     If not, every bump is re-run here so state A and its bumps come from one machine.
   - Measured ±1 mm bump pairs at the sidepod sites (`coarse_test.sh`).
   - DAFoam discrete adjoint on state A's own mesh and flow (fixed-point adjoint if Krylov runs out
     of the 15 GB here).
   - **Pass marks (fixed before the result, Part 3's):** Pearson r ≥ 0.9 and signs ≥ 80 % against
     the measured pair half-differences; steps ≤ 1 mm; only pairs whose measured difference is
     ≥ 3σ count towards signs.
2. **If DAFoam passes:** the loop. Real-wall solve → surface sensitivity → move the level set →
   milling rules (`geometry.py`) → remesh → repeat, from several seeds (team pod, none, team pod
   with tunnels cut).
3. **If it fails:** fix the topology check (units, ≤ 1 mm steps) and try the ESI shape adjoint on
   the bumps' own mesh; if both fail, run route D (BO/SAIL scored by real-wall CFD).
4. Every design is judged by ordinary real-wall CFD; finalists at the medium and fine meshes.

## Status log

- **2026-11-20**: this file. Machine: 4 cores, 15 GB, Ubuntu 24.04, Docker client present (daemon
  not running yet), dl.openfoam.com and Docker Hub reachable. Next: install OpenFOAM v2412, start
  Docker, re-solve coarse state A.
- **2026-11-20, set-up done.** OpenFOAM v2412 installed from dl.openfoam.com; Docker daemon
  started; DAFoam image `dafoam/opt-packages:v5.1.1` pulled (one Docker Hub 429 on the first try);
  Python deps in `/opt/py` (same pins as `codespace_gate.sh`). Bump geometry rebuilt here is
  identical to the committed `gate_results/bumps.json`. Coarse state A re-solve started 14:58 UTC.
- **2026-11-20, the topology check's bug, found in the OpenFOAM v2412 source.**
  - `topologySens<solver>` is a **per-unit-volume** density: `sensitivityTopO` accumulates
    `(U·Ua)·betaMax·interp'(beta)` + turbulence terms + the objective's own `dJdb` = `betaMax·|U|²`
    (`incompressibleAdjointSolver::topOSensMultiplier`, `objectivePowerDissipation::update_dJdb`),
    and nothing multiplies by the cell volume.
  - `topo/mill_topo.py::one_cycle` used it as a per-cell derivative (no `V`), then **added the
    objective's direct term again** (`BETA_MAX·|U|²·V`), which ESI had already included (in
    per-volume form).
  - So the predictions were too large by ~1/V (cells ~3×10⁻¹⁰–10⁻⁹ m³), matching the 10⁸ mismatch.
    Correct: `dJ/dbeta_i = topologySens_i · V_i`, no extra direct term.
  - The verdict on the topology adjoint stays **untested**; a re-check needs this fix and ≤ 1 mm
    steps. It does not rescue the porous route: the misranking was measured with real walls.
- **2026-11-20 15:05, coarse state A reproduced here:** 181.03 mN half car, 424 s on 4 cores
  (committed 180.99 mN). The two committed coarse bumps (`pod_rear`, `pod_front_m`) stay valid.
- **2026-11-20 15:31, DAFoam Krylov adjoint on coarse state A: stagnated.** The first DAFoam run in
  this repo to get past the Jacobian colouring: the earlier medium-mesh tries ran out of memory
  (preconditioner > 15 GB, colouring > 40 GB), and the earlier coarse test stopped before DAFoam.
  - DAFoam primal (300 its from state A): 182.17 mN, +1.1 mN (0.6 %) on OpenFOAM's state A, which is
    the size of a bump signal. Its last p solve still starts at ~1e-2.
  - Colouring 899 s, peak ~14.4 GB of 16. GMRES (restart 200, PC fill 0, level 1): 2.75e-2 → 1.89e-2
    in 100 iterations, then flat to 9 digits through 500. Killed; summary in
    `gate_results_coarse/dafoam_krylov/summary.log`.
  - **Likely cause: the flow, not the solver.** State A never settles (residual floor ~1e-3, force
    oscillation 1.5 % ≈ ±2.7 mN). A steady discrete adjoint of an unsteady wake is ill-posed: the
    "unstable in separated flow" failure mode in the literature.
  - **Decision rule, fixed before the probe:** run the fixed-point adjoint (no colouring, no PC).
    - If its residual falls steadily by ≥ 3 orders, the preconditioner was the problem: let it
      finish, run the bumps, judge against the marks above.
    - If it floors or grows, the primal is the problem: build a smoothed testbed (first-order
      upwind U/k/ω on the coarse mesh, converged ≥ 4 orders, force oscillation ≪ 1 mN), re-solve
      state A and the bumps with those schemes, and re-run DAFoam. That tests the gradient on a
      smoothed flow model, not the production schemes.
    - Either way, the ESI shape adjoint on `refA_coarse`'s own mesh is the second candidate; the
      current-scheme bumps serve it.
- **2026-11-20 15:40, the fixed-point probe can't run with k-ω SST.** DAFoam v5.1.1's
  `DASimpleFoam::runFPAdj` looks up `nuTilda` (Spalart-Allmaras only) and crashed. For k-ω SST,
  Krylov is DAFoam's only adjoint. So the diagnosis moves to the flow: state A restarted with
  first-order upwind U (k and ω were already upwind) for 3000 more iterations
  (`gate/refA_coarse_up`). If it converges ≥ 4 orders with force oscillation ≪ 1 mN, Krylov is
  re-run on it; the colouring depends only on the mesh, so the 15 min colouring is reused.
- **2026-11-20 15:42, the upwind-U state is steady.**

  | | production (linearUpwind U) | first-order upwind U |
  |---|---|---|
  | Ux / p initial residual at the end | ~1e-3 / ~1e-2 | 3e-6 / 1e-5 (flat from it. ~2250) |
  | half-car Fx, mean of last 500 its | 181.04 mN | 228.72 mN (**+26 %**) |
  | Fx range over last 500 its | 2.80 mN | 0.02 mN |

  So the non-convergence is the second-order convection on this wake, and first-order upwind
  removes it, at the cost of a much more diffusive flow model. A gradient of this model is only
  useful if the model **ranks sidepod changes like the production model does**: the same ±1 mm
  bumps must be measured with both schemes (rank check), on top of the adjoint-vs-measured check.
  If the ranking disagrees, try a middle scheme (e.g. `limitedLinearV 1`, a TVD scheme) that may
  converge with less smearing. DAFoam Krylov launched on this state (`gate/dafoam_coarseA_up`);
  the colouring is recomputed (`run_docker.sh` deletes it before renumbering).
- **2026-11-20 16:08, DAFoam Krylov on the steady state converges (slowly).** Primal 228.722 mN
  = OpenFOAM's 228.72 (the production state was 1.1 mN off). Colouring 944 s. GMRES residual
  2.75e-2 → 1.52e-2 (100) → 4.0e-3 (200) → 3.3e-3 (300) → 1.47e-3 (400), where the unsteady state
  stalled at 1.87e-2. **The stall was the unsteady primal**, as diagnosed. The 1e-6 relative
  target is out of reach in 2000 iterations at this rate; whether the partly converged gradient is
  good enough is exactly what the bump check decides.
- **2026-11-20 16:23, gradient solved, then killed by memory at the last step.** GMRES hit its
  2000-iteration cap at 1.9e-6 (from 2.75e-2: 7e-5 relative), then the final product
  dR/dXv^T·ψ (which turns ψ into surface sensitivities) was OOM-killed on 16 GB. Added a 16 GB swap
  file; re-run with the saved colouring (skips 15 min).
- **2026-11-20, user decision:** overlap the remaining check with building the loop. A cut-down
  check (3 ± pairs on the steady model, little noise) must agree in sign and roughly in size
  before the loop's results are trusted.
- **2026-11-20, `shape_loop.py` written** (route A loop): seed field → `Car.build` (rules, 3-axis
  mill, min wall, checks) → coarse real-wall solve (steady scheme, warm-started) → reject and halve
  the step if drag rose → DAFoam Krylov → dD/dn per surface point → 1 mm grid (mirrored, region
  only) → Gaussian smoothing (2 mm) → level-set step, re-initialised as the signed distance of the
  milled body. Seeds `original`, `lean`, `blend`, `block`, `channel` all build and pass the rules.
  Cost per accepted step here: ~40 min (most of it colouring + GMRES); multi-start needs more
  cores or colouring reuse (morph steps between remeshes).
- **Manufacturing finding:** an enclosed lengthwise tunnel **cannot be milled**. The team's 3-axis
  process (top, bottom, left, right set-ups) can't reach a bore along x; the mill rule filled a
  5 mm bore through the team pod (pod 66.5 vs 67.5 cm³). Only open channels and grooves reachable
  from a set-up direction are buildable, so the search can't produce closed tunnels, by the rules
  of the process rather than any limit of the method. The open `channel` seed came out at 22.4 cm³
  (first version: the slot was oversized and cut the outer pod loose). Fixed: an 8 mm outboard groove (the 6.35 mm ball must fit; a 6 mm one was refilled), seed now 57.3 cm³ and buildable.
- **2026-11-20 17:33, local agent takes over (owner's PC, Linux, `gh`).** Fixes before any launch:
  the repo is now `mxnviir/stem-racing-paper`, so every codespace script cd'd into a folder that
  doesn't exist (`/workspaces/esp32-line-follower`); fixed. `shape_loop.py`: if DAFoam fails after
  an accepted step, the next start re-runs the adjoint on that design (`grad_ready`) instead of
  stepping along a stale or missing gradient; the codespace runner retries once. Swap is now
  sized at 24 GB per seed (was 16). **Pass rule for the 3-pair check, written before the result**
  (from HANDOFF_LOCAL.md §4): measured pair half-difference (D₊ − D₋)/2; every clear pair
  (|Δ| ≥ 3σ) must have the adjoint's predicted sign, and predicted/measured must be within 0.5–2.
  Judge: `dafoam/pair_judge.py`. Fail → the loop is not run.
- **2026-11-20 17:57, bumps lost twice to container restarts.** The cloud container restarted at
  ~17:41 and ~17:57, both while the session sat idle between messages; the detached bump jobs died
  right as their solvers started. Files, installs and the gradient survived; swap had to be
  re-enabled. Lesson: in this cloud session, long jobs survive only while a session-tracked
  background task is running. Relaunched 17:57 with a tracked watcher; expected ~19:20 UTC.
- **2026-11-20 18:15, local agent: 4-core codespace prepared, then stopped (owner's call; resume ~19:35).**
  The account offers only 2- and 4-core machines (`standardLinux32gb`: 4 cores, 15 GB RAM, 32 GB disk
  + 118 GB `/tmp`). Set up `sidepod-shape-loop-5p94vxwg4xpcvx79`: OpenFOAM v2412, DAFoam image
  (containerd store, fits), Python stack (imports OK after two PyPI timeouts; runner now retries
  with gentler downloads). Swap works only on `/tmp` (17 GB; it's re-created on restart, as `/tmp`
  is wiped when the codespace stops). Main disk 4.4 GB free for CFD runs: watch it. Plan: one seed
  (`original`) once the 3-pair check passes.
- **2026-11-20 18:45, STOP: do not run `shape_loop.py` as it stands (dry run with the real gradient, no CFD).**
  From the `original` seed, a 1.5 mm step flips **18 voxels** of a 67,000 mm³ pod; a 0.75 mm step
  flips **none**. Causes: (1) the step is normalised by max|g|, and the gradient has a hot spot (the
  median surface cell is 0.7 % of the max, the 99th percentile 24 %); (2) the field is the EDT
  difference of binary voxels, which jumps from −1 to +1 across the surface, so nothing moves until
  a cell changes by a full 1 mm, and all sub-voxel progress is erased at each re-initialisation;
  (3) the objective is drag only, while at the weight floor foam costs 1.22 ms per cm³, the same
  order as the drag sensitivity. Fix in progress in the cloud session (sub-voxel surface from the
  continuous field, percentile-normalised clipped step, race-time objective with the mass price,
  morph-first meshing). Wait for the commit "shape_loop v2".
- **2026-11-20 18:50, gradient check, 2 of 3 pairs in: both pass.** Steady model, coarse, ±1 mm,
  noise 0.0025 mN per pair.

  | site | measured (D₊ − D₋)/2 | adjoint | predicted / measured |
  |---|---|---|---|
  | `pod_rear` | −1.500 mN | −1.635 mN | 1.09 |
  | `pod_front_low` | −0.690 mN | −0.458 mN | 0.66 |

  Each bump against the unbumped state is nearly antisymmetric (−1.53 / +1.47 and −0.81 / +0.57 mN),
  so 1 mm is inside the linear range. `pod_rear_top` (predicted +0.24 mN, the opposite sign) is running.
- **2026-11-20 19:00, `shape_loop.py` v2** (replaces the version stopped at 18:45). Tested without
  CFD on the real gradient, from the `original` seed:
  - **Surface from the continuous field:** a true signed distance (slope 1), re-distanced at 4×
    resolution; the CFD surface is cut from the field wherever the rules left the voxels alone. A
    uniform 0.1 / 0.3 / 0.6 mm shift now changes the mesh volume by 0.9 / 3.4 / 6.9 cm³ (v1: nothing
    below 1 mm). The seed's mesh volume equals the CAD's (157.522 cm³).
  - **Step:** normalised by the 95th percentile of |g| on the surface band, clipped to ± step. A
    1.5 mm step moves 44 % of the surface band by more than 0.1 mm (v1: 18 voxels). Gradient on
    moves the rules forbid (growth through the legal block's faces, cargo foam) is zeroed first:
    3 % of the total.
  - **Objective = race time**, with foam volume priced by a multiplier (0 while lead remains, at
    most the true 1.22 ms/cm³ once it is gone). From the team pod the first step is close to
    volume-neutral (−0.2 cm³ of 67).
  - **Meshing:** the last accepted mesh is reshaped onto the new body (the gate's low-noise path),
    fresh mesh on failure. A step is accepted only if the solve converged and race time fell.
  - **Running gradient check:** every step logs the first-order prediction beside the measured change.
    The first-order prediction for the first 1.5 mm step is −69 mN whole car (−15 %), far more than
    a linear model can be trusted for; the measured value of step 1 is the first real test of
    the method at design scale.
- **2026-11-20 19:00, v2 additions and the early production ranking check (rule fixed before any result).**
  - Smoothing σ 2 → 4.5 mm (the gate validated ~10 mm bumps; the coarse car patch has 3,457 points).
  - Accept margin: race time must fall by the equivalent of 0.4 mN whole-car drag. The pair
    half-sums show a −0.03 / −0.12 mN half-car morph offset or curvature, and noise is 0.0025 mN,
    so a bare "T lower" would accept slightly worse steps late in a run.
  - A step that falls back to a fresh mesh is rejected: it isn't comparable with the morph lineage.
  - `morph_drift`: the morphed CFD car surface against the designed STL, logged every step.
  - `run_loop_here.sh`: one iteration at a time, commit after each, resumes after a restart.
  - **Early production ranking check.** After 2–3 accepted steps, morph production state A
    (`gate/refA_coarse`, linearUpwind, no `CFD_DIV_U`) onto the current best car, solve 1,000
    iterations, and compare with the committed production zero run (`gate_results_coarse/zero.json`,
    181.58 mN half car, stderr 0.44 mN).
    - **Pass:** the production change has the same sign as the steady model's cumulative change
      from the seed, and |change| ≥ 3σ (≈ 1.5 mN half car; σ from both runs' stderr).
    - **Fail** (opposite sign at ≥ 3σ): stop the loop. The steady model is misranking.
    - **Inconclusive** (< 3σ): continue, and repeat after more accepted steps.
- **2026-11-20 19:13, GRADIENT CHECK PASSED (3 of 3 pairs, steady model, coarse, ±1 mm).**

  | site | measured (D₊ − D₋)/2 | adjoint | predicted / measured |
  |---|---|---|---|
  | `pod_rear` | −1.500 mN | −1.635 mN | 1.09 |
  | `pod_front_low` | −0.690 mN | −0.458 mN | 0.66 |
  | `pod_rear_top` | **+0.251 mN** | **+0.242 mN** | 0.97 |

  Signs 3/3 (each ≥ 100σ; noise 0.0025 mN), every ratio within 0.5–2, Pearson r = 0.98. The
  opposite-signed, small `pod_rear_top` effect is predicted within 4 %. The DAFoam Krylov adjoint
  on the steady (first-order upwind U) coarse flow is trustworthy for small sidepod moves.
  `gate_results_coarse_up/pair_judge.json`. Next: `run_loop_here.sh cloud_original original` here.
- **2026-11-20 19:55, the loop works at design scale: step 1 accepted, −3.8 % drag (steady model).**
  Run `runs/cloud_original` (seed: the team's pod), this machine, 4 cores.
  - **Iteration 0 (the seed):** fresh mesh, 449.24 mN whole car (steady model; the gate's 228.7 mN
    half car was a mesh of the exact CAD, this is the re-surfaced body), converged, stderr 0.002 mN.
    DAFoam primal 224.607 vs OpenFOAM 224.619 mN half car; adjoint 27 min.
  - **Step 1 (1.5 mm, σ 4.5 mm):** on the morphed mesh (no fallback), **432.25 mN (−16.99 mN, −3.8 %)**.
    First-order prediction −43.4 mN; measured / predicted = 0.39, nonlinear but the same direction.
    83 % of the pod surface moved by > 0.1 mm.
  - **Mass:** pod 67.5 → 68.0 cm³ voxels, +1.47 cm³ mesh; foam +0.24 g, the last 0.05 g of lead gone:
    +0.19 g over the floor (≈ +1.4 ms) against ≈ −3.1 ms from drag. The multiplier aimed for zero
    volume change: `step_field`'s volume estimate (occupancy ramp) under-reads the mesh's change.
    The decision uses the exact mass, so it is still correct; the step is just less mass-efficient
    than intended. To fix between runs, not mid-run.
  - `morph_drift` can't read a fresh (binary) mesh; it works on morphed steps (ASCII).
- **2026-11-20 20:45, EARLY PRODUCTION RANKING CHECK PASSED.** Production schemes (linearUpwind U),
  production state A's coarse mesh morphed onto each car, warm-started, 1,000 iterations
  (`prodcheck.py`, `gate_results_coarse/prodcheck_*.json`):

  | car | production D20 half car | stderr |
  |---|---|---|
  | seed (team pod, re-surfaced) | 179.92 mN | 0.42 mN |
  | step 1 | **173.08 mN** | 0.51 mN |

  Change −6.84 ± 0.66 mN (10σ), against the steady model's −8.50 mN half car: same sign, 80 % of the
  size. Rule (fixed at 19:00): same sign and ≥ 3σ. **Pass.** On this change, the steady model ranks
  like the production model. (Seed vs the exact-CAD zero run, 181.58 mN: the re-surfacing itself is
  worth −1.7 mN.)
- **2026-11-20 20:45, loop status** (`runs/cloud_original`, steady model, whole car):

  | it | step | D20 | change | result |
  |---|---|---|---|---|
  | 0 | seed | 449.24 mN | | accepted |
  | 1 | 1.5 mm | 432.25 mN | −16.99 (pred −44.8) | accepted |
  | 2 | 1.5 mm | 429.13 mN | −3.11 (pred −24.9) | rejected: morph failed checkMesh, fresh mesh not comparable |
  | 3 | 0.75 mm | **428.90 mN** | −3.34 | accepted; adjoint running |

  Total −20.3 mN (−4.5 %). Measured/predicted falls with step size (0.38 at step 1), the usual sign
  of curvature, so the shrinking steps are working as intended. Watch: repeated morph fallbacks as
  the shape drifts from the seed's mesh. If they recur, re-base the lineage (re-solve the current
  design on a fresh mesh and continue from it).
- **2026-11-20 21:00, re-basing added** (takes effect from iteration 4; each iteration is a fresh
  process). When the lineage's mesh can't be morphed onto a candidate (`MORPH_FALLBACK`): solve the
  current design on a fresh mesh, make it the reference (its gradient stays valid, same design),
  and morph the candidate from it, so both numbers share a mesh. Before this, every fallback was
  a rejection with the step halved, so repeated fallbacks would have shrunk the steps to nothing.
- **2026-11-20 21:55, step 4 accepted; then its adjoint stalled; fallback added.**
  - Step 4 (0.75 mm): **427.09 mN (−1.81)**, morphed mesh (skewness 2.9, Mesh OK). Drift of the CFD
    surface from the design: mean 0.018 mm, p99 0.16 mm. Total so far **−22.15 mN (−4.9 %)**.
  - Its DAFoam adjoint stalled: GMRES 2.6e-2 → 9.0e-3 by iteration 200, then flat to 2000 (reason −3,
    "Adjoint solution failed"). Iterations 0, 1 and 3 converged with the same settings. The flow is
    steady (OpenFOAM and DAFoam agree to 0.01 mN; residual p 7e-6) and the mesh passes checkMesh,
    so this design's linear system is harder for the memory-limited preconditioner (fill 0).
  - The wrapper's identical retry was stopped by hand: same inputs, same stall, 40 min each.
  - **Fallback (`_use_stale_gradient`):** when an adjoint fails, step along the last good gradient
    (here it 3's: a design ≤ 0.75 mm away), at most 2 accepted designs in a row. Every step is
    still judged by real CFD. Run restarted 21:55 on it 3's gradient.
  - If stalls recur, the fixes (memory permitting): GMRES restart 200 → 400, or preconditioner
    fill 0 → 1 on a bigger machine.
- Render of the changes so far: `runs/cloud_original/shape_change.png`. The outer front corner is
  chamfered, the inboard leading face filled, the rear lower outboard corner tapered towards the
  rear wheel (boat-tail), and a scoop cut at x ≈ 145–155 mm from the nose; mid-width sides bulge a
  few tenths, and the outermost flank is pulled in.
- **2026-11-20 23:56, run `cloud_original` (seed: the team's pod) CONVERGED to a local optimum.**

  | it | step | D20 whole car (steady) | race time | result |
  |---|---|---|---|---|
  | 0 | seed | 449.24 mN | 0.76486 s | accepted (fresh mesh) |
  | 1 | 1.5 mm | 432.25 | 0.76319 | accepted |
  | 2 | 1.5 mm | 429.13 | | rejected: morph failed (fresh mesh) |
  | 3 | 0.75 mm | 428.90 | 0.76244 | accepted |
  | 4 | 0.75 mm | 427.09 | 0.76151 | accepted; adjoint stalled (morphed mesh) |
  | 5 | 0.75 mm | 428.26 | | re-based (it 4 on a fresh mesh: 423.85); rejected (+4.4, stale gradient) |
  | 6 | 0.375 mm | 421.83 | 0.76027 | accepted; adjoint converged on the re-based mesh |
  | 7 | 0.375 mm | 419.18 | 0.75982 | accepted |
  | 8 | 0.375 mm | **416.05** | **0.75927** | accepted, **best** |
  | 9 | 0.375 mm | 416.99 | | rejected |
  | 10 | 0.19 mm | 415.85 | | rejected: −0.19 mN, under the 0.4 mN margin; step < 0.1 mm → stop |

  - **Best (it 8) vs the team's pod, steady model:** −33.2 mN whole car (**−7.4 %**), race time
    **−5.6 ms**. Mass +0.06 g (69.41 g), pod 67.5 → 68.7 cm³. Fresh-vs-fresh check at it 4
    (−25.4 mN against the lineage's −22.2) says the gains aren't a morph artefact.
  - **Lessons:**
    - adjoints converge on fresh or lightly morphed meshes and can stall after several morphs;
      re-basing fixes both the morph failures and the stalls;
    - measured/predicted runs 0.3–0.7: curvature, so the step control matters;
    - with the 0.4 mN margin the run ends once a step's gain drops below ~0.4 mN.
  - **Next, on this machine:** the production check of it 8's car (`prodcheck_best_it8`, coarse,
    morphed from production state A; it may fall back to a fresh mesh this far from the seed, which
    is then noisier), and run **`cloud_lean`** (seed: no pod, 10 g of lead available, so foam is
    free at first): can it grow a pod of its own, and how does it compare with the team's?
- **2026-11-21 00:15, production check of the final design: inconclusive so far, chain queued.**
  - `prodcheck_best_it8`: the morph from production state A failed (8 steps away), so a fresh mesh:
    170.48 mN half car, stderr 1.63 mN, force swing 3 %. Against the seed's 179.92 mN on the morph
    path that is −9.4 mN, but fresh vs morphed with the production wake is not a fair comparison.
  - Queued: (1) `prodcheck_seed_fresh`, the seed on a fresh mesh with identical settings (fresh vs
    fresh); (2) `prodchain.py`, production state A morphed through the loop's accepted designs
    1 → 3 → 4 → 6 → 7 → 8 in order, each from the previous link: one low-noise lineage. If a link's
    morph fails the chain stops (no fresh-vs-morph mixing). This is the decisive production check
    of the run.
  - `cloud_lean` (no-pod seed) started 23:56. Seed: 493.38 mN whole car (steady). The team's pod
    is worth −9 % over no pod in the steady model (production: −12 %), consistent.
- **2026-11-21 01:12, PRODUCTION CHECK OF THE WHOLE RUN (`cloud_original`): the gain is real, the
  late polish isn't.** Production schemes, coarse. Chain 1 morphs from production state A
  (`prodchain_cloud_original.json`); chain 2 re-bases at design 4 on a fresh mesh against the seed's
  fresh-mesh result (`prodchain_cloud_original_f4.json`). Half car:

  | design | production change vs seed | steady model | ratio |
  |---|---|---|---|
  | 1 | −6.86 mN (morph chain) | −8.50 | 0.81 |
  | 3 | −9.05 mN (morph chain) | −10.17 | 0.89 |
  | 4 | −8.39 mN (fresh base) | −12.7 | 0.66 |
  | 6 | −9.10 mN | −13.7 | 0.66 |
  | 7 | −8.76 mN | −15.0 | 0.58 |
  | 8 | **−8.16 mN** | −16.6 | 0.49 |

  Fresh-vs-fresh, design 8 against the seed: −10.37 mN (170.48 vs 180.85; seed fresh vs seed morph
  differ by 0.9 mN, so mesh scatter is ~1 mN here).
  - **Verdict:** the final design beats the team's pod by **8–10 mN half car in the production
    model (−4.5 to −5.7 %, ≈ 3–4 ms of race time)**. The big early steps carry over almost fully
    (81–89 %). Once production plateaus (from design 3–4), the steady model's further −6 mN of
    polish isn't confirmed: it optimises quirks of its own smoothed flow.
  - **Method change:** production-check every few accepted steps, keep the design where production
    is best, and stop a run once production stops improving (two checks without gain beyond ~1 mN).
    For `cloud_original` the production-best is design 6 (−9.10) or 3 (−9.05), within noise of 8.
- **2026-11-21 01:12, `cloud_lean` (no-pod seed): iteration 0 done.** 493.38 mN whole car (steady),
  adjoint OK. Production checks of its designs run every 3 accepted steps, from its own production
  seed run.
- **2026-11-21 05:00, `cloud_lean` (no-pod seed): the steady model grows a pod; production barely confirms it.**

  | design | steady D20 whole car | pod | production half car (fresh) | vs no pod |
  |---|---|---|---|---|
  | 0 (no pod) | 493.38 mN | 5.0 cm³ | 206.19 ± 0.33 | |
  | 3 | 484.45 | 9.2 | | |
  | 4 | 479.52 | 10.8 | 203.91 ± 0.34 | **−2.28** |
  | 5 | re-based 476.29; candidate rejected | | | |
  | 7 | 473.66 | ~12 | 204.30 | **−1.89** |

  - Steady: −19.7 mN whole car (−4.0 %) in 7 iterations, gains accelerating once the pod passed
    ~8 cm³. Production: −2.3 then −1.9 mN half car, where the steady model says −6.9 then −9.9:
    ratio ~0.3, and steps 5–7 add nothing in production.
  - The team's pod is worth −25.3 mN half car in production. **From no pod, this method recovers
    < 10 % of that.** The steady model's compass is much weaker on a small, young pod than on
    the team's (ratio 0.8–0.9 for the big early steps there).
  - Stop rule: this is the first production check without a gain. One more after ~3 accepted
    steps; if that doesn't gain > 1 mN either, the run stops. **Conclusion so far: a good
    starting shape matters, and the method improves a pod far better than it invents one.**
- **2026-11-21 05:20, how to get invention: literature and plan (route E, "explore, then refine").**
  Owner's question after the two runs: can anything invent its own geometry well?
  - **Why the adjoint loop can't, by itself.** It is a local method, and the literature treats
    that as a known property: aerodynamic design spaces opened up to new concepts are multimodal
    (Chernukhin & Zingg; Bons et al. 2019), and a gradient method lands in the basin it starts in.
    Our two runs are a clean example: from the team's pod, −5 % (production); from no pod, < 10 %
    of the team pod's benefit recovered.
  - **What the literature uses for invention:**
    1. *Global search plus adjoint refinement* (memetic / hybrid): an evolutionary or surrogate
       search finds the basins, the adjoint polishes inside them (Kontoleontos, Asouti &
       Giannakoglou 2012, CFD shape optimisation; Zingg's hybrid and multistart optimisers).
    2. *Surrogates that eat adjoint gradients* (gradient-enhanced kriging, Bayesian optimisation
       with gradients): each CFD + adjoint gives a value and a whole gradient, so the global model
       needs far fewer runs (Bouhlel & Martins; Wang et al. 2018; Müller et al. 2024).
    3. *Quality-diversity search* (MAP-Elites, SAIL): returns many different good designs, not
       one; shown on 2D airfoils and a 3D velomobile with real flow simulation (Gaier et al.).
       `methods.py` already has `sail`, `bo`, `cma`, `neat`.
    4. *Topological derivatives with level sets*: a map of where inserting material helps, used to
       nucleate new features that a level set alone never creates (Allaire et al.; Amstutz 2005 for
       Navier-Stokes; Sá & Novotny for channels). Published for Stokes/laminar internal flow only.
  - **What tonight's numbers make possible.** A production-scheme coarse solve on a fresh mesh
    costs ~6 min on 2 cores, with ~1 mN mesh scatter; concepts differ by tens of mN (no pod vs
    team pod: 25 mN half car). So a global search can be scored **directly by the production
    model**: ~20 designs an hour on this 4-core machine, ~150 an hour on 32 cores. The steady model
    and the adjoint (45 min a step) are only needed for the refinement stage, where they work.
  - **Route E:**
    1. *Explore*: quality-diversity / Bayesian search over a low-dimensional concept space (the
       lattice or CPPN representations in `design.py`), every design milled, rule-checked and scored
       by production coarse CFD on a fresh mesh; 200–500 designs.
    2. *Refine*: `shape_loop.py` from the best 3–5 distinct concepts, production check every
       3 accepted steps, stop when production stops improving.
    3. *Verify*: medium mesh, then a physical test.
    Optional research add-on: a topological-sensitivity map from DAFoam (its `alphaPorosity`
    derivative on the real-wall flow) to propose where to seed new material.
  - **Probe running now** (production, fresh meshes): blends of no pod → team pod at 50 / 75 / 90 %,
    the full `block` and the `channel` seed. It shows whether the landscape between "no pod" and
    "pod" is a smooth slope (then the steady model's compass is what failed) or has a plateau or
    valley (then no local method can cross it), and gives the first concept-scale scores.
- **2026-11-21 05:45, objective = race time, including its gradients; ballast; whole-car scope (owner).**
  - **Already in place:**
    - every accept/reject in `shape_loop.py` uses Part 2's race model with CFD drag and lift plus
      the exact mass;
    - lead ballast tops the car up to 48.2 g automatically: in the T1.22 container under the halo,
      up to 15.8 g (1.39 cm³); beyond that the car is illegal.
  - **Added:** the step direction now carries the exact centre-of-mass gradient
    (`objective.mass_cell_gradient`) on top of drag and the mass price. Logged as `com_grad_share`.
    Effective for new runs. Lift is left out of the adjoint: its slope is −0.002 vs 0.188 s/N for drag.
  - For this car the race model's COM slopes are exactly 0 (the thrust never lifts a wheel pair),
    and pitch balance, guide friction and rolling are placeholders, never calibrated (APPROACH.md §4).
    A layout optimum that leans on those terms can't be trusted until they're measured.
- **Whole-car design rules from the owner (2026-11-21):**
  - layout variables: halo x (`d_halo`), rear axle x, wheelbase (`W`; front axle = rear − W),
    front wing x and z, rear wing x and z, nose cone x and z;
  - **wings: NACA 0015, fixed section, no incidence (aoa 0)**; single element assumed (no flap)
    until the owner says otherwise;
  - nose cone, wing supports and the other printed parts: **ABS, FDM, 0.2 mm nozzle**
    (Part 4 density 1.04 g/cm³; `BUILD_WALL_MM` is a placeholder until the team gives the
    printer's minimum wall);
  - objective: race time (Part 2 model) with exact mass, COM and ballast.
- **Method for the whole car (route F):** the bilevel plan of APPROACH.md §3 and PARTS_PLAN.md,
  updated with tonight's evidence.
  - **Builder:** Part 5 `run_car.py` already builds a whole car from (`W`, `x_front`, `d_halo`) with
    Part 1's body field, Part 4 parts (wings, nose, supports, ballast under the halo, ABS masses)
    and the referee (`legality.py`); `part_ranges.py` gives each setting's legal range. Its body is
    Part 1's parametric body, **not** the trial-car STEP that `sidepod_opt` works on. Joining them
    is the first engineering task.
  - **Outer loop:** TuRBO / Bayesian optimisation over the ~10 layout scalars. Each sample is a
    fresh-meshed whole car, legality-checked, scored by **production** coarse CFD and race time
    (~6 min on 2 cores). The steady model is not used here: it misjudges small changes, which is
    what layout moves are. ~100–150 samples.
  - **Inner loop:** at the incumbent layout, refine the body and sidepods with `shape_loop.py`
    (steady-model adjoint, production check every 3 steps); grow the ABS supports by structural
    topology optimisation (PARTS_PLAN.md).
  - **Alternate** outer and inner 2–3 times, then medium mesh, then a physical test.
  - **Concepts:** route E's production-scored exploration supplies the inner loop's starting body.
  - **Optional hint:** layout slopes from the adjoint (sum dD/dXs over a part's points for a rigid
    move). This needs the wings, nose and wheels as DAFoam design surfaces, and it comes from the
    steady model, so it is a hint for the outer search, not its engine.
  - **Before the outer loop:**
    1. fresh-mesh repeatability (one car, 4–5 fresh meshes → σ: the smallest layout effect BO can see);
    2. a wing Reynolds-number check (~20,000 on chord: steady k-ω SST is unreliable for the wings;
       a transient or transition-model run on one wing position).
- **2026-11-21 06:00, COM: a correction, and how the optimiser handles it.** Earlier I said COM doesn't
  matter for this car. That was true only at the current design point. A sweep of Part 2's race
  model at fixed mass and drag (dT in ms; COM x from the nose, z above the track):

  | x \ z | 10 | 16 | 22 | 30 | 40 |
  |---|---|---|---|---|---|
  | 60 | +22.0 | +14.9 | +7.9 | 0 | 0 |
  | 120 | +15.5 | +8.7 | +2.0 | 0 | +4.2 |
  | 165 (car) | +11.0 | +4.4 | **0** (22.4) | 0 | +8.2 |
  | 200 | +7.9 | +1.8 | +0.2 | +1.1 | +11.9 |
  | 245 | +5.5 | +1.6 | +1.8 | +6.9 | +18.1 |

  - The model has a flat zone where COM costs nothing and steep cliffs outside it, worth 4–22 ms
    (up to ~120 mN of drag). The cliffs are `pitch_balance.axle_loads`: when the thrust line's
    moment lifts a wheel pair, its tether guide rubs on the line (`mu_guide` 0.25, a placeholder).
    Their height and position need a guide-friction / track test before they're trusted.
  - The team car sits on the zone's edge (z 22.4: dropping COM to 16 costs 4.4 ms). Every value is
    ≥ 0: moving COM only avoids penalties, it never buys time, and extra lead costs 7.5 ms per gram.
    The zone moves with the layout (axles, wheelbase, thrust line, the halo that carries the ballast
    container).
  - **How the optimiser "figures it out":** gradients can't (zero inside the zone, kinked at the
    edge). The race time evaluation can, and it already decides every step. For route F's outer
    loop: model **D20 and L20** with the surrogate, then compute race time **exactly** with the JAX
    race model (exact mass, COM, ballast, layout geometry), so the kinked cliff is never learned,
    only evaluated. Ballast mass above the floor and `d_halo` become explicit outer variables.
- **2026-11-21 06:00, thin walls, ribs, windows (owner: designs like an open-lattice pod, not blobs).**
  - What blocks them in the current loop: σ 4.5 mm smoothing erases 3 mm ribs; the coarse mesh
    (~3,500 surface points on the car patch) can't resolve them; the level set never opens holes;
    and the steady model's fine polish wasn't confirmed by production. **The adjoint loop is the
    wrong engine for this geometry.**
  - What it needs:
    - a representation that makes walls, ribs and windows natively: a parametric frame family
      (skin, window pattern, rib ≥ 3 mm foam or ≥ printer minimum in ABS, windows ≥ 6.35 mm and
      reachable from a mill set-up) or the CPPN in `design.py`;
    - a mesh refined in the region (~1 mm or finer, 3–8× the cost);
    - global search scored by production CFD and exact race time;
    - a structural check on the ribs (hang test, handling).
  - Coupling: windows remove foam, lead tops the mass up at the container (z 21), which pulls COM
    down towards the cliff. Race time catches this automatically.
  - **Probe A (rules fixed before the result):** the team pod with 3 or 5 vertical through-windows,
    3 mm ribs and a 3 mm skin (`runs/concepts/win3`, `win5`; pod 49.7 / 49.4 cm³ vs 67.5; ~3 cm³ of
    window corner refilled by the mill; 3.1 g of lead added). Production, fresh mesh, coarse.
    Windows help only if race time beats the team pod's by more than 3σ of fresh-mesh scatter
    (probe B), with drag and lead both counted.
  - **Probe B:** fresh-mesh repeatability, the team pod on 3 more fresh meshes (with the existing
    180.85 mN: 4 samples), giving σ.
  - **Open with the owner:** are the image's pods milled foam or printed? What rib thickness does
    the team's process achieve (foam 3 mm; printer minimum still a placeholder)? RULES_MAP lists
    no rule on through-openings in the body.
- **2026-11-21 06:10, owner's answers and direction.** Pods are milled foam with **3 mm walls**; **no
  through-hole rule**. The owner doesn't want invention limited by hand-made starting designs: the
  system must invent its own geometry. The windowed pods (`runs/concepts/win*`) are **not seeds**:
  they are an instrument check (can the CFD resolve 3 mm ribs and 8 mm windows, and do they change
  race time beyond mesh scatter?). If not, the pod region's mesh is refined before any inventing
  method runs. **Invention plan:**
  1. a generative global search (CPPN in `design.py` or a rib/window frame family) through the
     milling rules, scored by production CFD and exact race time, many designs in parallel;
  2. a topology-capable adjoint loop for refinement: nucleation from a topological-sensitivity map
     (where adding solid in air cuts drag), holes opening when thin walls' faces meet, less
     smoothing and a finer pod mesh so rib-scale detail survives.
- **2026-11-21 06:30, concept and window results, and an honest assessment of the inventing routes.**
  - **Concepts** (production, fresh meshes, half car): no pod 206.2; blend 50 % 212.3; 75 % 201.1;
    90 % 185.5; team pod 180.9; **team pod + 8 mm outboard groove 175.4 (−5.5, −3 %)**; adjoint
    design 8 170.5–172.7; whole block 251.8. The path from no pod to a pod rises before it falls
    (a valley no local method crosses), and a single topological feature (the groove) gains 2/3 of
    what the whole adjoint run did.
  - **3-window pod: 182.8 ± 0.8 (+2.0 vs the team pod).** Lead replaces the removed foam at the same
    48.2 g, so race time moves only through drag and COM: about +0.7 ms. Significance waits on the
    fresh-mesh repeats.
  - **Assessment (owner's question):**
    - *Generative global search is not industry practice:* industry uses parametric/morph +
      sampling + surrogate + adjoint polish on engineer-chosen concepts. Its parts are proven
      separately: metamodel-assisted EAs with CFD (Giannakoglou), quality diversity with CFD
      (Gaier et al.), CPPN generative encodings for 3D objects (no CFD-drag use found).
    - *Estimates:* beats the team pod in production ~60–70 %; beats the adjoint result ~35–50 %;
      invents winning rib/window geometry ~25–35 %. Earlier estimates for the adjoint were 40–50 %
      to beat the team pod (it did, −5 %) and 15–25 % to invent (it didn't).
    - *Copy from the literature:* surrogate pre-screening, a QD archive with descriptors (pod volume,
      open area, COM z), a surrogate on D20/L20 with race time computed exactly, coarse search and
      medium confirmation.
    - *Topology-changing adjoint:* ~10–20 %. Published only for 2D, laminar or low-Re flows. Tonight's
      evidence (fine changes don't transfer to production; a young pod transferred ~30 %) is
      against it. Use topological sensitivities as hints inside the global search, not as the
      inventor.
- **2026-11-21 06:45, is free-form generative search worth building? (owner's question; compute assumed plentiful).**
  - Nobody publishes it because industry has no freedom to invent (styling, packaging, crash), a
    full-car CFD run costs hours, and where shapes are free and physics is cheap (structures,
    cooling channels) generative design is already mainstream. This car is the unusual case: a
    nearly free shape, one objective, minutes per run.
  - A widespread recipe gets most of it: a feature vocabulary (grooves, windows, ribs, tapers,
    undercuts; millable by construction) + sampled search with a surrogate + adjoint polish.
    Tonight: one hand-placed groove −3 %, adjoint polish −5 %.
  - **Decision proposed to the owner:** run that recipe as the **baseline** and the free-form
    generator as a **head-to-head experiment** at equal budget and scoring. The comparison answers
    whether the generator earns its place (and is the result a paper needs).
  - Not just a physics problem. Five problems: flow-model trust, search, software robustness,
    manufacturing and strength of 3 mm ribs, the race model's placeholder friction. Compute fixes
    search and part of trust. With compute plentiful the bottleneck is trust: no car has been
    built. Highest-value spend: mill 3–4 deliberately different pods (team, adjoint-polished,
    grooved, windowed) and time them against the CFD ranking; alongside, a mesh-refinement study
    and time-accurate runs on the same four.
- **2026-11-21 07:00, route G: a construction kit and a map-keeping search, not seed shapes (owner: seeds
  cap creativity; the system must decide what exists and what connects).**
  - **Given** (mostly by the regulations): fixed points (axles, wheels, chamber, halo, cargo, NACA 0015
    wing sections, guides), legal volumes for foam and ABS, building blocks, a referee.
  - **Building blocks:** *bodies* (a centre line with a width/height profile along it: pods, nose,
    loft) and *members* (struts or ribs between two points with a thickness).
  - **Decided by the search:** how many bodies and members exist (zero allowed), where each starts
    and ends and which parts it joins, their profiles, the layout numbers, ballast and COM.
  - **Search:** quality diversity (MAP-Elites / SAIL, `methods.py`) with conditional variables (a
    part's settings exist only if the part does; SMT 2.0 / decreed variables in aircraft design).
    Map axes such as rear-pod volume, nose width, member count: the best car in every cell, so
    "with and without rear pods" are both optimised and compared, and no path has to cross the
    measured valley between "no pod" and "pod".
  - **Inner loop:** supports grown by a seconds-long structural solve per candidate (PARTS_PLAN).
  - **Scoring:** legality → production CFD → exact race time. **Polish:** the adjoint loop on the
    map's best few. **Seeds** (e.g. the owner's 50 sidepods): optional head start in the first
    population, never a boundary.
  - **Halo loft:** its profile numbers go in the global search; "smallest loft then adjoint" is local.
  - **Risks:** thin members are where the flow model and the coarse mesh are weakest (windows got
    worse with count on this mesh); a large build (kit, structural check, whole-car builder,
    robust meshing); most random kit designs are poor (surrogate screening).
  - **Staging:** (1) prototype with two decisions, sidepod shape and rear pods or none;
    (2) nose with auto-grown wing supports; (3) loft, layout, ballast; (4) adjoint polish and a
    finer mesh.
  - **Paper framing:** "best possible" isn't provable; defensible: the best found by a documented
    search at a stated budget, the map explaining each choice, ablations, finer-mesh and track
    confirmation.
- **2026-11-21 06:30, fresh-mesh scatter of the production coarse model: σ = 0.32 mN half car.**
  - The team pod unshifted and shifted by −0.05 / +0.05 / +0.10 mm (physical effect < 0.01 mN by
    the adjoint; each shift gets its own snappy mesh): 180.85, 180.31, 180.33, 180.10 mN. Mean 180.40.
  - Identical STLs give identical meshes: a plain repeat returned 180.85 to the digit, so plain
    repeats measure nothing.
  - Differences ≥ ~1.4 mN between two fresh-mesh designs are real at 3σ (σ√2 × 3). Significant
    against the team pod: groove −5.5 mN, 3 windows +2.0, 5 windows +6.1, the adjoint design
    −10.4, 90 % blend +4.6.
  - **Window verdict (probe A's rule):** windows don't help on this mesh and model; drag rises with
    their number. To re-check on a finer mesh before treating as final: 3 mm ribs are at the
    coarse mesh's resolution limit.
  - A production-scored global search can resolve ~1.5 mN (≈ 0.3 ms) per design, with no repeats needed.
- **2026-11-21 07:16, run `cloud_lean` (no-pod seed) STOPPED by the production stop rule.**

  | design | steady D20 whole car | pod | production half car (fresh) |
  |---|---|---|---|
  | 0 (no pod) | 493.38 mN | 5.0 cm³ | 206.19 |
  | 4 | 479.52 | 10.8 | 203.91 |
  | 7 | 473.66 | 12.5 | 204.30 |
  | 9 | 469.25 | 14.9 | 204.01 |
  | 10 | 467.40 (accepted on a reused gradient; it 9's adjoint stalled at 1.9e-3) | | not checked |

  - Steady model: −26.0 mN whole car (−5.3 %) over 10 iterations. Production: −2.2 mN half car
    by design 4, then flat within the 0.32 mN scatter (203.9, 204.3, 204.0). Two checks without a
    gain > 1 mN: stopped. The team's pod sits 25 mN below no pod in production; this run recovered 9 %.
  - **Conclusions from both runs:**
    - the adjoint loop refines a good pod (−5 % in production from the team's);
    - it can't create one (a valley lies between no pod and a pod: 50 % blend +6.1 mN);
    - the steady model's gains on small features don't transfer;
    - `runs/cloud_lean/` holds the state if anyone wants to resume it (remove `STOP`).
- **This machine is now idle**, apart from what is started next.

## Sources

- Feppon, Allaire, Dapogny, Jolivet: [body-fitted topology optimisation of 2D and 3D heat exchangers](https://www-ljk.imag.fr/membres/Charles.Dapogny/publis/heatexchangers.pdf); [thermal fluid-structure systems, body-fitted meshes](https://researchportal.ip-paris.fr/en/publications/topology-optimization-of-thermal-fluidstructure-systems-using-bod/)
- [Level-set topology optimisation for 2D turbulent flow with an immersed boundary (JCP 2021)](https://www.sciencedirect.com/science/article/abs/pii/S0021999121005258)
- [Immersed boundary with RANS turbulence models (preprint)](https://arxiv.org/pdf/2606.06135)
- [Papoutsis-Kiachagias et al.: continuous adjoint for turbulent shape and topology optimisation](https://www.researchgate.net/publication/273705112_Continuous_Adjoint_Methods_for_Turbulent_Flows_Applied_to_Shape_and_Topology_Optimization_Industrial_Applications)
- [Koch, Papoutsis-Kiachagias, Giannakoglou: transition from topology to shape optimisation (2017)](https://zenodo.org/records/582625/files/Koch%20Journal%20of%20Computers%20and%20Fluids%20May%202017.pdf)
- [OpenFOAM v2312 release notes: topology optimisation](https://www.openfoam.com/node/560)
- [Othmer: adjoint methods for car aerodynamics](https://mathematicsinindustry.springeropen.com/articles/10.1186/2190-5983-4-6)
- [Chalmers: adjoint optimisation of ground vehicles (DrivAer, unstable in separated flow)](https://odr.chalmers.se/items/e625457f-41b4-481d-baaf-8f31e7097bbe)
- [Siemens: adjoint shape optimisation for car aerodynamics](https://blogs.sw.siemens.com/simcenter/adjoint-shape-optimization-for-improved-car-aerodynamics/)
- [Siemens: topology optimisation in STAR-CCM+](https://blogs.sw.siemens.com/simcenter/topology-optimization-cfd-creating-designs-like-nature/)
- [Bons, He, Mader, Martins: multimodality in aerodynamic wing design optimization (2019)](https://mdolab.engin.umich.edu/bibliography/Bons2019a); [Bristol: global optimization of multimodal aerodynamic benchmarks](https://research-information.bris.ac.uk/en/publications/global-optimization-of-multimodal-aerodynamic-optimization-benchm/)
- [Kontoleontos, Asouti, Giannakoglou: asynchronous metamodel-assisted memetic algorithm for CFD-based shape optimization (2012)](https://www.bohrium.com/paper-details/an-asynchronous-metamodel-assisted-memetic-algorithm-for-cfd-based-shape-optimization/811650189788971008-4135)
- [Bouhlel & Martins: gradient-enhanced kriging for high-dimensional problems](https://arxiv.org/pdf/1708.02663.pdf); [Wang et al.: adjoint + gradient-enhanced kriging (ICAS 2018)](https://www.icas.org/icas_archive/ICAS2018/data/papers/ICAS2018_0715_paper.pdf); [Müller et al.: Bayesian optimisation with adjoint gradients (Stanford CTR 2024)](https://web.stanford.edu/group/ctr/ctrsp24/ii05_MULLER.pdf)
- [Gaier, Asteroth, Mouret: surrogate-assisted illumination (SAIL)](https://arxiv.org/html/1702.03713); [aerodynamic design exploration through SAIL](https://www.researchgate.net/publication/318142887_Aerodynamic_Design_Exploration_through_Surrogate-Assisted_Illumination)
- [Amstutz: the topological asymptotic for the Navier-Stokes equations (2005)](https://www.esaim-cocv.org/articles/cocv/pdf/2005/03/cocv0404.pdf); [Sá, Novotny et al.: topological derivatives for fluid flow channel design](https://novotny.lncc.br/download/papers/50); [hole seeding in level-set topology optimization](https://arxiv.org/pdf/1909.10703)
- [SMT 2.0: hierarchical and mixed-variable Gaussian processes](https://ar5iv.labs.arxiv.org/html/2305.13998); [meta and decreed variables](https://arxiv.org/pdf/2506.22621v3); [mixed-categorical GPs for aircraft design](https://www.arxiv.org/pdf/2402.04711)
- [MAP-Elites with topology optimisation (soft robots)](https://arxiv.org/pdf/2407.07591); [MAP-Elites for diverse structural designs](https://eprints.whiterose.ac.uk/id/eprint/210793/1/EBB_CEC_2024.pdf)
