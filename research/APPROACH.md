# How to actually find the fastest car

Written 2026-11-19 after a full read of the five parts. This page covers three things:
what the current code does and where it goes wrong, how each proposed optimiser fits this
problem (with benchmark numbers), and the plan.

## 1. What the code does today

The pipeline is good engineering wrapped around the wrong search.

**Worth keeping as they are:**
- `part5-simulation/legality.py` (the referee). It has 113 rule rows, edge tests on every
  numeric rule and no shared code with the cutter. It costs no CFD, so it can screen
  thousands of cars for free.
- `part2-simulation` stopwatch work: the frozen reference, 2-core repeatability, chained
  6-hour jobs and the Ahmed bias. This is careful, honest measurement.
- `race_objective.py`, the race-time model (JAX). Its placeholders are listed in section 4.
- `part4` manufacturing files, mass roll-up and part gates.

**Where it goes wrong:**

1. **It optimises the smallest part of the drag.** `part4-simulation/assembly.py` says
   "wheels are 64-75 % of the car's drag and the body only 13-22 %". The wheels are fixed
   team STLs (`wheel.py`: "the wheels are the team's STLs"). Almost all the search machinery
   (the level-set cutter, the compass and the 255-run measured map) works on the body, so it
   tunes the 13-22 % slice in fine detail. The part that controls the wheels' drag is the
   flow onto and around them: front-wing wake, pods and shielding, how the wheels are covered
   within T7.9, wheel width at the T7.4 minimum, and hub and support shape. That is only
   touched through a handful of wing and support scalars.

2. **Carving can't reach a different kind of car.** The current plan carves down from the
   full legal block. Each cut stays within about 1.5 mode heights (~1 mm, part3 PROOF step
   rehearsal), with 25-40 rounds per chain and 3 chains. Even if every step were kept, the
   end result is the block with ~25-40 mm of total local moves spread over the surface. A
   catamaran tunnel, real sidepods or wheel pods are 10-20 mm away *everywhere at once*, and
   the path between passes through flow-separation changes, so no local gradient leads there.
   The old lofted body did have a tunnel and sidepods, but the tunnel was a token one
   (`ft_h` <= 10 mm, off by default), and that body was dropped for carving.

3. **The low-noise stopwatch only works close to one reference car.** The noise drops from
   8.65 ms to 0.09 ms in part2 PROOF only because every car is *reshaped from one frozen
   reference mesh and warm-started from one of its two frozen flow states*. That is fine for
   1 mm cuts. A car with a tunnel or a different pod cannot be morphed from the reference
   mesh, so it falls back to fresh-mesh noise (5-9 ms). In practice the measuring method
   rules out big design changes.

4. **The flow has two answers and RANS picks one.** Fresh meshes put near-identical cars
   12 % apart in drag (body and rear-wheel wake switch together). The fix chosen was to
   average the two frozen states ("method A"). That hides a real physical effect: the rear
   wheel wake is bistable at this Reynolds number (~3e5). Which state a *real* car sits in
   decides milliseconds, and steady RANS cannot say. The Ahmed check (+9.5-13 % drag, worse
   on the wall-resolved mesh) says the same thing: SST misjudges separation, and separation
   is exactly what tunnels, sidepods and wheel wakes are about.

5. **Body mass is fixed by the "no ballast" rule.** `run_car.py:288` sets
   `ballast_material=None  # the team adds no ballast`. The foam body is then sized until the
   car weighs 48.2 g, so the body's *volume* comes from the parts' weight, not the aero.
   `ballast.py`'s own notes say lead in the capsule needs 45 % less foam (tungsten: 75 % less).
   This choice limits every body the optimiser can make, yet nothing in the search tests it.

6. **The tests mostly check the code against itself.** Examples: golden files from the code's
   own runs (`grow_truth_96_0de1e3e.txt`), the loop tested on a 6-D fake bench with an exact
   or noisy gradient oracle and iid noise (`checks/bench.py`), and rule edges tested on box
   cars. None of that is wrong, but no test checks that the *physics ranking* is right. No
   car has been built or timed, and the race model's friction, tether-guide friction, wheel
   spin-down and part weights are placeholders. The fake bench has no flow-state jumps and no
   fidelity gap, so it says nothing about how the loop behaves on the real noise.

7. **The supports and materials aren't really design choices.** "Material" is a density.
   The beam-support architecture is fixed and only its scalars move. Nothing decides between
   architectures (beam vs pod vs body-integrated vs carbon-rod axle) or materials on
   stiffness, mass and aero together.

## 2. The proposed methods, judged against this problem

The real budget: one fine run is ~4.5 h, one medium run ~45 min on 2 cores, and there are
about 4 working GitHub accounts. That is roughly **15-25 fine-run equivalents a day**. Every
method below is judged on what it delivers inside a few hundred fine-run equivalents.

| Method | What it's good at here | What breaks it here | Verdict |
|---|---|---|---|
| Discrete adjoint (DAFoam / SU2) | All shape slopes from ~2 runs, whatever the number of shape variables. The right tool to polish the surface of a car whose layout is already chosen | Needs a converged steady flow, and our wake is bistable, so the slope belongs to one flow state. Changes shape by FFD morphing, so it can't add a tunnel. Fine-mesh AD memory is tight on 16 GB runners. Our continuous adjoint already failed the wing test (r 0.42-0.70); a discrete one is consistent with the solver and should pass, but has to be proven | **Use for the final polish only**, after it passes the existing wing known-answer gate *and* a 10-variable car gate (r >= 0.9 against finite differences) |
| Bayesian optimisation (Kriging + EI) | Fewest runs at 10-30 settings. Handles noise with a nugget term. Batches suit parallel jobs | Plain GP-EI degrades past ~30-40 variables | **Use for the 26 part and layout settings**, in the trust-region form (TuRBO), which held up best in the bench |
| Multi-fidelity co-Kriging | We already have medium and fine meshes with Spearman 0.96 between them, the ideal case. Medium is ~1/6 the cost | Fails if the medium mesh's error doesn't follow a smooth pattern (e.g. medium picks the other wake state) | **Use**, layered on BO. Cheap to try because the 20-car medium/fine pairs already exist |
| POD reduced-order model | Predicts whole flow fields. Very strong on a fixed-topology morph family (DrivAer) | Needs all snapshots on one mesh/topology. Tunnel vs no tunnel breaks it | **Not now.** Maybe later, inside the one chosen concept |
| CMA-ES / derivative-free | Robust and simple. Doesn't care about noise or kinks | Needs ~10-100 x the number of variables in runs, so thousands of CFD runs | **Use only on cheap things**: maximising the BO acquisition, or the free legality-only problems |
| Geometric deep learning | Can learn whole shapes | Needs hundreds to thousands of sims. Our Reynolds number and rules differ from public car datasets. Surrogate exploitation is a real risk | **No**, not until every run we make has been logged as training data |
| Evolution merging designs (GA) | Can combine features of good cars | Same run count problem as CMA-ES | **No**. The concept choice is a short list, so try each instead |

### Benchmark (`research/optimiser_bench/bench.py`)

This is a stand-in problem tuned to the repo's own measured numbers: 0.3 ms noise, a 1.3 ms
flow-state jump, medium-vs-fine Spearman ~0.96, fine = 6 x medium cost, and a ~20-40 ms gap
from the start car to the best car. The adjoint is modelled as a gradient with correlation r
to the truth (0.55 = what part3 measured; 0.97 = a working discrete adjoint). Each method is
scored on the *true* time of the car it hands over. Results are in section 5.

It does not test POD or deep learning (both need flow fields), and it can't test whether a
given method finds a better *kind* of car. That is the next point.

## 3. The bigger problem: none of these methods invents a car

Every method above tunes numbers inside a family of shapes someone has already defined.
Which family you search decides more than which optimiser you use. So the plan is in layers:

**Layer 0: measure what the model guesses (weeks, little compute).** Print and time 2-3
cars on the track. Run a spin-down test for wheel friction and a tether-guide drag test.
Without these, the optimiser sharpens a model whose friction terms are placeholders and
whose aero ranking has never been checked against reality.

**Layer 1: concept families as real parametric CAD**, each with ~15-30 meaningful settings,
built through the existing referee and Part 4 parts:
- *C1 catamaran*: two narrow hulls over the wheels and a deep central tunnel. Tunnel depth,
  width, roof shape, entry/exit ramps, hull section.
- *C2 central body + sidepods + wheel pods*: pod shape behind the front wheels shielding the
  rear wheels, sidepod undercut and taper.
- *C3 minimum-volume body with ballast*: as slim as the cargo and chamber allow, the mass
  made up in the halo capsule.
- Each with the wheel-side package as variables: wheel width at the T7.4 minimum,
  front-wing span and endplate turning flow around the wheels, hub cover, and the support
  section and position.
- **Wheel supports** as a categorical choice of architecture x material (PA12 SLS beam /
  PLA / foam-integrated / carbon-rod axle), each with a structural check: halo load,
  T7.13 hang test, axle deflection under the launch load.

**Layer 2: pick the concept.** For each family: multi-fidelity TuRBO, ~60-100 medium runs
plus ~10-15 fine runs. Compare the families by their *optimised* best, with error bars.
The finalists then get a time-accurate (URANS) run each, to see which wake state they
really sit in.

**Layer 3: polish the winner.** Discrete adjoint with FFD on the fine mesh, if it passes the
gates. If not, use the existing measured map on a reduced FFD basis. This is the only place
the current carving/compass machinery still fits.

**Layer 4: confirm.** Resolved mesh plus a physical timed run of the top 2.

## 4. Open items in the race model (all placeholders today)

Rolling friction 0.010, tether-guide friction (mu_guide 0.25) and tether drag (not modelled),
wheel inertia 1.39e-7, and printed part masses (datasheet, never weighed). The model says
0.199 ms per mN of drag and 7.51 ms per gram. Track times of real top cars (1.0-1.1 s) don't
match the raw model (0.95 s), and the model has never been calibrated against a timed run.

## 5. Benchmark results

(filled in below)
