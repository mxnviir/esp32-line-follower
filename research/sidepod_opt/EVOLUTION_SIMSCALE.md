# Evolving the sidepods on SimScale: the complete guide

This guide takes someone new to the repo from nothing to a verified, faster sidepod. The method is evolution: generate a batch of legal sidepods, time each one in real CFD on SimScale, keep the good ideas, repeat. Every car is judged by a full SimScale RANS solve with real walls.

All paths below are relative to `research/sidepod_opt/` unless they start with `.github/` or `part`.

**Status (2026-11-21):** the evolution runs on SimScale with a fixed-size mesh (section 3.3, mesh study below). Keys are used in order, each until SimScale reports it out of core-hours (`runs_per_key: null`); a 10-run limit per key is still available for free accounts.

---|---|
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
            manifold3d pymeshlab fast-simplification rtree shapely mapbox-earcut matplotlib
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

### 3.2 SimScale access (API keys)

1. Your plan must include **API access**: account settings → "API keys".
2. The evaluator takes several keys and uses them **in the order given**. With `"runs_per_key": null` (current config) a key is used until SimScale refuses for lack of core-hours, then it is retired and its unfinished cars move to the next key. For free accounts with a known run limit, set `"runs_per_key": 10`:
   ```bash
   export SIMSCALE_API_KEYS='key1,key2,key3'      # comma, space or newline separated; SIMSCALE_API_KEY also works for one
   ```
   Never commit a key or write it into a file in the repo. The state file stores only a 10-character fingerprint of each key (sha256), its project and its run count.
   **In a Claude Code cloud environment:** open the environment's settings (cloud environment menu in the session's title bar → Edit) and add ONE environment variable, in `.env` format, one line:
   ```
   SIMSCALE_API_KEYS=simscale_ak_firstkey,simscale_ak_secondkey,simscale_ak_thirdkey
   ```
   No quotes, no spaces, commas between keys. Keep keys that are already used up in the list (the campaign recognises them by fingerprint, knows they are spent, and can still fetch their last results). Do **not** use "Network secrets" for SimScale: those inject one key per host into every request, which would override the per-key rotation.
3. Check a key with `SIMSCALE_API_KEY=... python simscale_tool.py check`. You should see "SDK ok, API key ok".
4. Behind an HTTPS proxy (e.g. a cloud container), `HTTPS_PROXY` and `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` are passed to the SDK automatically (urllib3 ignores them otherwise). The host `api.simscale.com` must be allowed.

**There is no web-UI setup.** Every account gets a project called "sidepod evolution", created through the API on first use, and every car gets its own simulation and mesh operation, built from code (`simscale_template.create_case`).

### 3.3 What every car's simulation is (set in `simscale_template.py`)

| Setting | Value |
|---|---|
| Geometry | ONE solid: the air volume (half wind tunnel minus the car), STEP, mm, faces named (section 5) |
| Analysis | Incompressible, steady, k-omega SST, 1000 iterations |
| Fluid | SimScale's default Air |
| Domain | x −771 to 2314 mm, y 0 to 192 mm, z from the road to 245 mm (nose at x = 0, flow +x) |
| Inlet | velocity (20, 0, 0) m/s |
| Outlet | pressure 0 |
| y = 0 | symmetry (half car) |
| Side, top | slip walls |
| Road | moving wall (20, 0, 0) m/s, **0.15 mm below the wheels' lowest point** (no contact: the team's choice) |
| Car | no-slip wall |
| Wheels | rotating walls about +y through their centres, ω = −1416.43 rad/s (rim speed 20 m/s, rolling with the road) |
| Result | "Forces and moments" on car + wheels; D20 and L20 = mean of the last 15 % of iterations × 2 (half car) |
| Mesh | SimScale standard (Simmetrix) mesher, **manual sizing: 30 mm largest, 0.8 mm smallest cell** (`"sizing"` in the config; omit it for automatic fineness 6), automatic layers, physics-based meshing, 1.5 mm cells in a box around the car: 3.5–4.0 M cells for every design |

**Mesh study (2026-11-21).** Automatic sizing let the faceted, lumpy evolved pods drive the cell count up (team car 2.9 M, evolved 6.1–8.2 M) and failed often. A 0.8 mm floor on the cell size fixes both:

| Cells | auto 6 | min 0.5 mm | min 0.8 mm | min 1.2 mm |
|---|---|---|---|---|
| team car | 2.90 M | 3.63 M | 3.48 M | – |
| c00004 | 6.12 M | 4.82 M | 3.84 M | 3.41 M |
| c00008 | 8.20 M | 5.09 M | 4.04 M | 3.62 M |
| c00001 | 6.55 M | 4.91 M | 3.88 M | 3.55 M |

All nine manual meshes succeeded first time. Drag at 20 m/s (whole car):

| Mesh | team car | c00004 | gap |
|---|---|---|---|
| auto 6, 1.5 mm box | 0.3843 N | 0.4081 N | +6.2 % |
| min 0.8 mm, 1.5 mm box (used) | 0.3823 N | 0.4098 N | +7.2 % |
| auto 6, 1.0 mm box | 0.3585 N | see `simscale_results/validate` | |

The 1.0 mm box lowers the absolute drag by 7 %, so absolute values are not mesh-converged; what the evolution needs is the ranking, which the finer-mesh run of c00004 checks. Winners are re-run on the finer mesh before they are trusted. `simscale_validate.py` runs such checks outside the evolution.

Cost seen on the first run: estimate 8.7 core-hours and 65 min; the real run took about 2 h 15 min wall time.

## 4. Smoke test (no runs spent)

```bash
export SIMSCALE_API_KEYS=... SIMSCALE_HOLD_RUNS=1 TICK_S=30
python campaign.py init runs/smoke <a copy of config.simscale.json with cma budget 2, batch 2>
python campaign.py run runs/smoke          # Ctrl-C after ~10 min
python campaign.py status runs/smoke       # "simscale": cases should reach phase "mesh" with mesh_done true
```

`SIMSCALE_HOLD_RUNS=1` stops every car after meshing, before a run is started (runs are what cost credits). Open the project in the web UI and check one simulation: wheels rotating, road moving, car no-slip.

To build one air volume by hand: `python simscale_step_domain.py exact --out team.step` (the team car exactly as its STEP).

## 5. The geometry engine (what happens to each car)

The design side (`geometry.py`) is unchanged:

1. **Read** `cad/trial_car.step`: exact B-rep body and wheels.
2. **Take the design:** a field over a 1 mm grid of the sidepod region. Foam goes where it's positive.
3. **Finish:** symmetric left/right; forced air removed; locked CAD kept.
4. **Mill:** top and bottom set-ups, 3.175 mm ball; unreachable air becomes foam.
5. **Clean:** 3 mm minimum-wall filter, loose pieces deleted.
6. **Check:** every rule in section 1. Illegal cars never reach SimScale.
7. **Build the exact surface** and weigh it (foam, lead, centre of mass).
8. **Export** `cars/<id>/`: `body_mm.stl` (the body, STEP frame, mm), STLs for OpenFOAM, `mass.json`.

**The SimScale air volume** (`simscale_step_domain.build_design`). SimScale's API cannot extract a flow volume, and it splits multi-solid STL uploads into pieces, so we send it the air itself, the way the team's Fusion add-in does:

| Part | How it goes into the STEP |
|---|---|
| The car outside the sidepod region | the team's **exact** B-rep, cut by the region grown 0.3 mm (`seam_region`) |
| The designed sidepod (+y side) | the designed body inside that same grown region, reduced to about **4500** well-shaped triangles (pymeshlab quadric collapse). The band between the region and the seam is the original shape, so nothing changes. |
| Wheels | exact B-rep |
| Air | the half tunnel box minus all of the above, ONE solid; road 0.15 mm under the wheels |

Faces are named in the STEP (inlet, outlet, symmetry, side, top, ground, wheelF, wheelR; every other face is the car), and SimScale keeps the names. Checks before upload: one solid (air sealed inside the body is dropped and logged), all 8 names present, removed volume = car + wheels (±0.3 %).

**How this route was found** (SimScale reports why an import fails in `failureReason`; read it before changing anything):

| Tried | Result |
|---|---|
| Exact CAD + triangle pod, seam ON the region boundary, 0.05 mm overlap | about 2 in 3 imports refused: "invalid edge" / "bad face-face". The region's planes (the 27.175 mm sidepod top, the spine underside at z = 17) are planes of the team's CAD, so the seam lay on CAD faces. |
| Whole half body as 20k triangles | imports, but meshing fails ("element size too close to the CAD tolerance"): the team's CAD has 263 faces under 0.1 mm², whose triangles are 0.04 mm wide. Raising small-feature suppression to 0.2 mm meshes, but only with boundary layers off. |
| **Seam moved 0.3 mm off the region, no overlap** | **3 of 3 designs imported first time; both tested meshed with boundary layers.** Any overlap (0.02–0.1 mm) breaks the OpenCASCADE cut on some cars. |

If SimScale still refuses one, the evaluator rebuilds the pod with another triangle count (4500 → 5200 → 3900 → 6000 → 4200 → 6800 → 4800 → 5600 → 3600 → 7500) and tries again; mesh failures get the same treatment. The reasons are logged in `tries`.

**Per car, the evaluator (`simscale_step_eval.py`) walks:**

```
wait (no key free) -> step (build + upload the STEP) -> import -> mesh -> run -> done
```

State is in `simscale_state.json` next to the campaign, so the campaign survives restarts.

## 6. Running the evolution

The config is `config.simscale.json`:

| Stage | What runs |
|---|---|
| `evolve` | CMA-ES, generations of 8, on a 6 × 3 × 4 lattice of design values (72 numbers plus a blend weight), starting from the team's sidepod. The team's car is timed first as the reference. The budget is set high (400); in practice **the keys are the budget**. |
| `recheck` | The best 4 are re-timed in our own OpenFOAM on GitHub Actions (section 7). |

```bash
python campaign.py init runs/simscale config.simscale.json
export SIMSCALE_API_KEYS='key1,key2,...'
python campaign.py run runs/simscale          # polls once a minute (TICK_S); or cron `campaign.py tick` every few minutes
python campaign.py status runs/simscale       # stage, method progress, and per key: runs used, project, retired?
python campaign.py report runs/simscale       # runs.md, convergence.png, best.png, best/<car folders>
```

**Keys and the 10-run waves.**
- The first key runs the reference plus up to 9 designs.
- When every key in `SIMSCALE_API_KEYS` has used `runs_per_key` runs, the campaign submits nothing new. `status` shows `"capacity": 0`.
- Add new keys to `SIMSCALE_API_KEYS` (keep the old ones there, so results of their last runs can still be fetched), then restart `campaign.py run`.
- A key that returns a quota error or 401/403 is marked `retired`. Its unfinished cars move to the next key and start again from the upload.

**Errors never blame a design unless the design is at fault.**
- Network, quota and auth errors: the car waits and retries.
- A bug in our code: the car waits, with `last_error` shown in `status`.
- Import failure, mesh failure, or a run that diverges in its first few iterations (a bad mesh element: seen once, at iteration 1, charged 0 core-hours) all restart the car at the next of 10 pod triangle counts.
- Only a geometry that can't be built, or fails all 10 counts, or diverges late in the run, counts as a failed design. CMA scores it as worse than its generation.
- Finished results stay in `simscale_state.json` (`done`) until the campaign has stored them, so stopping the process mid-collect loses nothing.

**State lives on disk,** so a run can die or be restarted at any point. `runs/` is not in git: `simscale_results/` holds a committed copy of everything needed to carry on (state files, designs, `x/`, the CMA pickle in `cma/`). On a fresh container, restore it with
`mkdir -p runs/simscale/runs && cp simscale_results/{state.json,simscale_state.json,designs.jsonl,config.json} runs/simscale/ && cp -r simscale_results/x runs/simscale/ && cp simscale_results/cma/*.pkl runs/simscale/runs/`
(cars in flight also need their `cars/<id>/body_mm.stl`; when none are in flight nothing else is needed).

| File | Holds |
|---|---|
| `simscale_state.json` | key fingerprints (runs used, project, retired) and cars in SimScale, each at its phase |
| `state.json` | stages and budgets |
| `designs.jsonl` | every car built, legal or not, with its result |
| `runs/*.pkl` | each method's memory |

**To stop:** set `"stopped": true` in `state.json`.

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
| `status` shows `capacity: 0` | every key has used its runs: add keys (section 6) |
| a key `retired` with a quota/401 message | that account is out of credit or the key was reset; its cars move to the next key |
| a car stuck with `last_error` | read the message: a proxy/network error clears itself; anything else is a bug to fix (the car is not blamed) |
| "import refused 10 times" | a pod SimScale won't take at any triangle count (rare); the design counts as failed. `tries` has SimScale's reasons |
| "named faces missing after import" | the STEP lost its face names (check `simscale_step_domain.write_step`) |
| "too expensive" in `designs.jsonl` | the estimate exceeded `max_cost` (core-hours) |
| Everything illegal | read `check` in `designs.jsonl`: thin foam or pieces usually means the step size is too large (lower CMA `"sigma"`) |

## 10. What is tested, and what is not

| Part | Status |
|---|---|
| Rules (cargo off, 27.175 mm ceiling, top/bottom milling, 3 mm walls, one piece), exact watertight export | tested |
| Air volume STEP (exact CAD + triangle pod, seam 0.3 mm off the region), names surviving SimScale's import | tested on SimScale: 3 evolved designs imported first time, 2 meshed with boundary layers |
| Simulation + mesh built from code, run on SimScale | tested: the team car meshed (5.7 M cells) and ran |
| Campaign → SimScale (keys, retries, import re-tries) | running: first generation solved on SimScale (runs take 4–6 h each) |
| Force reading | see the status line at the top |
| Actions re-check | dry-run tested; a real dispatch has not run yet |
| Whole car (nose, rear pods) and the 3 layout variables | **not built**; only the sidepod region is designable |
