# SimScale template reference

**The full step-by-step guide is `EVOLUTION_SIMSCALE.md`.** This page only keeps the template simulation's settings, for reference.

## 1. What you do once

1. **API key.** In SimScale, open your account settings and find "API keys". If there is no such page, your plan has no API access, and this route cannot run. Set it as `SIMSCALE_API_KEY` in the environment; never commit it.
2. **The original car's files.** Run this from `research/sidepod_opt/`:
   ```bash
   python -c "from pathlib import Path; from geometry import Car; c = Car(); c.export_car_folder(c.body_mesh, Path('simscale_template'), 'original')"
   ```
   Zip `car_half.stl`, `wheelF.stl` and `wheelR.stl` and upload them as ONE geometry, units **m**. The solids must keep their names: `car`, `wheelF`, `wheelR`.
3. **One simulation on it**, named anything. It copies Part 2's setup:

| Setting | Value |
|---|---|
| Analysis | Incompressible, steady, k-omega SST |
| Fluid | air, ν = 1.48e-5 m²/s (μ 1.813e-5, ρ 1.225) |
| Domain | external box: x −0.771 to 2.314 m, y 0 to 0.192 m, z 0 to 0.245 m (the car's nose is at x = 0 and the flow is +x) |
| Inlet (x min) | velocity (20, 0, 0) m/s, turbulence intensity 0.5 %, eddy viscosity ratio 5 |
| Outlet (x max) | pressure 0 |
| y = 0 | **symmetry** (half car) |
| Side, top | slip |
| Ground (z = 0) | **moving wall**, velocity (20, 0, 0) m/s (a rolling road) |
| `car` | no-slip wall |
| `wheelF` | rotating wall, axis (0, 1, 0) through (0.055384, 0.027875, 0.01382) m, ω = −1416.43 rad/s |
| `wheelR` | rotating wall, axis (0, 1, 0) through (0.193384, 0.024875, 0.01382) m, ω = −1416.43 rad/s |
| Result control | **"Forces and moments"** (exactly this name) on `car` + `wheelF` + `wheelR` |

4. **One mesh operation** on that simulation. Use automatic or standard meshing with refinement on the car and wheels and a refined region under the car (the gap is 1.5–2 mm). Every design copies these mesh settings.
5. **Run it once** and check the drag. Our OpenFOAM gives 0.183 N for the half car. Agreement within 10–15 % is normal across solvers; only SimScale-to-SimScale differences steer the search.
6. **IDs:** `python simscale_tool.py ids` lists the project, simulation and mesh-operation IDs.

## 2. What runs

The config is `config.simscale.json`:

- **`evolve` stage:**
  - `sail`: 80 cars, batches of 8.
  - `cma`: 240 cars, generations of 12.
  - The original car is also run once on SimScale as the reference.
  - Lower the budgets to fit your quota.
  - `max_cost` stops any car whose SimScale estimate is above it before its run starts.
- **`recheck` stage:** the best 4 are re-timed in our OpenFOAM pipeline on Actions. Set `repos` to the compute repo.

```bash
python campaign.py init runs/simscale config.simscale.json
# fill project_id / template_sim_id / mesh_template_id / max_cost in runs/simscale/config.json
SIMSCALE_API_KEY=... python campaign.py tick runs/simscale      # cron this, e.g. every 10 min
python campaign.py report runs/simscale
```

- **Each tick** builds new cars, submits them, and advances every in-flight car one step (import → mesh → run). `runs/simscale/simscale_inflight.json` keeps that state, so a tick can die or be restarted at any point.
- **Cars that are not legal** (rule checks or the 3 mm minimum wall) never reach SimScale and cost nothing.

## 3. First real test

Run the campaign with `"budget": 1` for both methods. That is 3 cars: the reference plus 2. Check:
- the reference drag against step 1.5;
- that the remapped boundary conditions landed on the right solids (open one design's simulation in the web UI);
- the cost per car.

Then raise the budgets.
