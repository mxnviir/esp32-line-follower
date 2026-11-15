# Deliverable 2 — Motor & IR Calibration Firmware

Read `00_OVERVIEW.md` first.

## 1. Purpose

A separate firmware (`Calibrate/Calibrate.ino`) used on the bench and on a sample
of the real track surface. It **measures** the motors and sensors, guides the
user through the physical adjustments the software cannot do (sensor height,
HW-201 trimmer), and prints a machine-readable calibration report that feeds
the simulator (deliverable 1) and the track firmware (deliverable 3).

It must never guess: every number it prints is measured, and every measurement
states how many samples it is based on.

## 2. Constraints

- Same pins, inversion flags and safety as `AllInOne.ino` (boot checks, brownout
  safe mode, STBY LOW until a motor step is explicitly started).
- Interaction over USB serial at 115200 (line commands). Must also be usable
  with LED-only feedback for steps marked LED.
- No Bluetooth (USB power brownout risk, see overview).
- Every motor step: soft start, maximum duration 10 s, `stop` aborts instantly,
  and the user must type `go` (or press BOOT button GPIO0) to start it.

## 3. Calibration steps

Run in order via a menu (`menu`, `1`..`7`, `report`). Each step prints a header,
what the user must do, live readings, and a PASS/FAIL with the reason.

### Step 1 — Power check
- Read reset reason and reset log (reuse from AllInOne).
- Ask user which supply is connected. Run both motors to PWM 255 for 1 s
  (lifted). If a brownout occurs, record it and FAIL with: "ESP32 supply too
  weak for motors — power the motors from the battery / ESP32 from a power bank".
- PASS criterion: no brownout during 3 consecutive 1 s full-power pulses.

### Step 2 — Motor direction
- Each wheel forward 0.5 s, then backward, at PWM 150. User answers `y`/`n`
  ("did the LEFT wheel move FORWARD?"). Output the correct `INVERT_LEFT` /
  `INVERT_RIGHT`.
- PASS: user confirmed all four movements.

### Step 3 — Motor deadband
- Lifted. For each wheel ramp PWM from 0 up in steps of 5, hold 300 ms each;
  user types `m` the moment the wheel starts turning. Repeat 3 times.
- Report: deadband per wheel (mean and spread of 3 trials).
- PASS: spread ≤ 15 PWM; else FAIL "inconsistent — check gearbox friction".

### Step 4 — Motor speed and matching
- Lifted, tape marker on each wheel. Both wheels at PWM 128 for 10 s, then 255
  for 10 s. User types counted turns per wheel per run (`l 12`, `r 12.5`).
  Repeat each speed twice.
- Report: rpm per wheel per PWM, left/right ratio, recommended `LEFT_SCALE` /
  `RIGHT_SCALE` (faster wheel scaled down to match).
- PASS: ratio within 0.9–1.1. Else WARN and recommend scale values; FAIL if
  outside 0.7–1.3 ("mechanical problem — fix before running").

### Step 5 — On-floor drive check
- On the real surface, no line. Drive straight 1.5 s at PWM 150 with the
  Step 4 scales. User measures sideways drift at 1 m (mm) and types it.
- PASS: drift ≤ 50 mm over 1 m. Report recommended scale trim.

### Step 6 — Sensor height and contrast (the critical one)
- Requires a sample of the real line on the real background.
- Live display at 10 Hz: per-sensor state, and a per-sensor tally.
- Procedure:
  1. User sets the sensor bar at a starting height, types `h <mm>`.
  2. User slowly slides the bot sideways across the line, back and forth, 5
     times, then types `done`.
  3. Firmware counts, per sensor: transitions REFLECT→DARK and DARK→REFLECT,
     whether every sensor went DARK at least once per pass (over the line) and
     REFLECT between passes (over background), and **stuck events** (a sensor
     that stayed DARK while both neighbours had returned to REFLECT, or vice
     versa = ghosting).
  4. Verdict per sensor: CLEAN / GHOSTING / NEVER-DARK / NEVER-REFLECT, and an
     overall recommendation: "raise bar 2 mm", "lower bar 2 mm", "line material
     reflects IR — change it", or "OK at this height".
  5. Repeat at other heights; firmware keeps a table height → verdicts.
- Also detects which logic level the line produces and prints the required
  `LINE_IS_HIGH`.
- PASS: all enabled sensors CLEAN at one height, with 0 stuck events in 5
  passes.

### Step 7 — HW-201 matching and sensor timing
- User slides the bar slowly across the line at the chosen height.
- Firmware timestamps each sensor's switch. Using the known sequence (S1→S5 or
  S5→S1) it computes, relative to neighbours, whether S5 switches early/late
  compared with the BFD sensors' pattern, and prints "turn HW-201 trimmer
  clockwise / anticlockwise / OK".
- PASS: S5 switch timing deviation ≤ 30% of the mean neighbour interval over 5 passes.

## 4. Calibration report

`report` prints a block that can be pasted directly to the agent:
```
CALIBRATION REPORT v1
date_ms_uptime=...
supply_ok=1 brownouts_in_test=0
invert_left=1 invert_right=0
deadband_left=42(±4,n=3) deadband_right=40(±3,n=3)
rpm128_left=...(n=2) rpm128_right=... rpm255_left=... rpm255_right=...
scale_left=1.00 scale_right=0.97
drift_mm_per_m=...
line_is_high=1
height_mm=12 sensors=S1:CLEAN S2:CLEAN S3:CLEAN S4:CLEAN S5:CLEAN stuck_events=0
height_table=8:S2 GHOST|10:CLEAN|12:CLEAN|14:S5 NEVER-REFLECT
hw201_timing=OK(dev=12%)
overall=PASS|FAIL <reasons>
```
- Also saved in NVS so it survives power-off (`report` reprints it).
- Values entered by the user are marked `(user)`; values measured by the
  firmware are marked with their sample count `(n=..)`.

## 5. Acceptance benchmarks

### MUST
| ID | Benchmark | Evidence |
|---|---|---|
| C1 | Compiles with arduino-cli (exit 0) and boots with all existing checks passing. | compiler + boot log |
| C2 | Motors never move without an explicit `go`/BOOT press; `stop` halts within 20 ms (measure via timestamps). | log with timestamps |
| C3 | Brownout during Step 1 is detected and reported (test by running on laptop USB with motors on USB, if the user agrees; otherwise NOT RUN with reason). | log |
| C4 | Step 6 detects ghosting: demonstrated on glossy tape (or by deliberately setting the bar too low) → at least one sensor reported GHOSTING; on a good line → all CLEAN. Both runs logged. | two logs |
| C5 | Step 6 never reports CLEAN for a sensor that has a stuck event in that height trial (unit-test the classifier with ≥ 10 crafted transition sequences, including edge cases). | test output |
| C6 | Report contains every field listed in §4; any field not measured prints `NA`, never a default number. | report text |
| C7 | `LINE_IS_HIGH` recommendation matches the measured polarity in both a normal and an inverted test (e.g. black tape on white, then white strip on black). | logs |
| C8 | Report survives a power cycle (NVS) and reprints identically. | before/after |
| C9 | Regression: `AllInOne.ino` still compiles and is unchanged except intentionally shared helpers. | diff + compile |

### SHOULD
| ID | Benchmark |
|---|---|
| CS1 | Whole procedure doable in ≤ 25 minutes by the user (time a dry run). |
| CS2 | LED-only mode for Steps 6–7 (LED blinks pattern for CLEAN/GHOSTING) when no laptop is available. |

## 6. Report template
```
Deliverable 2 report — <date>
C1 … C9: PASS/FAIL/NOT RUN — evidence
CS1, CS2: …
Things the user must still do physically:
Blocked / questions:
```
