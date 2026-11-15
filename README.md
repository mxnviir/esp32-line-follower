# ESP32 Line Follower

Firmware, tools and notes for a competition line-following robot built on a
classic ESP32 DevKit, a TB6612FNG motor driver, two N20 gear motors, a
BFD-1000-style 5-channel IR sensor board and an extra HW-201 IR module.

The main firmware is [`AllInOne/AllInOne.ino`](AllInOne/AllInOne.ino). Every
setting you are likely to change is in one block at the top of that file.

---

## Contents

1. [Hardware](#1-hardware)
2. [Repository layout](#2-repository-layout)
3. [Building and flashing](#3-building-and-flashing)
4. [How the firmware works](#4-how-the-firmware-works)
5. [Settings reference](#5-settings-reference)
6. [Serial commands](#6-serial-commands)
7. [Track learning and speed planning](#7-track-learning-and-speed-planning)
8. [Simulation and test tools](#8-simulation-and-test-tools)
9. [Tuning](#9-tuning)
10. [Known problems and their causes](#10-known-problems-and-their-causes)
11. [Project history](#11-project-history)

---

## 1. Hardware

### Controller
| Item | Value |
|---|---|
| Board | Classic ESP32 DevKit (ESP32-D0WD-V3), CP2102 USB-serial |
| Working board | MAC `c4:d8:d5:78:5a:84` |
| Dead boards (flash chip not responding) | MAC `b0:cb:d8:ee:90:44`, and an ESP32-D0WDQ6 rev 1.1 |
| Power | 5 V USB power bank on the micro-USB port |

### Pins
| Function | GPIO | Notes |
|---|---|---|
| S1 (far left, BFD) | 15 | |
| S2 (BFD) | 33 | |
| S3 (centre, BFD) | 32 | |
| S4 (BFD) | 35 | input-only pin |
| S5 (far right, HW-201) | 34 | input-only pin; HW-201 powered from 3V3 |
| PWMA / AIN1 / AIN2 (left motor A) | 18 / 19 / 21 | |
| PWMB / BIN1 / BIN2 (right motor B) | 23 / 22 / 5 | |
| STBY (driver enable) | 25 | LOW = motors off |
| Status LED | 2 | on-board blue LED |
| BOOT button | 0 | not used by the race firmware |

### Sensors
- **BFD board (S1–S4):** TCRT5000 sensors with a 74HC14 Schmitt trigger. Its
  own S5 is missing (pads bridged). Powered from 3.3 V. Clean 0 V / 3.3 V
  outputs. On the track (glossy black electrical tape on white tile) it reads
  the tape as **reflective**, so its output is **LOW over the line**.
- **HW-201 (S5):** LM393 module, 55 mm right of S4, LEDs tilted about 31°
  outward, 46 mm above the floor. Its output is **HIGH over the line**.
- Sensor faces are 41 mm above the floor. That is too high for these sensors
  (they work best at 5–15 mm) and causes ghosting; see section 10.

### Drive
- TB6612FNG. **VM is currently fed from the ESP32's 5V/VIN pin**, so motor
  current flows through the micro-USB cable. This causes brownouts; see
  section 10.
- N20 gear motors, coil 15–25 Ω (so 6 V motors). Motor A is wired reversed and
  is inverted in software.
- Wheels 33 mm diameter, 163 mm apart. Sensor row 185 mm ahead of the axle.

---

## 2. Repository layout

| Path | What it is |
|---|---|
| [`AllInOne/AllInOne.ino`](AllInOne/AllInOne.ino) | **Main race firmware.** Self-checks, reset log, line engine, live tuning, track-map support |
| `AllInOne/sketch.yaml` | Build options (40 MHz flash) used by `arduino-cli` |
| `AllInOne/track_map.h` | *(generated, optional)* speed plan from a learning run; not in the repo until you make one |
| [`TrackLearn/TrackLearn.ino`](TrackLearn/TrackLearn.ino) | **Learning firmware.** Generated from `AllInOne.ino` with `TRACK_LEARN_MODE 1`. Do not edit it directly |
| [`tools/make_learn_firmware.py`](tools/make_learn_firmware.py) | Regenerates `TrackLearn` from `AllInOne` |
| [`tools/export_track.py`](tools/export_track.py) | Reads the learned map from the robot and writes `AllInOne/track_map.h` |
| `tools/engine_sim*.py`, `tools/run2.py`, `tools/pivot_test.py` | Offline Python simulation of the line engine (see section 8) |
| [`WheelSpeedTest/`](WheelSpeedTest/WheelSpeedTest.ino) | Both motors at equal half and full power, to compare wheel speeds |
| [`SensorMonitor/`](SensorMonitor/SensorMonitor.ino) | Prints the five sensor-pin voltages for the Arduino Serial Plotter; motors off |
| [`Diagnostics/`](Diagnostics/Diagnostics.ino) | Older stand-alone board check (RAM, flash, motor pins, reset log) |
| [`HardwareTest/`](HardwareTest/HardwareTest.ino) | Older test: LED blinks per sensor detection, motors run back and forth |
| [`LineFollower/`](LineFollower/LineFollower.ino) | The first, simple line follower (historical) |
| [`PD_TUNING_GUIDE.md`](PD_TUNING_GUIDE.md) | Earlier tuning guide (written when Bluetooth was on); section 9 here is current |
| [`specs/`](specs/) | Specifications written for build agents (simulator, calibration firmware, track-run firmware) with pass/fail benchmarks |

---

## 3. Building and flashing

Install [arduino-cli](https://arduino.github.io/arduino-cli/) and the ESP32 core:

```bash
arduino-cli config add board_manager.additional_urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32
```

On Linux, give yourself access to the serial port (once):

```bash
sudo usermod -aG dialout $USER
```

Then log out and back in. Until then, after every replug: `sudo chmod 666 /dev/ttyUSB0`.

Compile and flash the race firmware (the 40 MHz flash setting comes from
`sketch.yaml`):

```bash
arduino-cli compile AllInOne
arduino-cli upload --fqbn esp32:esp32:esp32:FlashFreq=40,UploadSpeed=115200 -p /dev/ttyUSB0 AllInOne
```

- **Use 40 MHz flash.** At the default 80 MHz this board got stuck in a boot
  loop with `csum err` on a weak supply.
- **Use 115200 upload speed.** 460800 sometimes failed. If an upload fails,
  run it again: a failed upload leaves the previous firmware running.
- After changing `AllInOne.ino`, run `python3 tools/make_learn_firmware.py` to
  keep `TrackLearn` in sync.

---

## 4. How the firmware works

### Boot
1. Motor driver held in standby (STBY LOW).
2. Self-checks: chip report, RAM pattern test, flash read-back, motor pin
   read-back test. A failure stops the motors and blinks an error code
   (2 = RAM, 3 = flash, 4 = pins).
3. Reset log: the reason for every restart and how long the previous run
   lasted are kept in flash (32 entries) and printed at boot.
4. Two brownouts in a row: it keeps racing at 70% power instead of stopping.
5. After an unexpected restart (brownout, crash, watchdog) it **resumes
   immediately**. After a normal power-on it waits 2 s (LED blinks).
6. The motor driver is enabled (STBY HIGH) and line following starts.

There is **no motor test at boot**; the robot races straight away.

### Every 5 ms
1. **Dead reckoning.** From the wheel commands it estimates how far the robot
   drove and turned (no encoders, so this is an estimate).
2. **Sensors.** Each sensor is debounced (2 identical readings). Each sensor's
   position on the floor comes from the measured geometry, including the
   HW-201's tilt. Steering weights: S1 −2000, S2 −1000, S3 0, S4 +1000,
   S5 +4756 (1000 per sensor pitch).
3. **Classification:**

   | Letter | Meaning | Action |
   |---|---|---|
   | `L` | Normal line | PD steering, slowing in curves |
   | `J` | Line on both sides, wider than one line | Junction: straight through, centre sensors only, for 40 mm |
   | `<` / `>` | Line across one whole side | Corner: steer hard that way |
   | `-` | Nothing seen | Lost-line logic below |

4. **Lost line**, in this order:
   1. **Turn memory:** if an outer sensor (S1 or S5) touched the line within
      80 mm, even for a single raw reading, pivot toward that side. S5 only
      counts if the line was already right of centre, and S5 alone is ignored
      while the line was left of S4 (the HW-201 sees dark tile grout as line).
   2. **Corner memory:** a corner was seen within 80 mm, so pivot toward it.
   3. **Gap:** the line vanished near the centre running straight, so drive
      straight for up to 60 mm.
   4. **Prediction:** steer to where the dead-reckoning model says the line
      now is (pivot if it's beyond the outer sensors).
   5. **Sweep:** left/right sweeps that double in length. It never stops on its own.
5. **Ending a pivot:** keep turning until a **centre** sensor (S2–S4) has the
   line (slower once only an outer sensor sees it), then short-brake 60 ms,
   then cap the steering at ±60 for 60 mm. This stops overshoot after 90° turns.
6. **Motor output:** soft start (10 per step), deadband compensation (any
   non-zero command becomes at least 70 PWM so wheels never stall), power
   scale, and inversion. Wheels coast through zero while driving and brake only
   on an explicit stop.

---

## 5. Settings reference

All of these are at the top of `AllInOne.ino`. Tags: **measured** (from the
robot), **assumed** (typical value, please measure), **live** (also changeable
over serial).

### Build options
| Setting | Value | Meaning |
|---|---|---|
| `USE_BLUETOOTH` | 0 | Bluetooth tuning. Starting the radio browned out the board on USB power |
| `DEBUG_SERIAL` | 0 | 1 = print engine data continuously |
| `TRACK_LEARN_MODE` | 0 | 1 = learning firmware (set by `TrackLearn`) |
| `USE_TRACK_MAP` | 1 | Use `track_map.h` if it exists |
| `LOW_CURRENT_MODE` | 1 | Gentler ramps and slower pivots while motors run off USB power |

### Track
| Setting | Value | Meaning |
|---|---|---|
| `LINE_IS_HIGH` | false | BFD board: LOW = line (it sees the glossy tape as reflective) |
| `HW201_LINE_IS_HIGH` | true | HW-201: HIGH = line |
| `DEFAULT_LINE_WIDTH_MM` | 18 | Line width (live: `width`); used to tell junctions and corners from a normal line |

### Sensors
| Setting | Value | Meaning |
|---|---|---|
| `USE_S1`, `USE_S5` | 1, 1 | Enable the far-left and far-right sensors |
| `SENSOR_PINS_CFG` | 15, 33, 32, 35, 34 | GPIO for S1..S5 |
| `BFD_PITCH_MM` | 22 (**assumed**) | BFD sensor spacing. Every position depends on it, so please measure it |
| `SENSOR_HEIGHT_MM` | 41 | BFD sensor height |
| `HW201_RIGHT_MM` | 55 | HW-201 distance right of S4 |
| `HW201_RAISE_MM` | 5 | HW-201 height above the BFD sensors (46 mm total) |
| `HW201_TILT_DEG` | 31 | HW-201 tilt outward, measured from a photo (±5°) |
| `SENSOR_FILTER_SAMPLES` | 2 | Readings needed before a sensor change counts |

### Robot geometry
| Setting | Value |
|---|---|
| `WHEEL_DIAMETER_MM` | 33 |
| `WHEEL_BASE_MM` | 163 |
| `SENSOR_AHEAD_MM` | 185 |

### Motors
| Setting | Value | Meaning |
|---|---|---|
| `INVERT_LEFT` / `INVERT_RIGHT` | true / false | Motor A is wired reversed |
| `LEFT_SCALE` / `RIGHT_SCALE` | 0.5 / 0.5 | **Half power** while motors run off USB. Set to 1.0 with a proper motor supply |
| `MOTOR_RPM_AT_FULL` | 300 (**assumed**) | Used for dead reckoning and the speed plan |
| `MOTOR_DEADBAND` | 40 (**assumed**) | PWM below which a wheel doesn't turn (model only) |
| `MOTOR_MIN_PWM` | 70 (**assumed**) | Every non-zero command is lifted to at least this |
| `MOTOR_SLEW` | 10 | Max PWM change per 5 ms |
| `MOTOR_REVERSE_SLEW` | 40 | Faster ramp when a wheel changes direction (unused in low-current mode) |
| `LOW_CURRENT_SEARCH_SPEED` | 100 | Pivot speed in low-current mode |

### Speeds and steering
| Setting | Value | Meaning |
|---|---|---|
| `DEFAULT_BASE_SPEED` | 150 | Cruise command (live: `base`) |
| `DEFAULT_MAX_SPEED` | 255 | Command cap (live: `max`). `160` keeps 6 V motors near 6 V on 9.6 V |
| `DEFAULT_KP` / `KI` / `KD` | 0.08 / 0 / 0.6 | PD gains (live: `kp`, `ki`, `kd`) |
| `CURVE_SLOWDOWN` | 0.3 | Up to 30% slower when the error is large |

### Line engine
| Setting | Value | Change it if… |
|---|---|---|
| `SEARCH_SPEED` | 140 | Pivot speed outside low-current mode |
| `GAP_MAX_MM` | 60 | Your gaps are longer |
| `GAP_CENTER_MM` / `GAP_MAX_ANGLE_DEG` | 10 / 10 | It treats turns as gaps (lower) or gaps as turns (raise) |
| `JUNCTION_HOLD_MM` | 40 | It turns into side branches after a junction (raise) |
| `CORNER_MEMORY_MM` | 80 | It misses corners it just saw (raise) |
| `SIDE_MEMORY_MM` | 80 | It drives straight through turns (raise) or turns wrongly at gaps (lower) |
| `S5_TRUST_MM` | 5.5 | S5 only counts as a turn hint when the line was this far right of centre (stops tile grout fooling it) |
| `PIVOT_FIND_FACTOR` | 0.6 | It overshoots after turns (lower) |
| `PIVOT_BRAKE_MS` | 60 | It keeps rotating after a turn (raise) |
| `POST_TURN_MM` / `POST_TURN_MAX_CORR` | 60 / 60 | Gentle steering after a pivot |
| `CORNER_INNER_FACTOR` | −1.0 | −1 = pivot in place. Arcs failed tight hairpins in simulation |
| `PIVOT_MARGIN_MM` | 10 | How far beyond the outer sensor a predicted line must be to pivot |
| `SEARCH_MAX_TURN_DEG` / `PREDICT_MAX_MM` | 200 / 300 | When prediction gives up and sweeping starts |
| `SWEEP_FIRST_MS` | 400 | First sweep length (then doubles) |
| `LOST_SPEED_FACTOR` | 0.8 | Speed while predicting |
| `RECOVER_SPEED_FACTOR` / `RECOVER_MM` | 0.85 / 30 | Speed after finding the line again |

### Track map
| Setting | Value | Meaning |
|---|---|---|
| `LEARN_BASE_SPEED` | 110 | Speed of the learning run |
| `MAP_STEP_MM` | 20 | One map sample every 20 mm |
| `LEARN_END_LOST_MS` | 3000 | Line gone this long ends the learning run |
| `MAP_LOOKAHEAD_MM` | 120 | Plan speed this far ahead |
| `MAP_MIN_BASE` / `MAP_MAX_BASE` | 90 / 220 | Limits on planned speed |
| `MAP_SYNC_WINDOW_MM` | 300 | A junction/corner must be this close to the map, or the map is dropped |

### Boot and safety
| Setting | Value |
|---|---|
| `START_DELAY_MS` | 2000 (normal power-on only) |
| `RESUME_AFTER_CRASH` | true |
| `BROWNOUT_POWER_FACTOR` | 0.7 |

---

## 6. Serial commands

Serial Monitor at **115200** baud, line ending **Newline**:

| Command | What it does |
|---|---|
| `show` | Print current Kp, Ki, Kd, base, max, width |
| `kp 0.08` / `kd 0.3` / `ki 0` | Set gains |
| `base 150` / `max 255` | Cruise speed / cap (0–255) |
| `width 18` | Line width in mm |
| `stop` / `go` | Pause / resume |
| `watch` | Live data on/off |
| `reset` | Back to compiled defaults |
| `log` / `clear` | Show / clear the reset log |
| `map` | Track map status |
| `export` | Print the learned map |
| `save` | End a learning run and save the map |

Tuned values are saved in flash and survive power-off. **Flashing a new build
resets them** and clears the reset log.

`watch` output:
```
01100 L follow   lineX= -11.0mm ang=  3.2deg L= 112 R= 165
```
Sensors S1..S5, what it sees, what it's doing, where it thinks the line is,
which way the line runs, and the wheel commands (before scaling).

---

## 7. Track learning and speed planning

1. `python3 tools/make_learn_firmware.py`, then flash `TrackLearn`.
2. Put the robot at the start. It drives the course once at `LEARN_BASE_SPEED`,
   recording distance, heading and features every 20 mm.
3. When the line has been gone for 3 s (end of course), it stops and saves the
   map to flash. The LED blinks slowly. `save` ends it early.
4. Connect to the PC and run:
   ```bash
   python3 tools/export_track.py /dev/ttyUSB0
   ```
   It reads the map without resetting the robot, saves `tracks/track_<date>.csv`
   and writes `AllInOne/track_map.h`.
5. Compile and flash `AllInOne`. It plans speed 120 mm ahead (fast on
   straights, braking before curves, corners and junctions), re-syncs at
   junctions and corners, and drops the map if something doesn't match.

The saved map survives reflashing. Without wheel encoders the distance is
estimated, so the plan is approximate. Learn and race at the same power setting.

---

## 8. Simulation and test tools

`tools/engine_sim.py` is a Python port of the line engine's equations, used to
test changes offline before flashing. `tools/run2.py` runs it over a set of
tracks (straight, dashed, crossing, 90° corners, curves, hairpins) at half and
full power. `tools/engine_sim_lag.py` adds motor lag and deadband;
`tools/pivot_test.py` compares versions of the pivot logic.

```bash
cd tools && python3 run2.py
```

**Limits:** the simulation assumes motors deliver what they're told, perfect
power, and idealised sensors. It did **not** reproduce several real problems
(brownouts, the robot driving straight through turns), so a pass in simulation
is not proof the real robot will behave.

---

## 9. Tuning

Fix hardware problems first (power, loose motor wire, sensor ghosting):
tuning around them is wasted effort.

1. Check sensors with `watch`: each should go `1` over the tape and `0` over
   the tile, cleanly.
2. Start slow: `base 100`, `kd 0`, `ki 0`, `kp 0.05`.
3. Raise `kp` by 0.02 until it just starts to wobble.
4. Add `kd` in steps of 0.05 until the wobble settles. Twitchy = too much.
5. If it shows `J` on a plain line, raise `width`. If it goes straight at
   corners, lower it.
6. Raise `base` in steps of 20, re-checking Kp and Kd.
7. On a proper motor supply, set `LEFT_SCALE`/`RIGHT_SCALE` to 1.0,
   `LOW_CURRENT_MODE` to 0, and re-tune.

### Sensor height
- **Raise** if every sensor reads the same over tape and tile, or it ghosts
  (a sensor stays in its last state after the tape has left).
- **Lower** if nothing switches, one line lights 3+ sensors, or it reports
  false junctions.
- Aim for the middle of the range where all sensors switch cleanly. For these
  sensors that's usually 5–15 mm; 41 mm is too high.
- Tilting the bar 10–15° reduces glare from glossy tape. Matte (gaffer) tape
  avoids the problem. A black skirt and emitter shrouds help too.

---

## 10. Known problems and their causes

| Problem | Cause | Fix |
|---|---|---|
| **Brownouts, restarts mid-run, `csum err` boot loops** | TB6612 VM is fed from the ESP32's 5V pin, so motor surges sag the supply through the micro-USB cable and the board's diode. A multimeter can't see these millisecond dips | Give VM its own supply (battery to VM only, or a second power bank cable), disconnect VM from the ESP32 5V pin, join grounds, add 470–1000 µF across VM/GND. Then set scales to 1.0 and `LOW_CURRENT_MODE` 0 |
| **Two dead ESP32 boards** (flash ID `ff/ffff`) | Earlier, 9.6 V was fed into VIN, giving 3.8 V on the 3V3 rail (over the 3.6 V limit) | Never put more than about 5–6 V into VIN |
| **Sensor ghosting / inconsistent switching** | Sensors 41 mm high; glossy electrical tape reflects IR | Lower to about 10 mm, tilt the bar, matte tape |
| **Left motor intermittent** | Loose wire or connector (works after a power cycle, fails after lifting) | Check AO1/AO2, the motor tab solder joints and the D18/D19/D21 jumpers |
| **Robot didn't turn at corners** | The outer sensor only touched the line for one reading, which the flicker filter dropped; the loss was then treated as a gap | Fixed: raw outer-sensor touches are remembered (`SIDE_MEMORY_MM`) |
| **Left 90° turns sometimes turned right** | The HW-201 (S5) reads dark tile grout as line; the BFD board can't see grout. A grout hit under S5 looked like a recent right-side touch, or pulled the robot hard right | Fixed: S5 is only believed when the line was already right of centre. In simulation: 6/24 → 0/24 failures |
| **Overshoot after 90° turns** | The pivot ended at the first outer sensor while still rotating | Fixed: pivot until a centre sensor sees the line, brake, gentle steering after |
| **Wheel stalled on turns** | Half power made the inner wheel's PWM too low to turn | Fixed: deadband compensation (`MOTOR_MIN_PWM`) |

---

## 11. Project history

1. Wrote a simple PD line follower; S5 disabled because it was broken.
2. Set up arduino-cli and flashing; fixed serial-port permissions.
3. Moved sensors to D15/D33/D32/D35/D34. Found GPIO5 was also BIN2.
4. Motors didn't move → traced to power wiring. Two ESP32s died (flash) after
   9.6 V on VIN gave 3.8 V on 3V3. A third board is healthy.
5. Added diagnostics, a persistent reset log, brownout safe mode, motor test,
   and live serial tuning (Bluetooth later disabled: it browned out on USB).
6. Identified the sensor board as BFD-1000-style with a 74HC14; fixed the
   inverted logic and tuned sensor height, and found glossy tape reads as reflective.
7. Added the HW-201 as S5 and computed its floor position from its measured
   tilt (31°, from a photo) and height.
8. Rebuilt the line engine around the measured geometry: dead-reckoning
   prediction, gap/junction/corner handling, never-stop behaviour.
9. Fixed stalls with deadband compensation. Added track learning and a
   speed-planning tool.
10. Made the firmware race-ready: removed the boot motor test, resume after a
    crash, faster reversing, 40 MHz flash. Added low-current mode for USB power.
11. Fixed the robot driving straight through turns (outer-sensor memory) and
    the overshoot after 90° turns (pivot exit with braking).
12. Fixed left turns sometimes going right: tile grout under the HW-201.

The `specs/` folder describes a fuller digital twin, calibration firmware and
track-run firmware with strict benchmarks; those are designs, not yet built.
