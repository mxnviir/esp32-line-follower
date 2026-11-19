# Wings, nose cone and wheel supports: design plan

Status: plan only. Nothing here is built yet. Written 2026-11-19 from the team's answers.

## Team answers this plan is built on

1. **Wheel supports:** one printed part for the front axle, one for the rear (wheel to wheel).
2. **Flat face:** a disc covering the wheel's inner side, with the axle stub coming out of it, as
   in Part 4. A printed 3 mm journal, a 3×6×2.5 mm bearing pressed on, and a hub cap.
3. **Printing:** ABS, FDM, 0.2 mm nozzle.
4. **Flush patch on the body:** any shape, as long as nothing is too thin.
5. **Nose cone:** may mix foam and ABS. Ahead of Ref A plastic is *allowed*, not required.
   Wings and wing supports are ABS up to the slot into the foam part of the nose.
6. **Loads:** keep Part 4's (3 N radial at the bearing, 1.2 N sideways at the contact patch,
   ≤ 0.15 mm sag at the bearing, safety factor 2, the T7.13 100 g hang).
7. **Order:** step by step, then a final combined run.

## Which parts are parametric, which are organic

The rules decide it. Where a rule fixes a dimension everywhere, a free shape is mostly illegal,
so the part stays parametric. Where a rule only bounds a volume, the part is organic.

| Part | Kind | Rules | Variables |
|---|---|---|---|
| Front wing | parametric, smooth spanwise | T8.6: chord 15–25 mm and thickness 2–6 mm everywhere; span ≥ 50 mm (or 2 × 25 mm split); T8.5.2; T8.7 5 mm clear air; T8.8 | Part 4 `FrontWing` (NACA section, angle, height, span, flap), plus chord, camber, twist and thickness as smooth splines along the span |
| Rear wing | parametric, smooth spanwise | T9.4–T9.7: chord, thickness, unbroken span ≥ 50 mm, ≤ 15 mm height change along the span, behind Ref B, ≤ 40 mm overhang | Part 4 `RearWing`, plus spanwise splines |
| Front wing supports | organic | T8.5.1: ahead of Ref A, ≤ 25 mm high, **within ±15 mm of the centreline**; T8.6.1: a support through the wing can split the span into 2 × 25 mm | grown between anchors |
| Rear wing pylon | organic | T9.4.1 behind Ref B; T9.5.1: its own pylon may sit under the wing without breaking the span; T9.6 clear air | grown between anchors |
| Endplates | organic, bounded | T8.5.3: ≤ 10 mm wide, ≤ 25 mm high outside the wheels, outside the minimum span | grown |
| Nose cone | organic shape, material decided by rule | T8.2 ≤ 40 mm ahead of Ref A; T8.5.1 box | one shape field |
| Wheel supports | organic around fixed hardware | T7.12.1 support only **inside the wheel cylinder**; T7.10 wheels seen from the side (supports excepted); T7.13 claw clearance 1.5 × 1.5 mm; T3.7 clearance | grown from the flat face to the flush patch |

## How the two kinds connect

1. **Parametric parts are built first.** Each one gives its exact shape plus anchors: the fixed
   ends an organic part must connect, and the no-go zones it must avoid.
   - Front wing: the patch on its underside where a support may attach; its T8.7 clear-air zone.
   - Wheel hardware: the flat face, the 3 mm journal with its shoulder, the bearing seat, the
     T7.13 claw clearance. Never designed, always stamped in exactly from the team's CAD.
2. **Organic parts are grown by structural topology optimisation:** least material that carries
   the loads between the anchors. A voxel finite-element solve per design (seconds).
3. **Nose material is decided, not searched.** One nose shape field; each cell is then labelled:
   - **Foam** where the mill can make it, it is ≥ 3 mm thick, and it connects behind the slot.
   - **ABS** where it is thinner or unreachable, and from the slot forward wherever it carries
     the wing supports.
   The ABS piece gets its plug and pocket at the slot through Part 4 `joints.py`, flush outside.
4. **Nested search.** Outer loop: CMA-ES or Bayesian optimisation over the parametric settings
   (a few dozen numbers), scored by CFD race time. Inner loop: for each outer choice, grow the
   supports and fit the nose to that exact wing. Every wing is judged with its own supports.
5. **Polish.** Once the layout settles, the organic fields can be refined directly against CFD
   (level-set descent, or the adjoint only after it passes its known-answer gate), within the
   strength limits.

## Manufacturing checks per material, before any CFD

- **Foam:** Part 1's milling rule (3-axis, 6.35 mm ball end, top/bottom/left/right), pockets and
  glue gaps from Part 4 `joints.py`, ≥ 3 mm walls (`rules_constants.MACHINED_MIN_WALL_MM`).
- **ABS, FDM, 0.2 mm nozzle:**
  - minimum wall ≈ 0.45 mm (2 lines); load-bearing members ≥ 1.2 mm
  - minimum feature ≈ 0.5 mm
  - overhangs ≤ 45° in the chosen print direction, or flagged as needing support material
  - no sealed holes; one piece; the plug fits its pocket
- **Whole car:** Part 5 `legality.py` on the assembled meshes, every design, as the referee.

## Known problems with this plan (from the review)

- **Resolution.** A 0.2 mm nozzle needs a design grid of ≈ 0.25 mm near the printed parts, not
  1 mm. Plan: a local fine grid per printed part, or a mesh/implicit (SDF) representation.
- **Loads.** Part 4's loads were calibrated to the team's SLS PA12 support. FDM ABS is weaker,
  and much weaker between layers. The printed 3 mm axle is the weakest point. The finish-catch
  impact is the load most likely to break a part and is not in the list. These need a measured
  break test or a decision from the team before the structural check can be trusted.
- **Aero in the inner loop.** Growing supports for stiffness with a frontal-area drag stand-in
  ignores aerodynamics where most of the drag is (wheels 64–75 %). The inner loop can only
  propose; CFD must decide, and the support's aero has to be in the CFD run.
- **Wing Reynolds number.** At ≈ 20,000 on the chord, steady RANS is unreliable for the wing
  (laminar separation bubbles). Wing choices need a transition model or a transient check.
- **Noise.** Each new wing or support layout needs a fresh mesh; Part 2 measured several ms of
  fresh-mesh noise. Effects smaller than that need repeats or a morphable family.

## Order of work

1. Wheel supports, body fixed: anchors, topology optimisation, FDM checks, joints.
2. Front wing + its supports + nose together (outer: spline wing; inner: grown supports, nose
   with automatic foam/ABS split).
3. Rear wing + pylon, same pattern.
4. Sidepods with everything else fixed.
5. Final combined run: a couple of rounds over all blocks, then a fine-mesh polish and confirm.
