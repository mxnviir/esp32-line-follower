# STEM Racing car: every requirement, and what an organic generator may change

Source: *STEM Racing UAE Professional Class Technical Regulations 2026-2027* (dated 19 Oct 2026),
read page by page, plus measured facts from this repo. Rule numbers are the regulation's own.
All limits are absolute (T2.7.1: 48.0 g passes, 47.9 g fails). Diagrams in the regulations are
illustrations only (T2.2.1): the text decides.

How to read each section:
- **Rule**: what the regulation says.
- **Generator**: how a parameter-free (organic) design generator must treat it:
  `FORCED SOLID` (must be material), `FORCED AIR` (nothing may be there), `FIXED OBJECT`
  (a part whose shape is set: only where it sits can change), `FREE` (the generator may put any
  shape here), `CHECK` (can only be judged on the finished car, by the referee).

---

## 0. The car in one picture (datums)

| Datum | Definition | Rule |
|---|---|---|
| Track surface | z = 0 | |
| Vertical reference plane | through the cartridge chamber axis, normal to the track (the car's centreline, y = 0) | T1.17.1 |
| Reference plane A | 16.0 mm **ahead** of the front axle centre line | T1.17.2 |
| Reference plane B | 16.0 mm **behind** the rear axle centre line | T1.17.3 |
| Wheelbase | front axle to rear axle, **120.0-140.0 mm** | T7.3 (PP) |

Everything is placed from these datums. Moving an axle moves Ref A or Ref B and every zone tied
to it, so the generator must rebuild all zones whenever the layout changes.

**Allowed parts only (T1.1, T3.3):** body, nose cone assembly (nose, front wing support, front
wings, end plates), rear wing assembly (support, wings, end plates), front and rear wheel support
systems (wheels rotating, supports not), two tether guides, finish and decals, two logo decals,
halo, helmet, legal ballast. Anything else is an "additional component" (T1.18), a 20-point
penalty (T3.3). Adhesive with no dimensional effect is allowed (T1.1).

---

## 1. Whole car

| Requirement | Limit | Rule | Generator |
|---|---|---|---|
| Total width | **65.0-85.0 mm** (outer edges of the widest feature, normal to the vertical plane) | T3.4 (PP) | CHECK; also bounds every FREE region at ±42.5 mm |
| Total height | **≤ 65.0 mm**, with a full cartridge in, on 4 wheels | T3.5 (PP) | FORCED AIR above z = 65 |
| Weight | **≥ 48.0 g** without cartridge | T3.6 (PP, 10 pts/g) | Derived: ballast fills the gap (section 9) |
| Track clearance | **≥ 1.5 mm** for everything except wheels, with cartridge in, on 4 wheels | T3.7 (PP, 10 pts/mm) | FORCED AIR for z < 1.5 (except wheels) |
| Static balance | must rest on all four wheels unaided (cartridge in) | T2.7.2, T7.6 | CHECK: centre of mass inside the wheel footprint |
| Both race cars | identical geometry | T3.1.4 | |
| Body made by CNC | material removal on a CNC router | T3.1.2 | Body must be millable (section 2) |
| Safe construction | judged | T3.2 (Safety, 10 pts) | |
| Spares | nose/front wing ×2, rear wing ×2, front wheels ×4, rear wheels ×4, supports ×2 each, identical | T3.9 | Removable parts must be separate pieces |

## 2. Body (the milled foam part)

| Requirement | Limit | Rule | Generator |
|---|---|---|---|
| One single uninterrupted piece of Model Block, **behind Ref A only** | 1 piece | T1.3, T4.1 (20 pts) | Must be one connected solid; anything ahead of Ref A is nose cone, not body |
| Contains the virtual cargo **and** the cartridge chamber | | T4.1 | FORCED SOLID (sections 2a, 3) |
| Made from the official Model Block | 223.0 × 65.0 × 50.0 mm, bore Ø18.10-18.15 × 52.0 deep, axis 29.0 mm above the slotted face, 6.0 × 6.0 slot full length centred on the bottom | T1.14, App. ii | The body must fit inside this block (with the block's bore as the chamber) |
| Hand finishing | minimum, only to remove machining marks | T1.13 | Every surface must come from the cutter |
| Finish and decals count in every dimension | decal ≤ 0.5 mm thick | T1.11, T4.8 | Keep 0.5 mm margin on outer limits where decals go |

**Team's milling process (repo, `machining.py`):** 6.35 mm ball end (3.175 mm radius) from top,
bottom, left and right; every concave corner gets at least the cutter radius; minimum milled wall
3.0 mm. So the body has no undercuts the tool can't reach and no inside corner tighter than
3.175 mm. Foam density 0.163 g/cm³.

### 2a. Virtual cargo (T4.2, Performance, 25 pts)
- A wedge: 60.0 mm long, 10.0 mm thick, plan view tapering from **55.0 mm** wide to **10.0 mm**
  wide (minimum sizes). Top surface symmetric about the vertical plane and normal to it.
- **Wholly inside the body** and **wholly between the front and rear wheel centre lines.**
- May share faces with the body; may overlap the ballast container; **may not overlap the halo
  pocket.** Must be shown on the drawings (T4.3).
- **Generator:** FORCED SOLID, but its position (x between the axles, height, which way the
  wedge points) is a placement the search may choose.

### 2b. Halo, helmet and pocket (T1.21, T4.4, T4.5, App. ix)
- Halo: the official part, **no change to size or profile** (T4.4.1, 10 pts). About 50.0 mm long,
  25.0 mm wide, 10.0 mm tall body, 6.0 mm hole for the helmet. Any material.
- Helmet: official part, unchanged (T4.5), 6.0 mm spigot 4.0 mm long. Any material.
- Pocket: cut with a ≤ 6.35 mm ball end to **3.175 mm depth**; **pocket floor 24.0 mm above the
  track and parallel to it**; so the halo's circular notch sits **34.0 ± 1.0 mm** above the track
  (T4.4.4, Safety). It is the stopping point for the arresting cable (App. vii).
- Halo must stay **visible**: front and side views (T4.4.2, 10 pts; the outline from 4.0 mm above
  the pocket floor up), and top view except where the helmet covers it (T4.4.3, 10 pts).
- Halo safety test: 2 kg on the notch with the car held by the cartridge (T4.4.5).
- **Generator:** halo + helmet = FIXED OBJECT at z = 24 (only x moves). Pocket = FORCED AIR.
  Sight lines from the front, side and top onto the halo = FORCED AIR (no body or part may
  block them). The body under the pocket = FORCED SOLID (floor and walls carry the 2 kg test).

### 2c. Decals (T4.6, T4.7, T1.12)
- STEM Racing logo decal, **30.0 × 15.0 mm, on each side, 100 % visible in side view**, wholly
  adhered (T4.6, 5 pts).
- Team number, **on the body between the front edge of the halo and Ref A, visible in plan view,
  text ≥ 8.0 mm**, plus "A"/"B" ≥ 8.0 mm (T4.7, 2 pts).
- **Generator:** FORCED SOLID patches that are flat enough to take a decal: one 30 × 15 mm
  side-facing patch each side; one roughly 9 × 15 mm top-facing patch ahead of the halo.

## 3. Cartridge chamber (T1.4, T5)

| Requirement | Limit | Rule |
|---|---|---|
| Diameter, along its whole minimum depth | **18.0-18.5 mm** | T5.1 (Safety) |
| Cartridge centre above the track (rear centre of the cartridge, cartridge in, on 4 wheels) | **30.0-40.0 mm** | T5.2 (PP) |
| Depth, rim to end | **45.0-58.0 mm** | T5.3 (Safety) |
| Angle to the track | **-3° to +3°** | T5.4 (Safety) |
| Wall of block material all round the minimum depth | **≥ 3.0 mm**; nothing may intersect the chamber | T5.5 (Safety, 10 pts) |
| Cartridge sticks out of the rear | **≥ 5.0 mm**, and visible all round its length (top, bottom, side) | T5.6 (PP) |
| Cartridge (App. vi) | 65.0 (+0.5/-0.5) mm long, Ø18.0 body, Ø8.7 neck, 28.9-29.4 g full | |

- **Generator:** chamber = FORCED AIR (Ø18.15 bore); 3 mm ring round it = FORCED SOLID foam;
  the protruding 5 mm of cartridge and the space round it = FORCED AIR. Chamber height
  (30-40 mm) and angle (±3°) are placements: with the block's bore 29 mm above its bottom, the
  chamber height also fixes how high the block sits, so it is linked to ride height.

## 4. Tether line guides (T6)
- **Exactly two**, firmly fixed; front one on or up to 10.0 mm ahead of the front axle line, rear
  one on or up to 10.0 mm behind the rear axle line; the line passes **only** through them
  (T6.1, Safety, 10 pts).
- Opening **3.5-6.0 mm** (gauge tools) (T6.2); fully closed ring; holds a 200 g weight (T6.3).
- **Generator:** FIXED OBJECT (ring) in each 10 mm window; the straight tether line between them
  and through them = FORCED AIR.

## 5. Wheels (T1.8, T7.1-T7.8, T7.13)

| Requirement | Limit | Rule |
|---|---|---|
| Number | 4 cylindrical wheels: max 2 front, max 2 rear; opposing wheels share one axis | T7.1 |
| Gap between opposing wheels (innermost rotating parts) | front **≥ 38.0 mm**, rear **≥ 30.0 mm** | T7.2 (PP) |
| Track contact width (flat rolling surface, chamfers and fillets excluded) | front **≥ 13.0 mm**, rear **≥ 17.0 mm** | T7.4 (PP) |
| Diameter (across the contact width) | **28.0-32.0 mm** | T7.5 (PP) |
| All four touch the track across the full contact width | cartridge in, before and during the race | T7.6 |
| Rolling surface | same diameter across the contact width: no tread | T7.7 |
| Rotation | all four turn freely on a **3°** slope | T7.8 |
| Wheel safety test | 100 g hung from each wheel by a 3-finger claw; **1.5 mm clearance** from the wheel's inner corner to the body for the claw | T7.13 (Safety) |

- Edge profile is free outside the contact width: chamfered, square or rounded are all shown as
  legal (T7.4 figure). Hub face and wheel construction are free (any material, any assembly).
- **Generator:** each wheel = FIXED OBJECT whose size the team pins (smallest legal: about
  Ø28.0 + margin, contact widths 13.0 / 17.0 + margin). Their positions (track width within T7.2
  and T3.4; axle x within the wheelbase) are placements. The edge profile and hub face can be
  organic within the wheel's own envelope. The claw ring = FORCED AIR.

### 5a. Wheel visibility and clear-air zones (the most constraining rules near the wheels)
- **Top and bottom views:** no part may hide any wheel (T7.9).
- **T7.9 keep-out boxes** (Performance), from the inside edge of each wheel's contact width out to
  the extreme width of the car, from the track up to 65.0 mm:
  - T7.9.1 in front of the front wheels: ≥ 5.0 mm deep (2.5 pts);
  - T7.9.2 behind the front wheels: per the diagram, 15.0 mm deep at the wheel, 30.0 mm across,
    with a 60° chamfer (5 pts);
  - T7.9.3 in front of the rear wheels: per the diagram, 30.0 mm across, with a 45° chamfer,
    5.0 mm at the wheel (5 pts);
  - T7.9.4 behind the rear wheels: ≥ 5.0 mm deep (2.5 pts).
- **Side view:** nothing but the wheel supports (e.g. hubcaps) may hide a wheel (T7.10, 10 pts
  per wheel).
- **Front view:** the front wheels may be hidden only up to **20.0 mm** above the track (T7.11,
  PP, 10 pts/mm). Above 20 mm they must be visible from the front.
- **Generator:** all of these = FORCED AIR. They are why the body narrows sharply at each wheel.
  Note the opportunity in T7.11: anything (nose, wing, body) may sit in front of the lower 20 mm
  of the front wheels, so shielding the bottom of the front wheels from the oncoming air is legal.

## 6. Wheel support systems (T1.9, T7.12)
- Single parts or assemblies joining a wheel to the rest of the car; **non-rotating**; may be
  bought or made by the team; any material (T1.9).
- **Must lie entirely inside the cylinder through the actual diameter of the two opposing wheels
  of that axle** (T7.12.1, 5 pts). Must still meet T3.7 (≥ 1.5 mm off the track).
- Must be identified on the drawings (T7.12.2).
- **Generator:** the support region per axle = a cylinder of the wheel's radius (about 14 mm)
  along the axle line, spanning both wheels. Inside it the shape is FREE (organic stub, flush
  with the body where it meets it), except: the axle and its bearing seat = FORCED SOLID; the
  claw ring = FORCED AIR; z < 1.5 mm = FORCED AIR. Outside the cylinder, no support material.
  Strength (100 g claw test, launch and track loads) is a CHECK the generator should size for.

## 7. Nose cone, front wing, end plates (T1.6, T1.7, T8)

| Requirement | Limit | Rule |
|---|---|---|
| Nose cone exists only **ahead of Ref A**; it carries the front wing; any material, incl. Model Block | | T1.7, T8.4 |
| Nose overhang: Ref A to the extreme front of the car | **≤ 40.0 mm** | T8.2 (5 pts) |
| Nose and front-wing support: ahead of Ref A, **≤ 25.0 mm above the track**, within **±15.0 mm** of the centreline | | T8.5.1 (10 pts) |
| Front wing and its end plates: ahead of Ref A; wing **≤ 20.0 mm above the track** wherever it is wider than ±15 mm | | T8.5.2 (10 pts) |
| End plates: outside the minimum span, **≤ 10.0 mm wide**, **≤ 25.0 mm high** when outboard of the front wheels | | T8.5.3 (10 pts) |
| Front wing must resemble an F1 wing: leading and trailing edge across the full span | | T8.3 |
| Rigid: span may not change | | T8.4 |
| Span | **≥ 50.0 mm**: one segment of 50, or two segments of **≥ 25.0 mm** each if the nose splits it; measured along the shortest of leading edge, trailing edge, top and bottom | T8.6.1 (PP, 2 pts/mm) |
| Chord, throughout the existing span | **15.0-25.0 mm**; up to **3** elements, which must **overlap** in plan view | T8.6.2 (PP), App. v |
| Thickness, throughout the span at some point along the chord | **2.0-6.0 mm** | T8.6.3 (PP) |
| Clear air round the wing, across its minimum span | **≥ 5.0 mm** to any other part or the track (5 mm ball on a 2 mm rod) | T8.7 (5 pts) |
| Visible in front view | nothing may hide it | T8.8 (10 pts) |

- Note from T8.5.3 and App. i: the **finish gate's light beam is about 7 mm above the track**.
  The end plates (or whatever is frontmost at beam height) break the beam; the regulations say
  to design them to trigger it as early as possible. The frontmost point at ~7 mm height should
  therefore sit at the 40 mm overhang limit. Check the competition regulations for how the start
  is timed.
- **Generator:** the whole region ahead of Ref A is FREE inside these boxes: the ±15 mm × 25 mm
  nose box, and the ≤ 20 mm wing box beyond it, out to ≤ 40 mm ahead of Ref A. The nose may be
  organic and printed or foam. The wing must stay recognisably a wing (leading and trailing edge,
  chord, thickness), so it is best grown as organic aerofoil sections and planform rather than
  free blobs, then judged by the referee.

## 8. Rear wing and its support (T1.6.2, T9)

| Requirement | Limit | Rule |
|---|---|---|
| Rear wing and support entirely **behind Ref B** | | T9.4.1 (10 pts) |
| Overhang: Ref B to the extreme rear of the car | **≤ 40.0 mm** | T9.4.2 (5 pts) |
| Height behind Ref B | **≤ 65.0 mm** | T9.4.3 (5 pts) |
| Must resemble an F1 wing: leading and trailing edge across the span; rigid; any material | | T9.2, T9.3 |
| Span | **≥ 50.0 mm in one unbroken piece** | T9.5.1 (PP, 2 pts/mm) |
| Chord | **15.0-25.0 mm**, up to **2** elements, overlapping | T9.5.2 (PP) |
| Thickness | **2.0-6.0 mm** | T9.5.3 (PP) |
| Height deviation along the minimum span (top surface) | **≤ 15.0 mm** | T9.5.4 (PP) |
| Clear air round the wing | **≥ 5.0 mm** (5 mm ball) | T9.6 (5 pts) |
| Visible in front view | nothing may hide it | T9.7 (10 pts) |

- Note that the cartridge (≥ 5 mm out of the rear, visible all round) also sits behind the body:
  the rear wing support must not wrap round it (T5.6).
- **Generator:** region behind Ref B up to 40 mm and 65 mm high is FREE for the support
  (organic pylon, flush with the body where it meets it); the wing element itself grown as
  aerofoil sections with the T9.5 limits checked by the referee.

## 9. Ballast (T1.22, App. ix)
- **Only** in the container under the halo, reached through the helmet hole. That is the **only**
  place ballast may go. Any material (e.g. lead fishing weights).
- Container (App. ix drawing): a slot about 12.7 mm wide × 22.7 mm long, 6.35 mm deep below
  the pocket, cut with the same ball end. Capacity about 1.39 cm³ (repo `ballast.py`): about
  15.8 g of lead, about 25 g of tungsten.
- **Generator:** the container = FORCED AIR in the body (filled with ballast afterwards). Ballast
  makes up whatever the car is short of 48.0 g. Because it sits under the halo, the halo's x
  position also sets where the ballast mass sits, which moves the centre of mass.

## 10. Materials (what may be what)

| Part | Allowed material | Rule |
|---|---|---|
| Body | official Model Block only, one piece, behind Ref A | T1.3, T1.14, T4.1 |
| Nose cone, front wing, supports, end plates | any, including Model Block | T1.7, T8.4 |
| Rear wing and support | any | T9.3 |
| Wheels, wheel supports | any; may be bought | T1.8, T1.9 |
| Halo, helmet | any (shape fixed) | T1.21, T4.5 |
| Tether guides | any; may be bought | T1.10 |
| Ballast | any, only in the container | T1.22 |

The team's choice (from this conversation): foam wherever possible to save weight, plastic only
where foam can't do the job: thin sections, loaded parts (axle, stub root, wing and pylon),
places the ball end can't reach.

## 11. Penalty classes (why some rules matter more)
- **Performance** rules (yellow): breaking any one makes the car **ineligible for "Fastest Car"
  and "Best Engineered Car"** (T2.4.2), on top of the points. These include T3.3, T3.6, T4.2, T4.4.1,
  T5.6, T7.2-T7.11, T8.6, T8.7, T8.8, T9.5-T9.7.
- **Safety** rules (red) must pass for the car to race: T3.2, T4.4.4, T4.4.5, T5.1, T5.3-T5.5, T6.1-T6.3, T7.13.
- Proportional penalties (PP, T2.5.2) grow with every started mm or g outside the limit.
- So the generator must treat every Performance and Safety rule as a hard limit, not a cost.

---

## 12. The organic design space at a glance

| Region | What the generator does there |
|---|---|
| Everything above 65 mm, below 1.5 mm (except wheels), wider than ±42.5 mm | FORCED AIR |
| T7.9 keep-out boxes; wheel side-view, top-view and front-view (above 20 mm) sight lines | FORCED AIR |
| Halo sight lines (front, side, top), halo pocket, ballast container, chamber bore, cartridge protrusion and the space round it, tether line, claw rings, 5 mm clear air round each wing | FORCED AIR |
| Virtual cargo; 3 mm wall round the chamber; floor and walls under the halo pocket; decal patches; axle and bearing seats | FORCED SOLID |
| Halo + helmet, wheels, tether guides, cartridge | FIXED OBJECTS (position only) |
| Body: from Ref A back, inside the Model Block | FREE, organic, millable, one piece, foam |
| Nose: ahead of Ref A, ±15 mm wide, ≤ 25 mm high, ≤ 40 mm overhang | FREE, organic, any material |
| Front wing: ahead of Ref A, ≤ 20 mm high outboard of ±15 mm | FREE within aerofoil rules (T8.6) |
| Wheel supports: inside each axle's wheel cylinder | FREE, organic stub, flush with the body |
| Rear wing support and wing: behind Ref B, ≤ 40 mm, ≤ 65 mm high | FREE within aerofoil rules (T9.5) |

**Placements the search chooses (the only "numbers"):** wheelbase (120-140), front and rear
track (T7.2, T3.4), halo x (which also places the ballast), cargo x (between the axles),
chamber height (30-40) and angle (±3°), ride height (≥ 1.5 mm), and the pinned wheel size.

## 13. What the physics says matters most (repo measurements, model only, not yet track-tested)
- **Wheels are 64-75 % of the car's drag; the body 13-22 %** (`part4-simulation/assembly.py`,
  medium-mesh CFD with all parts). Shielding and shaping the flow round the wheels (T7.11's
  20 mm front-view allowance, wing end plates, the shape of the support stubs, rear-wheel
  fairings outside the T7.9 boxes) is where most of the time is.
- Race model: about **0.199 ms per mN of drag** and **7.51 ms per gram** of mass
  (`part2-simulation/PROOF.md`). Mass sits at the 48.0 g floor with ballast, so mass placement
  (centre of mass, wheel inertia) matters, not total mass.
- The 2-D search test (`research/organic_feasibility/`) found, on its own, a fairing wrapped
  round the rear wheel: the kind of feature this table allows and a parametric template wouldn't.
- Still placeholders: rolling and tether-guide friction, wheel spin-down, real print weights;
  no car has been built or timed.
