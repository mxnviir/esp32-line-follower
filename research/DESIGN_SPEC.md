# Our car's design definition: the few numbers, the organic rest, and the wheel supports

What the generator builds, what it may change, and what each part must do. This is our design,
not the regulations (those are in `CAR_SPEC.md`; every rule there is enforced by the referee,
`part5-simulation/legality.py`). Loads and part details come from the team's own support
(`part4-simulation/beam_support.py`, calibrated on the support that already races).

---

## 1. The principle

The whole car's outer shape is **one organic surface**, grown by the evolved network (a CPPN)
inside the legal space. Nothing on it is a dimension someone types in. That one surface is then
**cut into the parts we make**: the foam body, the nose cone, the two wheel supports and the rear
wing support. Because every part is a piece of the same surface, every join is flush by
construction.

The only numbers are **where the fixed objects sit**. Everything else is organic or worked out.

---

## 2. The only parameters

### 2a. Pinned once (decided, not searched)

| Item | Value | Why |
|---|---|---|
| Wheel diameter | smallest legal + margin (about 28.1 mm) | less frontal area, mass and spin inertia |
| Wheel contact width | 13.0 front / 17.0 rear + margin | narrowest legal |
| Ride height (lowest point of anything but the wheels) | 1.5 mm + margin | lowest legal |
| Bearing | 3 × 6 × 2.5 mm (MR63), one per wheel | the team's; sets the axle diameter (3.0 mm) |
| Total mass | 48.0 g + small margin, made up with ballast | heavier is slower (about 7.5 ms per g) |

### 2b. Searched (the genome's only numbers)

| # | Placement | What moves with it |
|---|---|---|
| 1 | **Halo distance from the back of the car** | halo pocket, ballast container (so where the ballast mass sits), number-decal space ahead of it, the halo sight lines |
| 2 | **Rear axle distance from the back** | rear wheels, Ref B (and the rear wing zone behind it), rear support cylinder, rear tether guide window |
| 3 | **Wheelbase** (120-140 mm) | front axle, Ref A (and the whole nose and front-wing zone), front support cylinder, front tether guide window |

Optional, only if the first results show they matter: front and rear track width, cartridge
height (30-40 mm) and angle (±3°), virtual cargo position between the axles.

Everything the generator draws is anchored to these placements (distances to the wheels, halo,
cargo and chamber are inputs to the network), so the same organic genome stays meaningful when a
placement changes.

---

## 3. What is organic, what is forced, what is worked out

| Kind | Examples | Who decides |
|---|---|---|
| **Organic** | body surface, nose, support stubs, rear wing pylon, wheel edge profile and hub face | the evolved network |
| **Forced solid** | virtual cargo, 3 mm wall round the chamber, floor and walls under the halo pocket, decal patches, axle and its shoulder, flat mounting face | the rules and the support design (section 4) |
| **Forced air** | everything the rules keep clear (chamber, pocket, wheel clear-air boxes, sight lines, claw rings, wing clear air) | the rules |
| **Worked out** | where the parts are cut apart, tenons and pockets, which material each region is, wall thicknesses for strength, ballast amount | the generator, by fixed rules (sections 4-6) |

---

## 4. Wheel support system (one printed part per axle)

### 4a. What it is

One SLS print per axle, wheel to wheel, with the axles printed in. Five zones, from the inside out:

| Zone | What it is | Organic or fixed |
|---|---|---|
| **Tenon (keel)** | the hidden part that slots into a pocket milled in the body; carries the load into the foam | worked out from the cut (4c) |
| **Flush skin** | where the part shows on the outside of the body: its surface *is* the body's organic surface, so the join is invisible | organic (it is the body's surface) |
| **Stub** | the protrusion that grows out of the body's surface towards the wheel; small, durable, smoothly blended into the skin (no corner at the root) | organic shape, thickened if the strength check needs it |
| **Flat face** | a flat face square to the axle at the end of the stub, facing the wheel's inner side; the bearing's inner race sits against it | fixed shape; its position follows the wheel |
| **Axle** | 3.0 mm journal from the flat face out through the bearing to the wheel's outer face, printed in the same part; a hubcap pressed on its end holds the wheel | fixed shape (bearing size) |

### 4b. Requirements

| Requirement | Value | Source |
|---|---|---|
| Whole part inside the cylinder through both wheels of its axle | radius = wheel radius, along the axle line | T7.12.1 |
| Nothing below 1.5 mm off the track | | T3.7 |
| Claw clearance at each wheel's inner corner | 1.5 mm ring kept clear | T7.13 |
| Strength, normal racing loads | 3 N radial at the bearing + 1.2 N sideways at the tyre contact, PA12 at 44 MPa, safety factor 2 | team's support, `beam_support.py` |
| Stiffness | ≤ 0.15 mm sag at the bearing, so all four wheels stay flat on the track | `beam_support.py`, T7.6 |
| Wheel hang test | 100 g hung from each wheel | T7.13 |
| Launch and finish-catch loads | about 1 N per wheel each | `beam_support.py` |
| Wheels spin freely on a 3° slope | bearing seated square on the flat face | T7.8 |
| Printable | no wall under the printer's minimum (0.7 mm today, `component_contract.MIN_WALL_MM`) | Part 4 |
| Removable as a spare | separate part, identical spares | T3.9 |
| Lightest that passes | every wall at the print minimum unless the strength check asks for more | team rule |

### 4c. How the generator makes it

1. **Grow the whole car's surface** (one organic field).
2. **Force the fixed pieces solid:** the axle and its shoulder, the flat face at each wheel. The
   network shapes the material *around* them, so the stub always reaches the face.
3. **Mark the support region:** the part of the car inside this axle's wheel cylinder, outboard of
   a seam that keeps the foam body one piece around the cargo and chamber. Inside the region, the
   surface becomes the support's flush skin and stub; outside it, it stays foam.
4. **Cut the joint from the seam:** push the seam face into the body to make the tenon; grow the
   matching pocket until the 6.35 mm ball end can mill it; shrink the tenon by the glue gap; keep
   clear of the cargo, chamber wall, halo pocket and ballast container.
5. **Check strength and stiffness** with a beam check along the stub and axle under the loads in
   4b. If it fails, thicken the stub's thinnest section (the organic shape keeps its form, only
   grows) until it passes. Never thinner than the print minimum.
6. **Write the part** as one closed solid with its mass and centre of mass for the race model.

The air sees the flush skin and the stub, so they are what evolution shapes. The tenon, the
pocket and the wall thicknesses are worked out, never searched.

---

## 5. Nose cone, rear wing support and wings

| Part | Organic | Fixed / forced | Joint to the body | Material |
|---|---|---|---|---|
| **Nose cone** (everything ahead of Ref A) | its whole shape inside the nose box, flowing straight on from the body's surface at Ref A | carries the front wing; front-wing mount solid | tenon into the body through Ref A, cut from the seam like 4c | foam where it can be, plastic where it's thin or loaded |
| **Front wing** | section shape and planform, grown as aerofoils (1-3 elements) | leading and trailing edge across the span; chord, thickness, height limits checked | one part with the nose cone | plastic |
| **Rear wing support (pylon)** | its whole shape behind Ref B, flowing flush out of the body's top or tail surface | must not wrap round the cartridge | tenon into the body, cut from the seam | plastic (loaded) |
| **Rear wing** | section shape and planform as aerofoils (1-2 elements) | single unbroken span, chord, thickness, height deviation checked | one part with the pylon | plastic |

---

## 6. Materials: worked out region by region

Default is **foam** (0.163 g/cm³, milled). A region becomes **plastic** (SLS PA12, 1.01 g/cm³)
only if one of these is true:

1. it is thinner than foam can be milled or survive (3.0 mm milled wall);
2. the strength check says foam would fail there (axle, stub root, wing, pylon);
3. the ball end can't reach it (undercut);
4. it is a wing element.

The body behind Ref A is foam by rule. Ballast (lead or tungsten, in the container under the
halo) makes up the rest to 48.0 g, so every gram saved in the parts becomes a lower centre of
mass or a smaller body, not lost time.

---

## 7. What every generated car comes with

- One closed solid per made part: `machined_body`, `printed_front_assembly` (nose + front wing),
  `printed_support_front`, `printed_support_rear`, `printed_rwing`, wheels ×4, hubcaps.
- A mass report: mass and centre of mass per part, ballast needed, wheel spin inertia.
- The referee's verdict on every rule.
- The CFD half-car with every part as its own surface, for drag and lift per part.

---

## 8. Open decisions

1. Track width: pin it at the narrowest legal wheel gap, or search it (section 2b optional)?
2. Is 3.0 mm PA12 enough for the axle under the loads above, or does it need a sleeve or a bigger
   bearing? The strength check in 4c answers this per car.
3. Rear wing in PA12 (as above) or PLA (as Part 4 has it today)?
4. Hubcap: flush closed disc (aero) or open (lighter)? It can be organic too, inside the wheel.
