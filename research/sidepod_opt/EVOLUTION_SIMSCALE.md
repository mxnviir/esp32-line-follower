# Evolution on SimScale: the full plan

This is how the car's shape is evolved with real RANS CFD on SimScale, from setup to a verified winner.

**Related files:**
- `SIMSCALE.md`: the one-time SimScale template.
- `README.md`: the geometry pipeline.
- `config.simscale.json`: the campaign config.

**Status (2026-11-20):**
- **Ready and tested against a mocked SimScale:** the code for the sidepod region, the SimScale evaluator and the campaign loop.
- **Waiting on:** your SimScale API key and the template simulation.
- **Not built yet:** the whole-car regions (nose, loft, rear pods) and the three layout variables. See [Phase 5](#phase-5-whole-car-and-layout-needs-development).

## Why evolution, and why SimScale

Each method was checked against three needs: organic shapes, accurate decisions, and no runs wasted on variables that don't matter.
- **Adjoints:**
  - The ESI adjoint failed the gate (`gate_results/RESULT.md`).
  - DAFoam's discrete adjoint needs more than 150 kB of RAM per cell. That is over 40 GB for the 520 k-cell mesh, and 0.75–1.5 TB at 5–10 M cells.
  - Its accuracy test is still running on the coarse mesh (`dafoam/coarse_test.sh`).
- **Evolution:** every candidate is a real CFD run, so no gradient has to be trusted, and it can reach shapes far from the starting car. Its cost is the number of runs, and SimScale runs many cars in parallel in the cloud.
- **STAR-CCM+ topology optimisation:** not available, so not used.

## How one design becomes a race time

The steps below happen per car; nothing here is new code.

1. **Field:** the method proposes a field over the design region; foam goes where the field is positive. It is always a whole shape, so the method can add or remove material anywhere in the region.
2. **Finish:**
   - The field is made symmetric.
   - Forced air is cut out: the T7.9.2 and T7.9.3 wheel wedges, and the halo zone (T4.4.2).
   - The cargo is forced in.
   - The spine, deck, cockpit and halo pocket are locked to the STEP. **The halo/cockpit interface is never changed.**
3. **Mill:** the team's 3-axis process with a 6.35 mm ball end. Air the cutter can't reach stays foam, sealed voids are filled, and loose pieces are dropped.
4. **Minimum wall:** the region foam is opened by the 3 mm wall ball, then milled again. This is a minimum-feature filter. Before it was added, no evolved design passed the checks.
5. **Checks:**
   - one piece;
   - nothing changed outside the region;
   - no foam in forced air;
   - cargo inside;
   - at least 1.5 mm track clearance (T3.7);
   - thin foam ≤ 30 mm³.
   A car that fails is never sent to SimScale and costs nothing. The method is told it scored the generation's worst + 0.05 s.
6. **Weigh:** exact foam mass and centre of mass. A light car gets lead up to 48.2 g. A heavy car pays for its weight; there is no upper limit.
7. **Export:** an exact watertight body, made with Booleans against the CAD, plus the wheels, in Part 2's folder format.
8. **SimScale:**
   - Upload, import, mesh with the template's mesh settings, run.
   - Every car is cost-checked against `max_cost` before its run starts.
   - The force plot is read and gives D20 and L20.
9. **Race time:** Part 2's race model with this car's mass, axles and thrust line. The race time is the only objective.
   - Drag is worth about 0.18 ms per mN.
   - Mass is worth about 7.5 ms per gram above 48.2 g.

## Shape representations

| Representation | Variables | Used by | Notes |
|---|---|---|---|
| Lattice | 10 × 4 × 5 control values (±12 mm, smooth interpolation) + 1 blend value (start = team's sidepod, none, or between) = 201 | CMA-ES, SAIL | Smooth, organic pods; the default |
| CPPN | a small network of x, \|y\|, z, distance to the cargo, the original and lean shapes | NEAT | Most open-ended, but needs thousands of cars: **not on SimScale** |
| Level set, 2 mm | about 18 k values | SPSA, a future adjoint | Fine detail; for polishing, not for evolution |

## The methods and their roles

| Method | Role | Cars | How it runs |
|---|---|---|---|
| **SAIL** (MAP-Elites on a Gaussian-process surrogate) | **Explore.** Fills an 8 × 6 grid of *different* good pods (foam volume × pod height), using CFD only on the most promising candidates | 80, batches of 8 | Gives several distinct good designs, not one |
| **CMA-ES** | **Exploit.** Evolves a population of 12 per generation towards the fastest car | 240 = 20 generations | Adapts its own step size and direction; told the whole generation at once |
| NEAT | not used here | thousands | Only on free parallel compute (GitHub Actions) |

**Expectations:**
- **CMA-ES won't fully converge in 240 cars.** With about 200 variables, full convergence takes thousands of evaluations. Expect clear gains in 240 cars. More budget, or a restart around the best car, buys more.
- **SAIL's surrogate gets weaker as the number of variables grows.** Its value here is variety: several good, different starting points.

## Noise: what counts as a real improvement

Every SimScale car gets a fresh mesh, so remeshing noise is part of every number. In our OpenFOAM pipeline, a fresh mesh against a morphed one shifted drag by 0.37 mN. SimScale's own noise is unknown until it is measured.

- **Phase 0 measures it:** the original car is run 3 times.
- **Improvements below 3× that noise are not counted** as wins.
- **SimScale numbers are only compared with SimScale numbers.** The campaign times the original car once per stage as the SimScale reference. Absolute agreement with OpenFOAM within 10–15 % is normal across solvers; the ranking is what matters, and Phase 4 checks it.

## Phases

### Phase 0: setup and calibration (about 1 day, mostly yours)

1. Find the API key (account settings, "API keys"). Claude asks for it through a secure form; it is never pasted in chat.
2. Build the template simulation and mesh operation exactly as in `SIMSCALE.md`: half car, k-omega SST, rolling road, rotating wheels, a "Forces and moments" result control.
3. Check the original's drag against our 0.183 N (half car).
4. **Calibration:** the original 3 times, plus 2 evolved cars (`"budget": 1` per method). This gives:
   - the noise (spread of the 3 originals);
   - the cost per car (SimScale's estimate and the actual charge);
   - the time per car;
   - proof that the boundary conditions land on the right solids for an evolved shape.
5. **Set the budget** from those numbers:
   - total cost ≈ cars × cost per car;
   - wall time ≈ cars ÷ cars run in parallel (your plan's limit) × time per car.

### Phase 1: SAIL exploration (80 cars)

- A diverse grid of good sidepods, all real CFD.
- The output is the elite map: the best car in each cell of the grid.
- At the end, review the elite renders together (`campaign.py report`) before spending on Phase 2.

### Phase 2: CMA-ES exploitation (240 cars)

- Starts from the team's sidepod (`original`). The `blend` value lets it walk all the way to "no sidepod".
- **Optional second run:** start a CMA run from SAIL's best car. This needs a small code change, because CMA starts are currently `original`, `lean` or `blend` only.

### Phase 3: a second look (optional, budget permitting)

- A CMA restart with a smaller step size around the best car.
- Or more SAIL cars if the elite map still has empty, promising cells.

### Phase 4: verification outside SimScale (free on GitHub Actions)

1. **The best 4 cars are re-run in our own OpenFOAM pipeline at the medium mesh.** This is the config's `recheck` stage, which runs on GitHub Actions. It confirms SimScale's ranking with a second solver.
2. **The best 1–2 are run at the fine mesh and at 5–10 M cells**, plus a transient (URANS) wake check with Part 2's `transient.py`.
3. **A winner must:**
   - beat the original by more than 3× noise in SimScale;
   - keep that sign and roughly that size in OpenFOAM at medium and fine;
   - be legal and millable (already guaranteed by the pipeline).
4. **Print it and run it on the track.**

### Phase 5: whole car and layout (needs development)

The pipeline today designs the **sidepod region only**. These parts are not built yet:

1. **Layout variables:**
   - halo distance from the back, back to rear wheel, and wheelbase;
   - geometry code to move the axles, the wheel wedges and the halo/cockpit block, stretch the body, and re-check the rules;
   - then BO on those 3 variables, about 25 cars (fresh meshes, so noise matters).
2. **More design regions:**
   - nose, loft/top surfaces, and rear pods;
   - each region needs its box, the rule zones that stay air, the locked zones that stay the team's CAD (the halo/cockpit interface always stays locked), and the descriptors SAIL uses;
   - wings and supports, if the rules allow them as part of the body.
3. **Order:**
   - Fix the layout first, using BO with the team's body.
   - Then evolve all regions together on that layout. More regions means more variables, so CMA needs more cars: plan on 2–3× the sidepod-only budget.

## Running it

```bash
cd research/sidepod_opt
python campaign.py init runs/simscale config.simscale.json
# fill project_id, template_sim_id, mesh_template_id, max_cost in runs/simscale/config.json
# (with the key in place, Claude finds the IDs through the API)
SIMSCALE_API_KEY=... python campaign.py tick runs/simscale      # cron this, e.g. every 10 min
python campaign.py report runs/simscale                         # runs.md, convergence.png, best.png, best car folders
```

**Each tick does four things:**
1. builds new cars;
2. submits them;
3. advances every in-flight car one step (import → mesh → run);
4. tells the methods the finished results.

**State is on disk, so a tick can stop anywhere:**
- `simscale_inflight.json`: cars in flight;
- `state.json`: stages and budgets;
- `designs.jsonl`: every car built;
- `runs/*.pkl`: each method's state.

To stop, set `"stopped": true` in `state.json`. To resume, keep ticking.

## Cost and time worksheet (fill in after Phase 0)

| Item | Value |
|---|---|
| SimScale cost per car (estimate / actual) | … |
| Time per car (import + mesh + run) | … |
| Cars in parallel (plan limit) | … |
| Noise (spread of 3 originals), mN | … |
| Phase 1 + 2 cars | 320 + the reference car per stage |
| Total cost | 320 × cost per car |
| Wall time | 320 ÷ cars in parallel × time per car |

## What is tested, and what is not

| Part | Status |
|---|---|
| Geometry, finishing, milling, minimum wall, checks, mass, exact watertight export | tested on the trial car; about 2/3 of evolved cars come out legal |
| Campaign loop (ask, build, submit, collect, tell) with CMA-ES and SAIL | tested end to end against a mocked SimScale (`test_simscale.py` and a 6-tick campaign) |
| SimScale API calls | names and signatures checked against the SDK source; **never run against SimScale** |
| The template's boundary conditions on evolved shapes | checked by the face remapping in the mock; **must be checked by eye in Phase 0** |
| OpenFOAM re-check on GitHub Actions | dry-run tested; a real dispatch has not run yet |
| Whole-car regions and layout variables | **not built** |

## Risks

- **No API access on your SimScale plan.** Then this route can't run, and the same campaign runs on GitHub Actions with our own OpenFOAM (free, about 20 cars in parallel, 40 min each at medium).
- **Noise comparable to the gains.** Phase 0 measures it. If it is too large, repeat the best cars or use a finer mesh template.
- **SimScale and OpenFOAM disagree on the ranking.** Phase 4 catches this before anything is built.
- **Cost overrun.** `max_cost` per car, the budgets per method, and `"stopped": true` all cap it.
- **A surrogate-picked car being misjudged.** SAIL's GP only proposes cars; every reported number is real CFD.
