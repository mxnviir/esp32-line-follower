# Deliverable 3 — Track Run Firmware (one real run + competition)

Read `00_OVERVIEW.md`, then `01_SIMULATOR_SPEC.md` §3.7 (behaviours) first.

## 1. Purpose

The competition firmware. Built on `AllInOne.ino`, it:
1. Loads the parameters produced by the simulator (SAFE/FAST profiles) and by
   the calibration firmware (scales, deadband, `LINE_IS_HIGH`, height verdict).
2. Handles every track feature with the behaviours validated in the simulator.
3. Does a **short self-check on the real track** before the run.
4. **Records the entire run** to flash so the single real-track run can be
   analysed and replayed in the simulator afterwards.
5. Adapts within strict, safe limits during the run (speed only), never PD
   gains mid-run.

"Adapts perfectly from one run" is **not** a goal; it is impossible and must not
be claimed. The goal is: the run is safe, informative, and fully recorded.

## 2. Constraints

- Starts from current `AllInOne.ino`; keep all boot checks, reset log, safe mode,
  tuning commands, soft start.
- `HIL_MODE` from deliverable 1 must still work (same controller code path).
- Controller code must be identical to the simulator's port (B1 equivalence
  test must pass against this firmware).
- Remove temporary half-power scaling; scales come from the calibration report.
- `USE_BLUETOOTH` stays 0 unless the user confirms a 5 V supply that is not
  laptop USB.

## 3. Features

### 3.1 Profiles
- `SAFE` (default at boot) and `FAST`, both compiled in from the simulator export.
- Switch with serial `profile safe|fast`, or by holding BOOT (GPIO0) during the
  start blink (LED blinks 1× = SAFE, 2× = FAST to confirm).
- Active profile is printed at boot and stored in the run log.

### 3.2 Line-handling behaviours
Implement exactly the behaviours and parameter names of simulator §3.7: gap
ride-through, hard corner, crossing, hairpin/search with one reversal, speed
governor. Each logs an event when it activates.

### 3.3 Pre-run self-check (on the real track, ~5 s)
- Place the bot on a straight part of the line, centred. At start:
  1. Read sensors for 500 ms. Expect the centre sensor(s) on line and the
     outer ones off. If **all** sensors read line or **none** do → abort with
     LED code and serial message ("LINE_IS_HIGH wrong or bar too low/high").
  2. Optional `wiggle` check: rotate ±15° slowly; every enabled sensor must
     switch at least once. Sensors that never switch are reported, and the run
     refuses to start unless `force` is sent (user decision, logged).
- Result is stored in the run log header.

### 3.4 Speed adaptation (the only in-run adaptation)
- Base speed starts at profile base. If lost-line events occur, base drops 10%
  per event (floor 60% of profile base). Never increases during a run.
- PD gains are **not** changed during a run.

### 3.5 Run recording
- Ring buffer in RAM at the controller rate (200 Hz), each record:
  `t_ms(uint32), mask(uint8), pos(int16), corr(int16), L(int16), R(int16), mode(uint8), event(uint8)` = 16 bytes.
- 200 Hz × 16 B = 3.2 kB/s → at least 60 s in RAM (≥ 192 kB). If heap does not
  allow 60 s, downsample to 100 Hz and state it.
- On stop (line lost timeout, `stop`, or 120 s), write the buffer to a flash
  partition (LittleFS file `/run_<n>.bin`, keep last 3 runs). Do not write to
  flash while driving.
- Serial commands: `runs` (list), `dump <n>` (CSV to serial with header line
  `t_ms,mask,pos,corr,L,R,mode,event`), `erase` (asks `confirm`).
- Header includes firmware build date, profile, all parameters, calibration
  report, self-check result, reset reason.

### 3.6 Start and stop
- Start: after boot checks, LED blinks 2 s, then runs. Optional start on
  BOOT-button press (`start_mode button`).
- Stop: line lost beyond search, 120 s max run, or `stop`. Motors to 0, LED
  slow blink, log saved.

## 4. The one real run — checklist (put this in the README the agent writes)

Before:
1. Calibration report from deliverable 2 shows `overall=PASS` on the real surface.
2. Simulator SAFE profile exported and flashed. Boot log shows correct profile,
   scales, `LINE_IS_HIGH`.
3. Fresh battery; ESP32 on its 5 V supply (not laptop USB).

During:
4. Place centred on a straight. Self-check passes. Run **SAFE**.
5. Do not touch unless it leaves the track; note the place it failed (photo/video helps a lot).

After:
6. Connect USB, `dump` the run, send CSV + video/notes to the agent.
7. Agent imports into the simulator (deliverable 1 §3.11), fits the model,
   re-tunes, and produces the final profiles.

## 5. Acceptance benchmarks

### MUST
| ID | Benchmark | Evidence |
|---|---|---|
| T1 | Compiles (exit 0), boots, all checks pass, profile and parameters printed. | logs |
| T2 | Controller equivalence with simulator port: HIL test B1 re-run against this firmware, ≥ 99.9% identical steps. | B1 output |
| T3 | Every behaviour (gap, corner, crossing, hairpin, governor) passes its simulator track in HIL mode with this exact firmware, SAFE profile, 8/8 perturbed trials. | per-track table |
| T4 | Self-check aborts correctly in 3 forced cases: all sensors line, no sensor line, one sensor stuck (simulated via HIL or by covering a sensor). | logs |
| T5 | Recording: 60 s HIL run produces a log with ≥ 11 900 records at 200 Hz (or ≥ 5 950 at 100 Hz, stated), no gaps > 2 steps, CSV dump parses, and replaying it in the simulator reproduces L/R to within 1 PWM on ≥ 99.9% of records. | parser output |
| T6 | No flash writes while motors run (verify by code review + log timestamps of the write). | code ref + log |
| T7 | Speed adaptation never increases base and never goes below 60% of profile base (unit test with 20 crafted event sequences). | test output |
| T8 | Safety: motors stop within 20 ms of `stop`; brownout safe mode still works (B10-style test in HIL or real). | logs |
| T9 | Log survives power cycle; `runs` lists it; `dump` reprints identical CSV (checksum). | checksums |
| T10 | HIL_MODE 0 build: STBY behaviour, tuning commands, reset log unchanged from AllInOne (regression list). | logs |

### SHOULD
| ID | Benchmark |
|---|---|
| TS1 | Real robot, practice track (not the competition one): completes a mixed course with SAFE profile 3 times in a row. |
| TS2 | Run log + video of the real run lets the agent identify the failure point within ±0.5 s. |

## 6. Report template
```
Deliverable 3 report — <date>
Profiles: SAFE <values>, FAST <values> (from simulator export <date>)
Calibration used: <report block>
T1 … T10: PASS/FAIL/NOT RUN — evidence
TS1, TS2: …
What the robot is expected to handle / not handle:
Blocked / questions:
```
