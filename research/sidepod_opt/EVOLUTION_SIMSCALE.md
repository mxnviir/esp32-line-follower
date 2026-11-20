# Evolving the sidepods on SimScale: the complete guide

This guide takes someone new to the repo from nothing to a verified, faster sidepod. The method is evolution: generate a batch of legal sidepods, time each one in real CFD on SimScale, keep the good ideas, repeat. Every car is judged by a full SimScale RANS solve with real walls.

All paths below are relative to `research/sidepod_opt/` unless they start with `.github/` or `part`.

**Status (2026-11-20):**

| Part | Status |
|---|---|
| Design rules, geometry engine, legality checks, STL export | built and tested here |
| Campaign loop (CMA-ES, SAIL) | tested end to end against a mocked SimScale |
| SimScale API calls | checked against the SDK source and its examples; **never run against real SimScale** (no access from where it was built) |
| Your first job | step 4, the self-test, which proves the SimScale side works |

---

## 1. What is being optimised

**Objective.** For now, aero only: the evolution ranks cars by race time computed from SimScale's drag (D20) and lift (L20) with the exact mass of each milled body. To make it pure drag, see "Switching the objective" in section 8.

**Where material may go.** Only the sidepod region of the trial car (`cad/trial_car.step`): about x 49–159 mm from the tail, out to 32.5 mm each side, above 1.5 mm track clearance. Everything else is the team's CAD and is never changed: nose, body, deck, cockpit, halo, wheels.

**The rules every car obeys.** They're enforced by the geometry engine, `geometry.py`, and set in `config.simscale.json` under `"car"`:

| Rule | Setting | How it's enforced |
|---|---|---|
| No virtual cargo (for now) | `"cargo": false` | nothing is forced in or checked for the cargo |
| Nothing above the team's sidepod top | `"ceiling_mm": 27.175` | Measured from the STEP: the sidepod's top face is at 27.175 mm. The region simply ends there, and the exact CAD cut is at the same height, so not even the smoothed surface crosses it. |
| Halo cap (T4.4.2), forward of x = 115 | `"halo_zmin": 27.175` | Set to the same height, because the team's own STEP reaches 27.175 there. **Confirm the real rule height with the team.** |
| Milled from **top and bottom only**, 3.175 mm ball end | `"mill_dirs": "z"` | Part 1's machining model runs with only those two set-ups. Air the ball can't reach becomes foam. |
| 3 mm minimum wall everywhere | built in | Open/re-mill filter, then a check: at most 30 mm³ of "thin" foam, which tolerates voxel staircase artefacts. Cars that fail never reach SimScale. |
| One piece, no floating blobs | built in | Loose pieces are deleted; the check requires one piece. |
| Sidepod region only | built in | The check requires 0 mm³ changed outside the region. |

**Mass.**
- A car lighter than 48.2 g gets lead up to 48.2 g, which is free in race time.
- A heavier car pays for the extra: about 7.5 ms per gram.
- A car that needs more lead than the container holds is illegal.
- The other parts' mass is still an assumption; see `README.md`.

## 2. Why evolution and real walls (lessons already paid for)

| Approach tried | Result |
|---|---|
| ESI continuous adjoint (shape) | Failed its accuracy test twice, but both runs used the wrong mesh. Unresolved (`gate_results/RESULT.md`). |
| DAFoam discrete adjoint | Needs about 150 kB of RAM per cell, so 64–128 GB for a 520 k-cell car. Doesn't fit a normal machine. |
| Topology optimisation (porous solid, ESI) | Its gradient failed a finite-difference check. Worse, its porous "walls" make thin, curvy shapes look cheap. An evolved design it rated 18 % better than no sidepod was **11 % worse** in real-wall CFD (`topo/`). |
| Evolution scored by real-wall CFD | This guide. Slower per car, but every number is real. |

## 3. Setup (once)

### 3.1 Python environment

Use Python 3.11–3.13:

```bash
pip install numpy scipy scikit-image trimesh numba cma neat-python scikit-learn jax cadquery-ocp \
            manifold3d pymeshlab rtree shapely mapbox-earcut matplotlib
```

The SimScale SDK is not on PyPI:

```bash
git clone --depth 1 https://github.com/SimScaleGmbH/simscale-python-sdk.git
pip install ./simscale-python-sdk
# if the pip build fails (it did on one machine), use the clone directly:
export PYTHONPATH=$PWD/simscale-python-sdk:$PYTHONPATH
```

Quick health check (about 2 minutes):

```bash
python test_simscale.py          # expect: test_simscale: OK (state machine, restart, remap, force read, cost guard)
python simscale_tool.py export /tmp/team_car                # expect: "check": {... "ok": true}, files car_half.stl, wheelF.stl, ...
python simscale_tool.py export /tmp/no_pod --design none    # the car with no sidepod, also legal
```

### 3.2 SimScale access

1. Your plan must include **API access**: account settings → "API keys". If that page doesn't exist, this route can't run; use section 7's GitHub Actions route instead.
2. Create a key, then `export SIMSCALE_API_KEY=...`. Never commit it, and never put it in a file in the repo.
3. Check it with `python simscale_tool.py check`. You should see "SDK ok, API key ok".

### 3.3 The template simulation (in the SimScale web UI, once)

Every car is a copy of this simulation. Settings, copied from the repo's own OpenFOAM setup (Part 2):

1. **Upload the team's car.** Run `python simscale_tool.py export team_car`, zip `car_half.stl`, `wheelF.stl` and `wheelR.stl`, and upload the zip as ONE geometry, units **m**. The STL solids are named `car`, `wheelF`, `wheelR`.
2. **Check the body names SimScale gave them.** Run `python simscale_tool.py upload team_car --project <ID>`, which prints the imported geometry. If the bodies aren't called `car`, `wheelF`, `wheelR`, put SimScale's names in `"bodies"` in `config.simscale.json` (same order).
3. **Create one simulation:**

| Setting | Value |
|---|---|
| Analysis | Incompressible, steady, k-omega SST |
| Fluid | air, ν = 1.48e-5 m²/s (μ 1.813e-5, ρ 1.225) |
| Domain | external box: x −0.771 to 2.314 m, y 0 to 0.192 m, z 0 to 0.245 m (nose at x = 0, flow +x) |
| Inlet (x min) | velocity (20, 0, 0) m/s, turbulence intensity 0.5 %, eddy viscosity ratio 5 |
| Outlet (x max) | pressure 0 |
| y = 0 | **symmetry** (half car) |
| Side, top | slip |
| Ground (z = 0) | **moving wall**, (20, 0, 0) m/s (rolling road) |
| `car` | no-slip wall |
| `wheelF` | rotating wall, axis (0, 1, 0) through (0.055384, 0.027875, 0.01382) m, ω = −1416.43 rad/s |
| `wheelR` | rotating wall, axis (0, 1, 0) through (0.193384, 0.024875, 0.01382) m, ω = −1416.43 rad/s |
| Result control | **"Forces and moments"** (exactly this name) on `car` + `wheelF` + `wheelR` |

4. **Create one mesh operation.** Refine on the car and wheels and in a box under the car; the ride-height gap is 1.5–2 mm. Aim for at least 1.5–3 M cells for the half car if the budget allows (our own coarse runs used 0.1–0.5 M). Every car copies these mesh settings.
5. **Run it once.** Our OpenFOAM gives the team's car D20 ≈ 0.366 N for the whole car (0.183 N half). Agreement within 10–15 % is normal across solvers; only SimScale-to-SimScale differences steer the search.
6. **Find the IDs:** `python simscale_tool.py ids` lists every project, simulation and mesh operation with its ID.

## 4. Self-test: prove the SimScale side works (do this before spending budget)

```bash
python simscale_tool.py selftest --project <P> --template <SIM> --mesh <MESH_OP> --max-cost <X>
```

This runs 5 cars: the team's car **3 times**, plus 2 evolved designs. It writes `simscale_selftest/selftest.json` with:
- **noise:** the spread of the 3 identical cars. Gains smaller than about 3× this are not real.
- **cost and time per car,** which sets your budget (section 6).
- **two evolved designs:** open their simulations in the web UI and check the boundary conditions sit on the right bodies (wheels rotating, car no-slip).

To test a single car by hand:

```bash
python simscale_tool.py export my_car --design none
python simscale_tool.py run my_car --project <P> --template <SIM> --mesh <MESH_OP>
```

## 5. The geometry engine (what happens to each car)

`simscale_tool.py export` and the campaign use the same pipeline (`geometry.py`):

1. **Read** `cad/trial_car.step`: exact B-rep body and wheels.
2. **Take the design:** a field over a 1 mm grid of the sidepod region. Foam goes where it's positive.
3. **Finish:** symmetric left/right; forced air removed; locked CAD kept.
4. **Mill:** top and bottom set-ups, 3.175 mm ball; unreachable air becomes foam.
5. **Clean:** 3 mm minimum-wall filter, loose pieces deleted.
6. **Check:** every rule in section 1.
7. **Build the exact surface:** marching cubes of the pod, cut by the exact region solid, joined to the exact CAD. The result is watertight and welded as an STL reader sees it.
8. **Weigh:** foam mass, lead and centre of mass.
9. **Export** `cars/<id>/`:

| File | Content |
|---|---|
| `car_half.stl` | solid `car`, metres, half car, closed at y = 0 |
| `wheelF.stl`, `wheelR.stl` | +y wheels |
| `body_full.stl` (+ `wheelF_m.stl`, `wheelR_m.stl` from the tool) | for whole-car templates |
| `mass.json` | foam, lead, centre of mass |

10. **SimScale** (`SimScaleEvaluator` in `evaluators.py`): zip the STLs, import, copy the template with every boundary condition moved onto the new bodies by name, mesh with the template's mesh settings, check the setup, estimate cost (skip if above `max_cost`), run, read "Forces and moments". The time-average of the last 30 % gives D20 and L20.

A different car means a different STEP: set `"step"` and the other `CarSpec` fields (axles, region box, halo) in the config's `"car"` block.

## 6. Running the evolution

The config is `config.simscale.json`:

| Stage | What runs |
|---|---|
| `evolve` | `sail`: 80 cars in batches of 8 (explores several *different* good pods). `cma`: 240 cars in generations of 12 (refines the best). Both start from the team's sidepod. The original car is also timed once on SimScale as the reference. |
| `recheck` | The best 4 are re-timed in our own OpenFOAM on GitHub Actions (section 7). |

```bash
python campaign.py init runs/simscale config.simscale.json
# edit runs/simscale/config.json: project_id, template_sim_id, mesh_template_id, max_cost (and "bodies" if needed)
export SIMSCALE_API_KEY=...
python campaign.py tick runs/simscale        # run every 10 minutes from cron; each tick advances everything a step
python campaign.py report runs/simscale      # runs.md, convergence.png, best.png, best/<car folders>
```

Example cron line:

```
*/10 * * * * cd /path/research/sidepod_opt && SIMSCALE_API_KEY=... python campaign.py tick runs/simscale >> runs/simscale/tick.log 2>&1
```

**State lives on disk,** so a tick can die or be restarted at any point:

| File | Holds |
|---|---|
| `simscale_inflight.json` | cars in SimScale, each at import / mesh / run |
| `state.json` | stages and budgets |
| `designs.jsonl` | every car built, legal or not, with its result |
| `runs/*.pkl` | each method's memory |

**To stop:** set `"stopped": true` in `state.json`. **To change the budget:** edit `"budget"` per method before that method finishes.

**Budget worksheet** (fill in from the self-test):

| Item | Value |
|---|---|
| Cost per car (estimate / actual) | |
| Time per car (import + mesh + run) | |
| Cars SimScale runs in parallel on your plan | |
| Noise (spread of 3 originals) | |
| Total cost | 320 cars + references × cost per car |
| Wall time | 320 ÷ cars in parallel × time per car |

## 7. Verification outside SimScale (GitHub Actions, free for public repos)

The `recheck` stage re-times the best 4 cars in this repo's own OpenFOAM pipeline (`.github/workflows/sidepod_eval.yml`), so the win doesn't depend on one solver.

1. **A compute repo:** a GitHub repo containing this code, with the workflow on the branch named by `"ref"` in the evaluator config (set it, e.g. to the branch this guide is on). Public repos get free Actions minutes and 20 parallel jobs.
2. **The GitHub CLI** logged in with `repo` and `workflow` scopes: `gh auth login`.
3. **A release** for the batches: `gh release create sidepod-jobs -R OWNER/REPO --notes "batches"`.
4. **The config:** in `config.simscale.json`, set `"repos": ["OWNER/REPO"]` and `"ref"`.

Each batch goes up as a release asset; results come back as workflow artifacts. `campaign.py tick` handles both.

**A winner must:**
1. beat the team's car by more than 3× noise in SimScale;
2. keep that gain in OpenFOAM on GitHub Actions;
3. then be checked at 5–10 M cells and on the track.

## 8. Options and switches

| Want | Do |
|---|---|
| Pure drag instead of race time | In `campaign.py`, `_collect` computes `T` from `self.rm(...)`; replace it with `r["D20_N"]` (one line), and keep the race time in the log for reference. |
| Bring the cargo back | `"cargo": true` (forced foam inside, checked) |
| Allow side milling too | `"mill_dirs": "zy"` |
| Whole-car template | `"half": false` (needs `body_full.stl` and the mirrored wheels) |
| Start from no sidepod | `"starts": ["lean"]` |

## 9. Troubleshooting

| Symptom | Likely cause |
|---|---|
| `simscale_sdk` import error | section 3.1 (pip build failure: use `PYTHONPATH`) |
| "solids missing after import" | SimScale named the bodies differently: run `simscale_tool.py upload`, then set `"bodies"` |
| "too expensive" in `designs.jsonl` | the estimate exceeded `max_cost` |
| a car `FAILED` at mesh | a very thin gap; try the mesh operation's gap refinement. The car is told to the method as failed and the run continues. |
| No progress | cron isn't running, or the API key isn't in the cron environment (`tick.log`) |
| Everything illegal | read `check` in `designs.jsonl`: thin foam or pieces usually means the design's step size is too large (lower CMA `"sigma"`) |

## 10. What is tested, and what is not

| Part | Status |
|---|---|
| Rules (cargo off, 27.175 mm ceiling, top/bottom milling, 3 mm walls, one piece), exact watertight export | tested: 18 evolved cars all watertight, nothing above 27.175 mm in the sidepod area; the team's car and the no-pod car pass |
| Campaign loop with SimScale | tested against a mocked SDK (`test_simscale.py` plus a 4-tick campaign): 17 of 21 evolved cars legal |
| SimScale calls | names and signatures checked against the SDK source; **not yet run for real** (section 4 does it) |
| Actions re-check | dry-run tested; a real dispatch has not run yet |
| Whole car (nose, rear pods) and the 3 layout variables | **not built**; only the sidepod region is designable |
