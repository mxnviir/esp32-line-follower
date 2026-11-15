# Line Follower Project — Overview for Build Agents

Read this file completely before opening any other spec. It is the single source
of truth for facts about the robot. If another spec disagrees with this file,
this file wins. If this file and the real hardware disagree, **the hardware
wins** and you must report the disagreement instead of silently "fixing" it.

## 0. Rules for every agent (non-negotiable)

1. **No invented facts.** Every number you use is either (a) listed in section 2
   as MEASURED, (b) listed in section 2 as ASSUMED with its default, or (c)
   measured by you and reported with how you measured it. Never present an
   ASSUMED value as measured.
2. **No claimed results you did not observe.** "Compiles" means you ran the
   compiler and it exited 0. "Works" means you ran it and saw the output. Paste
   the actual output (or the relevant lines) in your report. If you did not run
   something, say "NOT RUN".
3. **No silent scope changes.** If a requirement is impossible or ambiguous,
   stop and write it in the report under "Blocked / questions". Do not
   substitute a different behaviour and call it done.
4. **Benchmarks are pass/fail.** Each spec has an Acceptance section. A task is
   successful only if **every** benchmark marked MUST passes, with evidence. Report
   each benchmark as PASS / FAIL / NOT RUN with the evidence next to it. Partial
   success is reported as FAIL with details, never rounded up.
5. **Do not touch hardware safety settings** (brownout detection, motor standby
   on boot, safe-mode on repeated brownout) unless a spec explicitly says so.
6. **Keep the existing firmware working.** The current firmware
   (`AllInOne/AllInOne.ino`) must still compile and behave identically after
   your changes unless the spec says otherwise. Run the regression checks.

## 1. The three deliverables

| # | Spec file | What | When used |
|---|---|---|---|
| 1 | `01_SIMULATOR_SPEC.md` | Browser digital twin + USB hardware-in-the-loop mode | Today, to design and pre-tune |
| 2 | `02_CALIBRATION_FIRMWARE_SPEC.md` | Bench/practice firmware that measures motors and IR sensors and outputs numbers | Tomorrow, before driving |
| 3 | `03_TRACK_RUN_FIRMWARE_SPEC.md` | Competition firmware that self-calibrates, handles all track features, and logs the single real-track run | Tomorrow's one real run + competition |

Build order: 1 → 2 → 3. Deliverable 3 reuses the control logic validated in 1
and the measured parameters produced by 2.

## 2. Robot facts

Status legend: **MEASURED** (confirmed on the real robot), **ASSUMED** (default
until the user measures it), **UNKNOWN** (must be asked or measured).

### 2.1 Controller
| Item | Value | Status |
|---|---|---|
| MCU | ESP32-D0WD-V3 rev 3.1, classic ESP32 DevKit (30/38 pin), CP2102 USB-serial | MEASURED |
| Good board MAC | `c4:d8:d5:78:5a:84` | MEASURED |
| Dead boards (flash ID ff/ffff, do not use) | `b0:cb:d8:ee:90:44`, one ESP32-D0WDQ6 rev1.1 | MEASURED |
| Toolchain | arduino-cli 1.6.0, core esp32:esp32 3.3.12, FQBN `esp32:esp32:esp32` | MEASURED |
| Serial port | `/dev/ttyUSB0`, needs `sudo chmod 666` after each replug | MEASURED |
| Upload | 460800 baud sometimes fails; 115200 reliable | MEASURED |
| ESP32 power | Must be 5 V on VIN or USB. 9.6 V on VIN gave 3.8 V on 3V3 and likely killed two boards | MEASURED |
| Bluetooth | Starting BT on laptop USB power caused brownout + boot loop | MEASURED |

### 2.2 Pins
| Function | GPIO | Notes |
|---|---|---|
| S1 (far left) | 15 | BFD board, strapping pin (harmless) |
| S2 | 33 | BFD board |
| S3 (centre) | 32 | BFD board |
| S4 | 35 | BFD board, input-only |
| S5 (far right) | 34 | **HW-201 module**, input-only, OUT->34, VCC 3V3 |
| PWMA / AIN1 / AIN2 (left motor A) | 18 / 19 / 21 | |
| PWMB / BIN1 / BIN2 (right motor B) | 23 / 22 / 5 | |
| STBY | 25 | LOW = driver off |
| Status LED | 2 | on-board blue |

### 2.3 Sensors
| Item | Value | Status |
|---|---|---|
| Line sensor board | BFD-1000-style 5-channel TCRT5000 board with 74HC14 Schmitt trigger; its own S5 is missing (pads bridged) | MEASURED |
| Board supply | 3.3 V, outputs clean 0.01–0.05 V / 3.3 V | MEASURED |
| Output polarity | Reflective surface: LED ON, output LOW. Black/no reflection: LED OFF, output HIGH | MEASURED |
| Hysteresis | Present (74HC14). Causes "ghosting" when black is not dark enough in IR or sensors are too low | MEASURED |
| Trimmer R17 | Does not change line sensors; probably sets the front proximity sensor | MEASURED (effect) / ASSUMED (purpose) |
| HW-201 | LM393 module, active LOW on reflection, own trimmer, 3.3–5 V | MEASURED (wiring) |
| Glossy black electrical tape, some black plastics | Reflect IR like white | MEASURED |
| Thin white paper on dark desk | Reads dark (IR passes through) | MEASURED |
| Sensor spacing S1–S4 | 22 mm | ASSUMED |
| S4 to S5 (HW-201) spacing | 22 mm | ASSUMED |
| Sensor height above floor | 10 mm | ASSUMED |
| Sensors in one straight row | yes | ASSUMED |
| Sensor row ahead of wheel axle | 60 mm | ASSUMED |
| Front proximity sensor + limit switch on BFD board | Exist; pins not wired | MEASURED (exist) |

### 2.4 Drive
| Item | Value | Status |
|---|---|---|
| Driver | TB6612FNG, VM from 9.6 V battery, VCC from ESP32 3V3 | MEASURED |
| Motors | N20 gearmotors, coil 15–25 ohm, so about 6 V rated | MEASURED (ohm) / ASSUMED (rating) |
| Gear ratio | Same on both sides now (left gearbox repaired) | MEASURED |
| Motor wiring | Motor A needs firmware inversion (`INVERT_LEFT=true`), B normal | MEASURED |
| Equal PWM on both wheels gives equal speed (lifted) | yes | MEASURED |
| Wheel diameter | 34 mm | ASSUMED |
| Wheel separation (centre to centre) | 100 mm | ASSUMED |
| Wheel RPM at PWM 255, 9.6 V | 300 rpm | ASSUMED |
| Motor deadband (PWM below which wheel does not turn) | 40 | ASSUMED |
| Caster / skid position | rear | ASSUMED |
| Robot mass | 250 g | ASSUMED |

### 2.5 Current firmware (`AllInOne/AllInOne.ino`)
- Boot: chip report, RAM test, flash read test, motor pin readback test, NVS
  reset log (32 entries, survives power loss), safe mode (motors off, LED blinks
  code) on test failure or 2 consecutive brownouts, sensor report, motor test.
- Line position: weighted average, weights S1..S5 = -2000, -1000, 0, +1000, +2000.
  All enabled sensors on => position 0. If S1 on and S5 off and only S4 sees the
  line => +1500.
- PID every 5 ms: `corr = Kp*e + Ki*sum(e) + Kd*(e - e_prev)`; left = base+corr,
  right = base-corr. Defaults Kp 0.08, Ki 0, Kd 0.6, base 150, max 255.
- Line lost: spin toward last error sign at 140; if last error 0, creep at
  base/2; stop after 3000 ms.
- Soft start: max PWM change 10 per call.
- Live tuning over USB serial (Bluetooth compiled out): `show`, `kp`, `kd`,
  `ki`, `base`, `max`, `stop`, `go`, `watch`, `reset`, `log`, `clear`. Values
  stored in NVS namespace `tune`, cleared on new build.
- Current flags: `USE_S1 1`, `USE_S5 1`, `LINE_IS_HIGH false` (**probably wrong
  for black line on light floor — confirm with user**), `INVERT_LEFT true`,
  `LEFT_SCALE = RIGHT_SCALE = 0.5` (temporary, for USB power), `USE_BLUETOOTH 0`.

### 2.6 Track (competition)
| Item | Value | Status |
|---|---|---|
| Line colour / background | black line on light background | ASSUMED |
| Line width | 18 mm | ASSUMED |
| Features | straights, curves, 90 deg corners, acute corners, hairpins, crossings, dashed lines / gaps, S-bends, zig-zags | ASSUMED (user said "all of that") |
| Smallest radius | 50 mm | ASSUMED |
| Max gap length | 50 mm | ASSUMED |
| Practice runs on the real track before competition | **exactly one** | MEASURED (user statement) |

## 3. Questions the user must answer (agents: do not guess these)

Answers replace the ASSUMED values above. Record the answer and the date.

1. Track: black line on light floor, or reflective line on dark? (decides `LINE_IS_HIGH`)
2. Line width (mm) and line material (electrical tape, printed, painted?)
3. Background material (white board, banner, floor tiles?)
4. Which features appear: 90 deg corners, acute (<90 deg) corners, hairpins,
   crossings, T-junctions, dashed lines/gaps (max gap length?), obstacles,
   start/finish markers, side markers?
5. Smallest curve radius in the rules?
6. Is it timed (speed matters) or pass/fail (completion matters)?
7. Is there a rule about touching/restarting, and how long is one run?
8. Sensor spacing S1–S4 and S4–S5, centre to centre of the black receivers (mm)
9. Distance from wheel axle to sensor row (mm)
10. Distance between wheels, centre to centre (mm)
11. Wheel diameter (mm)
12. Sensor height above floor (mm), with the bot standing on its wheels
13. Wheel turns in 10 s at PWM 128 and PWM 255 (from the wheel speed test), lifted
14. Robot mass (g) and where the caster/skid is
15. Which browser will run the simulator? (USB mode requires Chrome or Edge)
16. During the one real run: can a laptop be connected / nearby? Can you touch
    the robot between laps?
17. Will the competition allow a phone over Bluetooth for tuning? (Bluetooth
    needs a solid 5 V supply for the ESP32, not laptop USB)

## 4. What the user must do (in order)

### Today
1. Answer section 3, especially 1, 4, 6, 8–13.
2. Run the wheel speed test (already flashable) and count wheel turns.
3. Decide how the ESP32 is powered on the robot: power bank on USB, or a
   5 V buck module from the battery. **Not** 9.6 V on VIN.

### Tomorrow, before the real run
1. Flash deliverable 2 and follow its on-screen steps on a **sample of the real
   track surface and line** (or the most similar material you have):
   sensor height, HW-201 trimmer, motor check. About 20 minutes.
2. Send the agent the calibration report it prints.
3. Flash deliverable 3 with the parameters from 1 and from the simulator.

### The one real run
1. Follow the run checklist in `03_TRACK_RUN_FIRMWARE_SPEC.md`.
2. Afterwards, connect USB and send the agent the full run log (`dump`).
3. The agent re-tunes the simulator with that log and produces the final setting.

## 5. Brutal honesty: what this can and cannot do

- **The simulator cannot tune IR sensor height or materials.** Only a real
  surface can. Deliverable 2 does that.
- **One real run is not enough to "perfectly" tune anything.** It is enough to
  (a) calibrate the sensors on the real surface, (b) check motor speed on the
  real floor, (c) record where the robot fails. Expect the final setting to be
  "safe and reliable", not "optimal".
- **Simulated PD values are a starting point.** Expect real values within
  roughly x0.5 to x2 of simulated ones until the simulator is calibrated with
  real logs.
- **The biggest risks are hardware**: power (brownouts, 9.6 V on VIN), sensor
  ghosting on glossy tape, loose gearbox. Software cannot fix those.
- **A slower run that finishes beats a fast run that doesn't.** Deliverable 3
  must ship with a SAFE profile as the default.
