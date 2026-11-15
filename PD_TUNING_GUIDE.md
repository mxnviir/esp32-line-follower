# PD Tuning Guide — ESP32 Line Follower

## How the steering works

Every 5 ms the bot reads the sensors and works out where the line is:

| Sensors seeing the line | Position (error) | Meaning |
|---|---|---|
| S3 only | 0 | centred |
| S3 + S4 | +500 | slightly right |
| S4 only | +1000 | far right |
| S2 + S3 | −500 | slightly left |
| S2 only | −1000 | far left |
| all of S2–S4 | 0 | crossing → straight |

(S1 is currently disabled, S5 is not fitted.)

It then calculates a steering correction:

```
correction = Kp × error  +  Kd × (error − previous error)
left  wheel = base + correction
right wheel = base − correction
```

- **Kp (proportional)** — how hard it steers back based on *how far* off-centre the line is.
- **Kd (derivative)** — how hard it reacts to *how fast* the line is moving. It damps overshoot and wobble.
- **Ki** — leave at **0**. It's rarely useful for line following.

### Rough feel for the numbers (base 150)

| Setting | Line at the far edge (error 1000) gives |
|---|---|
| Kp 0.05 | correction 50 → wheels 200 / 100 (gentle) |
| Kp 0.10 | correction 100 → wheels 250 / 50 (firm) |
| Kp 0.15 | correction 150 → wheels 255 / 0 (pivoting) |

Kd acts on *changes*. With digital sensors the error jumps in steps of 500,
so every time the line crosses onto another sensor:

| Kd | Kick on each 500-step |
|---|---|
| 0.1 | 50 |
| 0.3 | 150 |
| 0.6 (current default) | 300 → saturates a wheel for a moment |

**A large Kd on digital sensors makes the wheels jerk hard at every sensor
change.** That's one reason the wheels never look equal while following —
they're constantly being kicked one way and the other. Expect your best Kd to
be well below 0.6.

---

## Live tuning (no reflashing)

The firmware accepts commands over **USB serial** (115200 baud) or
**Bluetooth** (device name `LineFollower`). For tuning on the track, use
Bluetooth from your phone:

1. Android: install **"Serial Bluetooth Terminal"** (by Kai Morich).
   iPhone doesn't support classic Bluetooth serial — use USB with a long cable
   instead.
2. Pair with **LineFollower** in your phone's Bluetooth settings.
3. In the app: *Devices* → *Bluetooth Classic* → **LineFollower** → connect.
4. Type commands and press send:

| Command | Does |
|---|---|
| `show` | print current values |
| `kp 0.08` | set Kp |
| `kd 0.3` | set Kd |
| `ki 0` | set Ki |
| `base 150` | cruise speed (0–255) |
| `max 255` | speed cap (0–255) |
| `stop` / `go` | pause / resume the motors |
| `watch` | toggle live data: sensors, position, correction, wheel speeds |
| `reset` | back to the compiled defaults |

Values are **saved in flash** and survive power-off. Flashing a new build
resets them to the defaults — so when you've found good values, tell me and
I'll make them the defaults.

---

## Tuning procedure

Use a track with a straight section **and** curves. Change **one thing at a
time**, and test each value for a full lap.

### Step 1 — Start slow and simple
```
base 100
kd 0
ki 0
kp 0.05
```
Slow speed makes everything easier to see and less likely to fly off the track.

### Step 2 — Tune Kp (with Kd = 0)
Watch how the bot behaves on the straight and in curves:

| What you see | Do |
|---|---|
| Drifts off the line in curves, lazy steering | **raise Kp** (+0.02) |
| Follows, but wobbles gently side to side | about right — go to Step 3 |
| Wobbles hard / zig-zags, getting worse | **lower Kp** (−0.02) |

Raise Kp until it **just starts to wobble**, then note that value.

### Step 3 — Add Kd to calm the wobble
```
kd 0.05
```
Raise Kd in steps of **0.05**:

| What you see | Do |
|---|---|
| Still wobbles / overshoots after curves | **raise Kd** |
| Smooth and settles quickly | good — keep it |
| Twitchy, jerky, buzzing wheels, especially on straights | **Kd too high** — lower it |

### Step 4 — Speed up
Raise `base` in steps of 20 (100 → 120 → 140 …). At higher speed you'll
usually need **a bit more Kp and Kd**. Repeat Steps 2–3 briefly at each speed
until it starts losing the line in the sharpest curve, then go back one step.

### Step 5 — Protect the motors (optional)
Your N20s are 6 V motors on a 9.6 V battery. `max 160` keeps them near 6 V.
Lower `max` limits the hardest corrections, so check the sharpest curve still
works.

---

## Reading the `watch` output

```
x011x pos=  500 corr=  40.0 L= 190 R= 110
```
- `x011x` — S1…S5: `1` sees line, `0` doesn't, `x` disabled
- `pos` — line position (− left, + right)
- `corr` — steering correction
- `L` / `R` — commanded wheel speeds (before soft start)

On a **straight**, `pos` should sit at 0 most of the time and `L` ≈ `R`.
If `pos` keeps flipping between −1000 and +1000, the bot is zig-zagging:
lower Kp or raise Kd slightly.

## Quick fault table

| Symptom | Likely cause |
|---|---|
| Always steers the same way, even on a straight | line logic inverted for your track (`LINE_IS_HIGH`), sensor bar not centred, or a sensor stuck on |
| Loses the line in every curve | Kp too low or base too high |
| Zig-zags on straights | Kp too high or Kd too low |
| Jerky, wheels buzz/kick | Kd too high |
| Spins in place a lot | line lost too often → lower base, raise Kp |
