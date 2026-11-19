# Sidepod region: which organic search finds the fastest sidepod?

Input: the team's `cad/trial_car.step` (body + 4 wheels) and a sketch circling the boxy block
between the wheels. Everything else on the car is held fixed. Seven search methods, none with
hand-chosen variables, compete for the fastest race time on the same budget of tunnel runs.

## The region (`region.py`, picture `results/region.png`)

Per side, mirrored:
- **Box**: x 49.4–159.1 mm (between the wheels), out to |y| 32.5 mm (T1.14 block half-width),
  z 1.5 mm (T3.7 clearance) to 40 mm.
- **Forced air**: the T7.9.2 wedge behind the front wheel (15 mm at the inner edge, 60°), the
  T7.9.3 wedge ahead of the rear wheel (5 mm, 45°), and everything above z 27 mm from x 115 mm
  forward (T4.4.2: the halo, at x 120–160, z 28–38, must stay visible from the side).
- **Forced solid**: the T4.2 virtual cargo (60 mm long, 55 → 10 mm wide, 10 mm tall), wide
  end forward, x 76–136, z 17–27: the layer where the trial car is solid across its full width.
  The trial car has a tunnel under the spine (no foam at |y| < 15 mm below z 17.5 mm); an
  earlier placement at z 7–17 filled that tunnel with 2.5 g of forced foam, so those runs were
  discarded (`results/old_cargo_low/`). **Assumed: confirm the team's cargo position.**
- **Kept as drawn**: the spine (the body at |y| ≤ 13.5 mm and z ≥ 17 mm: deck, cockpit, halo)
  and the whole body outside the box.

The trial box already clears the T7.9 wedges (its corners are chamfered in plan).

Every design passes the same finishing step: rule zones forced, cargo forced, closed and opened
by one 3 mm cell, one piece with the spine. Then it is **milled** (`milling.py`): rebuilt at
1 mm with a smooth surface and cut with Part 1's own rule (team process: 3-axis, 6.35 mm ball
end, setups top/bottom/left/right). Air the ball can't reach stays foam, sealed voids stay foam,
loose pieces are dropped. **The milled body is what gets weighed and put in the tunnel.**

Why: scoring the 3 mm design directly missed the cutter's 3.175 mm corner fillets, which add
0.5–1.7 g of foam on the real part, and a few designs had small undercuts. `check_outputs.py`
checks every output for weight, pieces, sealed voids, undercuts, walls under 3 mm, wheel gap
and track clearance.

## The scorer: race time, not drag (`score.py`)

- **Drag and lift**: from the tunnel, as changes from the original car run the same way, scaled
  to D20 = 0.39 N for the original.
- **Mass**: no upper limit. A heavy car is legal and pays 16.4 ms/g through the race model.
  Only the T3.6 floor applies: a car lighter than 48.0 g (+0.2 g margin) gets lead in the halo
  container (T1.22, 1.39 cm³ ≈ 15.7 g). A design needing more lead than fits is illegal.
- **COM**: exact, from the original body + the design's change + fixed parts + lead.
- All of it goes through Part 2's `race_objective` (pitch balance, guide friction).

Exchange rates on this car (original design): **0.45 ms per mN of drag, 16.4 ms per g over
48.2 g, −1.5 ms per mm of COM height** (the COM at 19 mm is far below the 30 mm thrust line, so
raising it helps), −0.11 ms per mm of COM moved rearward.

**Assumptions (the STEP has no parts list):** non-body parts = 48.2 g minus the drawn body's
foam (the trial car as drawn is the 48.2 g no-ballast car), their COM mid-wheelbase at z 16 mm;
foam 0.163 g/cm³; thrust line z 30 mm with the cartridge's rear centre 13 mm behind the tail
(the STEP has no chamber bore); guides 5 mm outside each axle.

## The tunnel (`lbm3d.py`, `tunnel.py`)

D3Q19 lattice Boltzmann, regularized BGK + Smagorinsky LES, 3 mm cells, half car with a
symmetry plane, rolling road (held still under each wheel contact, see below), free-slip top
and side. 157 × 36 × 32 cells. Re ≈ 2×10³ (the real car is ~3×10⁵), so it ranks shapes cheaply
and must be checked against OpenFOAM before any shape is trusted.

Measurement copies Part 2's stopwatch idea: every design starts from one frozen flow
(state A, the original car after 5000 steps), runs 1200 steps and averages the last 700. A
second frozen state (B, 1000 steps later) measures how much a result depends on the start
state.

Known artefacts: at 3 mm the wheel/road contact wedge is unresolvable. A spinning wheel
pumped mass there and blew up, so wheels are held still on a still patch of road under each
contact (+ a plinth); the road moves everywhere else, including under the sidepods. Lift
carries a constant pressure offset on the plinths, so only lift changes are used.

## The methods (`methods.py`, `topo_run.py`)

| Method | What it searches | How it moves |
|---|---|---|
| Random | smooth random fields around the original | none: the bar to beat |
| CMA-ES | 8×3×4 control lattice added to the original's signed distance | evolution strategy |
| CPPN-NEAT | a growing network over (x, y, z, distance to cargo, distance into the original) | neuro-evolution, seeded with 5 hand networks (original, lean, low pods, tapered, lowered) |
| Bayesian opt. | same lattice | GP + expected improvement in a trust region (TuRBO-style) |
| SAIL | same lattice | MAP-Elites on the GP (descriptors: foam mass, pod height); the tunnel checks the most promising archive cells |
| Level set, SPSA | every cell of the region | gradient from one random ± perturbation (2 runs per step) |
| Topology opt. (adjoint) | every cell, as a solid fraction | exact gradient of race time from a differentiable JAX copy of the tunnel (porous cells), charged as 2 runs per step |

Illegal designs cost no tunnel run (as with the real referee), but are capped.

## How the methods are judged

1. Same budget: 30 tunnel runs (topology: 2 per gradient step + 1 per scored design).
2. Score = race time of the best legal design the method hands over.
3. **Re-scored honestly**: each method's best is re-run 2× longer from state A and from state
   B. A design that only won through a short, single-state measurement drops here.
4. Two seeds per method (where time allowed): one lucky run is not a method.

## Results

(filled in below)
