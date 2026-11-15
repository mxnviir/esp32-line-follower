# Deliverable 1 — Digital Twin Simulator + USB Hardware-in-the-Loop

Read `00_OVERVIEW.md` first. All robot numbers come from there.

## 1. Purpose

A browser-based simulator that:
1. Runs a **bit-exact port** of the firmware's control logic on a simulated robot
   driving over simulated tracks (SIM mode).
2. Can instead drive the **real ESP32 running the real firmware**: the page sends
   simulated sensor readings over USB, the ESP32 returns its motor commands, the
   page moves the virtual robot (HIL mode).
3. Auto-tunes Kp, Kd, base speed and the line-handling parameters across a
   library of track features and outputs a SAFE and a FAST profile.
4. Accepts real run logs and fits the model to them (calibration).

It does **not** simulate IR physics (wavelength, materials). It simulates what
each sensor outputs, using parameters measured by deliverable 2.

## 2. Form and constraints

- One self-contained HTML file (inline JS/CSS), no build step, no server.
  Libraries only from cdnjs, pinned version. Plain canvas 2D is sufficient.
- Works offline in Chrome/Edge desktop. HIL mode uses the Web Serial API
  (Chrome/Edge only); SIM mode must work in any modern browser.
- The simulation core (`physics`, `sensors`, `controller`, `tracks`, `tuner`)
  must be plain functions with no DOM access, so they can be run headless in
  Node for tests (`node sim_tests.js` loads the same code).
- Deterministic: given the same seed, parameters and track, two runs produce
  identical results.

## 3. Model

### 3.1 Units and timing
- SI internally (m, s, rad). UI shows mm and ms.
- Physics step `dt_phys = 1 ms`. Controller step exactly `5 ms` (as firmware
  `LOOP_PERIOD_MS`). Sensor sampling happens at the controller step.

### 3.2 Robot geometry (all from overview §2, editable in UI)
- Differential drive; wheel separation `W`, wheel radius `r`.
- Sensor row perpendicular to heading at distance `L` ahead of axle.
- Sensor i lateral offset `y_i` (S1 most negative = left). Default from spacing.
  Each sensor can be individually enabled, offset forward/back, and moved.

### 3.3 Motors
For each wheel:
- Input: signed PWM `u` in [-255, 255] after firmware scaling/inversion.
- Deadband: |u| < `deadband` → target speed 0.
- Target wheel angular speed `w* = sign(u) * w_max * (|u| - deadband)/(255 - deadband)`.
- First-order lag: `dw/dt = (w* - w)/tau`, `tau` default 0.08 s (ASSUMED).
- Per-wheel multipliers: `gain` (default 1.0) to model mismatched gears or
  slipping gearbox; `slip_prob` per step (default 0) to model the old fault.
- `w_max` from overview RPM at PWM 255, scaled by `V_batt/9.6`.
- Optional traction limit: wheel ground speed cannot change faster than
  `a_max` (default 3 m/s², ASSUMED). Excess = wheel slip.

### 3.4 Power (optional but required for benchmark B10)
- Battery `V_batt` with internal resistance `R_int` (default 0.5 ohm, ASSUMED).
- Motor current `I = (V_applied - k_e*w)/R_coil`, `R_coil` default 15 ohm (MEASURED range 15–25).
- ESP32 supply modelled separately: `SUPPLY = USB_LAPTOP | POWER_BANK | SHARED_BATTERY`.
  In `USB_LAPTOP` with motors fed from USB, a combined current over 0.5 A drops
  ESP voltage; below 2.6 V for >1 ms triggers a simulated brownout reset that
  runs the firmware's real reset/safe-mode logic. Default `POWER_BANK` (no sag).

### 3.5 Sensors
For each enabled sensor at each controller step:
1. Compute `coverage` in [0,1] = fraction of a circular spot (radius `spot_r`,
   default 3 mm, grows with height: `spot_r = 0.3 * height`, ASSUMED) covered by
   line paint. Sample ≥ 32 points in the spot (fixed pattern, not random).
2. `reflect = (1 - coverage) * R_bg + coverage * R_line`, defaults `R_bg = 1.0`,
   `R_line = 0.1` (per-surface editable; e.g. glossy tape `R_line = 0.7`).
3. Per-sensor `gain_i` (default 1) and `offset_i` (default 0):
   `s = gain_i * reflect + offset_i + noise` (Gaussian, `sigma` default 0.02, seeded RNG).
4. Schmitt trigger with thresholds `T_low`, `T_high` (defaults 0.35, 0.55):
   state becomes REFLECT if `s > T_high`, DARK if `s < T_low`, else keeps
   previous state (this is the ghosting).
5. Electrical output: REFLECT → LOW, DARK → HIGH (MEASURED polarity).
6. The firmware's `LINE_IS_HIGH` flag then decides what "line" means,
   exactly as in firmware.
7. HW-201 (S5) has its own `gain`, `offset`, thresholds (comparator with
   smaller hysteresis, default 0.02).

### 3.6 Controller (bit-exact port)
Port, line by line, from `AllInOne/AllInOne.ino` at the commit/date you start:
`readLine`, weights, all-on rule, right-edge rule, PID with float math, integral
clamp ±10000, `BASE_SPEED`, `MAX_SPEED`, `SEARCH_SPEED`, lost-line spin,
creep, `LOST_TIMEOUT_MS`, soft start slew (`MOTOR_SLEW` per call), `LEFT_SCALE`,
`RIGHT_SCALE`, inversion flags, `paused`.

Add, behind toggles (default OFF so the port stays identical), the new line
handling that deliverable 3 will implement (§3.7). Use the same parameter names
as deliverable 3.

### 3.7 New line-handling behaviours (designed and validated here first)
| Behaviour | Trigger | Action | Parameters |
|---|---|---|---|
| Gap ride-through | line lost while last |error| ≤ `gap_err_max` | keep last motor command (straight) for `gap_ms`, then normal lost logic | `gap_ms` (default 250), `gap_err_max` (500) |
| Hard corner | outermost enabled sensor on, opposite half off, for ≥ `corner_confirm_ms` | pivot toward it at `pivot_speed` until a centre sensor (S2–S4) sees the line | `corner_confirm_ms` (10), `pivot_speed` (160) |
| Crossing | ≥ 4 enabled sensors on simultaneously | drive straight at base for `cross_ms`, ignore sensors | `cross_ms` (120) |
| Hairpin / search | line lost after gap time | spin toward last side; after `search_ms` reverse direction once; then stop | `search_ms` (1200) |
| Speed governor | |error| large | `base_eff = base - k_slow * |e|/1000 * base` | `k_slow` (0.4) |

### 3.8 Tracks
- Track = list of line segments with width, plus optional gaps. Build from
  primitives: `straight(len)`, `arc(radius, angle)`, `corner(angle)` (sharp
  vertex), `gap(len)`, `dashes(len, on, off)`, `crossing()`, `zigzag(n, amp, pitch)`.
- Required library (each a named preset):
  1. `oval` — straights + 150 mm radius turns
  2. `s_bends` — alternating 100 mm radius arcs
  3. `corner90_left`, `corner90_right`
  4. `acute60_left`, `acute60_right` (120° turn)
  5. `hairpin` — 180° turn at the smallest radius from overview
  6. `crossing` — figure-eight with a 90° crossing
  7. `dashed` — 30 mm on / 20 mm off for 600 mm
  8. `gap_max` — single gap of the max gap length from overview
  9. `zigzag` — 6 × 45° direction changes
  10. `t_junction` (only if the user confirms T-junctions exist)
  11. `competition_mix` — all features above in one closed course
- Line width and smallest radius come from overview §2.6.
- Users can import a track as JSON (same primitive list) and export it.

### 3.9 Scoring a run
Per run report:
- `completed` (bool): robot centre reached the finish within `timeout`.
- `lap_time` (s).
- `max_dev` (mm): max distance of sensor-row centre from line centreline,
  excluding gap/crossing zones.
- `mean_abs_dev` (mm).
- `lost_events`, `lost_time_total` (ms), `brownouts`.
- `off_track` (bool): sensor row centre farther than `off_track_mm` (default 40)
  from any line for > 1 s.
Score for tuning: `completed` first (all tracks must complete), then minimise
`sum(lap_time) + 0.02 * sum(mean_abs_dev_mm)`.

### 3.10 Auto-tuner
- Search space: Kp [0.01, 0.30], Kd [0, 1.0], base [60, 255], and the §3.7
  parameters within sensible bounds. Speeds respect `MAX_SPEED`.
- Method: coarse grid then local refinement (e.g. coordinate descent or
  Nelder–Mead), ≥ 500 evaluations per profile.
- Robustness: each candidate is evaluated with **randomised perturbations** of
  ±15% motor gain per wheel, ±20% sensor gains, ±3 mm sensor height, noise
  ×2, battery 8.4–10.8 V, start offset ±5 mm/±5°. At least 8 perturbed
  trials per track per candidate.
- Outputs:
  - **SAFE** profile: completes 100% of perturbed trials on all tracks, then fastest.
  - **FAST** profile: completes ≥ 95% of perturbed trials, minimises lap time.
- Export: a C header snippet with exact firmware variable names (copy button)
  and a JSON with all parameters + the git/date of the firmware port.

### 3.11 Calibration from real logs
- Import the run log produced by deliverable 3 (CSV, format defined there).
- Replay the logged sensor states into the controller port and check the
  controller's computed motor commands match the logged ones (port check).
- Fit motor `w_max`, `tau`, per-wheel `gain`, sensor `T_low/T_high/gain` so the
  simulated run on the recorded track reproduces the log. Report fit error.

### 3.12 HIL mode (USB)
Firmware side (add to `AllInOne.ino` behind `#define HIL_MODE 0`, default 0):
- When 1: STBY stays LOW always (motors physically off); sensors are not read
  from pins; instead the firmware reads frames from Serial and replies.
- Protocol at 921600 baud (fall back to 115200 if unreliable — report which):
  - PC → ESP: `S<mask_hex2>\n` per 5 ms step (bit i = sensor i electrical
    level HIGH). Example `S1A\n`.
  - ESP → PC: `M<left>,<right>,<mode>\n` with the signed PWM values exactly as
    passed to `driveOne` (after scaling/inversion), and mode index.
  - The ESP runs **one controller step per received S frame** (lock-step), so
    timing is driven by the simulator and is deterministic.
- Everything else (boot checks, reset log, tuning commands) unchanged. Boot
  output is allowed before the first S frame; the page ignores lines not
  starting with `M`.
Page side: Connect button (Web Serial), shows link status, round-trip time,
frame drops.

### 3.13 UI
- Canvas: track, robot body, wheels, sensor spots coloured by state, trail.
- Controls: track preset, run/pause/step/reset, speed ×0.25–×20, seed.
- Parameter panels: geometry, motors, sensors (per sensor), power, controller,
  behaviours. All parameters show their source tag (MEASURED/ASSUMED/FITTED).
- Live charts: line position, correction, L/R PWM, sensor states over time.
- Results table per track; tuner progress and best profiles.
- Works at 1280×720 and at phone width (controls stack).

## 4. Acceptance benchmarks

Report every item as PASS/FAIL/NOT RUN with evidence (numbers, logs, screenshots).

### MUST
| ID | Benchmark | Evidence required |
|---|---|---|
| B1 | **Port equivalence.** Feed 10 000 recorded or random sensor-mask sequences (seeded) into the JS controller and into the real firmware in HIL mode. Motor outputs identical (integer PWM) on ≥ 99.9% of steps; any mismatch explained (e.g. float rounding) and ≤ 1 PWM unit. | mismatch count, max diff, sample of mismatches |
| B2 | **Determinism.** Same seed + params → identical run report twice (bitwise for all numbers). | two reports |
| B3 | **Kinematics.** Equal PWM 255 both wheels, no lag: straight distance in 1 s equals `pi*D*rpm/60` within 1%. PWM +X/-X: rotation rate equals `2*v/W` within 1%. | computed vs simulated |
| B4 | **Sensor geometry.** Moving the robot laterally across a straight 18 mm line in 0.5 mm steps, each sensor's coverage reaches 0.5 within ±0.5 mm of its configured lateral offset ± line half-width. | table |
| B5 | **Hysteresis.** With `T_low=0.35, T_high=0.55` and `R_line` set so line reflect = 0.45, a sensor that enters from background stays REFLECT over the line (ghosting reproduced); with `R_line=0.1` it switches. | two plots/logs |
| B6 | **Current firmware behaviour reproduced.** With current defaults (Kp 0.08, Kd 0.6, base 150, new behaviours OFF), simulated `dashed` track shows the robot entering lost-spin at the first gap (as the real firmware would). Documented as a known weakness. | run report |
| B7 | **Track library.** All 11 presets (10 if no T-junctions) load, render, and have correct geometry: total length and turn angles within 1% of spec. | table |
| B8 | **SAFE profile.** Completes 100% of ≥ 8 perturbed trials on every required track. | per-track pass counts |
| B9 | **FAST profile.** ≥ 95% perturbed completion overall, and mean lap time on `competition_mix` at least 15% lower than SAFE. If not achievable, report FAIL with the best numbers — do not relax the benchmark. | numbers |
| B10 | **Brownout model.** In `USB_LAPTOP` supply with motors on USB, full-power start triggers a simulated brownout and, on two in a row, the firmware's safe mode. In `POWER_BANK` no brownout. | logs |
| B11 | **HIL link.** With real ESP32 connected: ≥ 60 s run with 0 dropped/garbled frames at the chosen baud, lock-step confirmed (step counter matches), motors physically did not move (STBY LOW confirmed by `watch` or pin readback). | page stats + serial log |
| B12 | **HIL vs SIM agreement.** Same track/seed: HIL run report equals SIM run report (lap time within 1 controller step, same lost events). | both reports |
| B13 | **Export correctness.** Exported header compiles into `AllInOne.ino` with `arduino-cli compile` exit 0, and `show` on the flashed board prints exactly the exported values. | compiler output + serial |
| B14 | **Headless tests.** `node sim_tests.js` runs B1(JS side), B2, B3, B4, B5, B7 and exits 0. | console output |
| B15 | **Regression.** `AllInOne.ino` with `HIL_MODE 0` compiles, boots, all checks pass, behaviour identical to before (motor test, tuning commands). | serial boot log |
| B16 | **No fake data.** Every displayed number is computed by the simulator or imported from a log; any placeholder is labelled. Every parameter shows MEASURED/ASSUMED/FITTED. | screenshot |

### SHOULD
| ID | Benchmark |
|---|---|
| S1 | Simulates ≥ 50× real time headless on a laptop (one `competition_mix` lap). |
| S2 | Log calibration (§3.11) reduces lateral-deviation RMS error vs the real log by ≥ 50% compared with default parameters. |
| S3 | Page usable at 400 px width. |

## 5. Report template
```
Deliverable 1 report — <date>
Firmware port source: AllInOne.ino <date/hash>
Parameters: MEASURED <list>, ASSUMED <list>, FITTED <list>
B1 … B16: PASS/FAIL/NOT RUN — evidence
S1 … S3: …
SAFE profile: <values>   FAST profile: <values>
Known weaknesses / differences from real robot:
Blocked / questions:
```
