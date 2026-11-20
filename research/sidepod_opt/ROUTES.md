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
