// GENERATED from AllInOne/AllInOne.ino by tools/make_learn_firmware.py.
// Do not edit: change AllInOne.ino and run the script again.
#define TRACK_LEARN_MODE 1

/*
 * ESP32 Line Follower — all-in-one firmware
 *
 * Boot sequence:
 *   1. Diagnostics: chip report, RAM test, flash read test, motor pin self-test
 *   2. Reset log (kept in flash, survives power loss) + brownout safety check
 *   3. Sensor report (no motor test: the robot starts racing directly)
 *   4. Line following on S1-S5 (S5 = HW-201 module at the far right)
 *
 * Line engine:
 *   - Each sensor is debounced, and its position on the floor comes from the
 *     measured geometry (including the HW-201's tilt).
 *   - While the line is seen, the firmware tracks where the line is and which
 *     way it runs relative to the robot.
 *   - When no sensor sees it, the robot keeps a model of the line and moves it
 *     using how far the wheels have driven and turned (dead reckoning), so it
 *     steers to where the line actually is now, not just where it was.
 *   - Gaps/dashes: drives straight for a set distance. Junctions/crossings:
 *     goes straight through. 90-degree corners: pivots toward the branch.
 *   - Never stops on its own; if the prediction fails it sweeps side to side.
 *
 * If a diagnostic fails, the motors stay off and the blue LED blinks an error
 * code (see ERROR CODES below). After two brownouts in a row it keeps racing
 * at reduced power. After an unexpected restart mid-run it resumes at once.
 *
 * Live tuning over USB serial (115200) or Bluetooth ("LineFollower", use a
 * phone app like "Serial Bluetooth Terminal"). One command per line:
 *   show            print current values        kp 0.08   set Kp
 *   kd 0.6          set Kd                      ki 0      set Ki
 *   base 150        cruise speed (0-255)        max 255   speed cap (0-255)
 *   width 18        line width in mm            watch     toggle live data
 *   stop / go       pause / resume the motors   reset     back to defaults
 *   log / clear     reset log (USB only)
 * Tuned values are saved in flash and survive power-off until the next flash.
 *
 * BUILD: flash at 40 MHz (FQBN esp32:esp32:esp32:FlashFreq=40, set in
 * sketch.yaml). At the default 80 MHz this board misread its flash on a weak
 * supply (boot loop with "csum err"); 40 MHz removed those errors.
 */

#include <Arduino.h>
#include <esp_system.h>
#include <esp_chip_info.h>
#include <driver/gpio.h>
#include <Preferences.h>
#include <LittleFS.h>

// ############################################################################
// ##                                                                        ##
// ##                  USER SETTINGS: everything you may change              ##
// ##                                                                        ##
// ## Tags: (measured) = from the real robot, (assumed) = a typical value     ##
// ## until you measure it, (live) = can also be changed over serial.         ##
// ############################################################################

// ---- Build options ----------------------------------------------------------

// Bluetooth tuning. Starting the radio draws a current spike that browns out
// the board on weak USB power: keep 0 for USB testing, 1 on a proper 5 V supply.
#define USE_BLUETOOTH 0
#define DEBUG_SERIAL  0   // 1 = print sensor/engine data while following

// ---- Track ------------------------------------------------------------------

// Track: black electrical tape on white tile (measured).
// Which output level means "line", set separately per sensor type:
//   false = output LOW over the line, true = output HIGH over the line.
// BFD board (S1-S4): reads the glossy tape as reflective, so LOW = line.
const bool  LINE_IS_HIGH          = false;  // (measured) BFD board S1-S4
// HW-201 (S5): LED OFF over the tape, so its output is HIGH over the line.
const bool  HW201_LINE_IS_HIGH    = true;   // (measured) HW-201 S5
const float DEFAULT_LINE_WIDTH_MM = 18.0f;  // (measured, live: "width <mm>")

// ---- Sensors ----------------------------------------------------------------

#define USE_S1 1  // far-left BFD sensor
#define USE_S5 1  // S5 = separate HW-201 module at the far right

// Pins, left to right: S1 S2 S3 S4 S5
const uint8_t SENSOR_PINS_CFG[5] = {15, 33, 32, 35, 34};

const float BFD_PITCH_MM     = 22.0f;  // (assumed) BFD-1000 sensor spacing, centre to centre
const float SENSOR_HEIGHT_MM = 41.0f;  // (measured) BFD sensor faces above the floor
const float HW201_RIGHT_MM   = 55.0f;  // (measured) HW-201 distance to the right of S4
const float HW201_RAISE_MM   = 5.0f;   // (measured) HW-201 is 46 mm above the floor
// HW-201 tilt from vertical: + = beam points outward (right), - = inward.
const float HW201_TILT_DEG   = 31.0f;  // (measured from photo, about +/-5 deg)

// A sensor state change is accepted only after this many identical readings
// in a row (each reading is 5 ms apart). Filters flicker and ghosting blips.
const int   SENSOR_FILTER_SAMPLES = 2;

// ---- Robot geometry ---------------------------------------------------------

const float WHEEL_DIAMETER_MM = 33.0f;   // (measured)
const float WHEEL_BASE_MM     = 163.0f;  // (measured) wheel centre to wheel centre
const float SENSOR_AHEAD_MM   = 185.0f;  // (measured) wheel axle to sensor row

// ---- Motors -----------------------------------------------------------------

// LOW-CURRENT MODE: for when the motors are fed from the ESP32's 5V/VIN pin
// (USB power bank). Gentler ramps and slower pivots draw smaller current
// spikes, so the ESP32 is less likely to brown out. Set to 0 once the motors
// have their own supply (battery or separate cable to the TB6612's VM).
#define LOW_CURRENT_MODE 1
const int LOW_CURRENT_SEARCH_SPEED = 100;  // pivot/search PWM in low-current mode

const bool  INVERT_LEFT  = true;   // (measured) motor A wired reversed
const bool  INVERT_RIGHT = false;  // flip if motor B spins backwards

// Per-motor power scale (0.0-1.0). Both 0.5 = half power for USB testing.
// Set both to 1.0 when running on the battery. If the bot drifts on a
// straight, lower the faster side slightly.
const float LEFT_SCALE  = 0.5f;
const float RIGHT_SCALE = 0.5f;

const float MOTOR_RPM_AT_FULL = 300.0f;  // (assumed) wheel rpm at PWM 255 on the battery
const int   MOTOR_DEADBAND    = 40;      // (assumed) PWM below which a wheel doesn't turn
// Lowest PWM that reliably turns a wheel with the robot on the floor. Every
// non-zero command is mapped into MOTOR_MIN_PWM..255 (after the power scale),
// so a slow inner wheel still turns instead of stalling the robot.
const int   MOTOR_MIN_PWM     = 70;      // (assumed) raise if a wheel still stalls
const int   MOTOR_SLEW        = 10;      // soft start: max PWM change per 5 ms step
const int   MOTOR_REVERSE_SLEW = 40;     // faster ramp when a wheel changes direction

// ---- Speeds and steering (PD) -----------------------------------------------

const int   DEFAULT_BASE_SPEED = 150;    // (live: "base") cruise PWM 0-255
const int   DEFAULT_MAX_SPEED  = 255;    // (live: "max")  PWM cap 0-255
const float DEFAULT_KP = 0.08f;          // (live: "kp")
const float DEFAULT_KI = 0.0f;           // (live: "ki")
const float DEFAULT_KD = 0.6f;           // (live: "kd")
// Slow down in curves: base speed x (1 - CURVE_SLOWDOWN x |error| / 2000).
const float CURVE_SLOWDOWN = 0.3f;

// ---- Line engine: lost line, gaps, junctions, corners -----------------------

const int   SEARCH_SPEED       = 140;    // PWM for pivots and sweeps
// Gap / dashed line: if the line was near the centre and roughly straight
// ahead when it vanished, drive straight for up to this distance.
const float GAP_MAX_MM         = 60.0f;
const float GAP_CENTER_MM      = 10.0f;  // "near the centre" limit
const float GAP_MAX_ANGLE_DEG  = 10.0f;  // "roughly straight ahead" limit
// Junction / crossing (line seen on both sides at once): go straight,
// steering only with the centre sensors for this distance.
const float JUNCTION_HOLD_MM   = 40.0f;
// 90-degree corner (line seen across one whole side): if the line is lost
// within this distance afterwards, turn hard toward the corner. The turn is an
// arc: outer wheel at SEARCH_SPEED, inner wheel at SEARCH_SPEED x this factor
// (negative = slowly backwards, -1 = pivot in place, 0 = inner wheel stopped).
const float CORNER_MEMORY_MM   = 80.0f;
// Turn memory: if an OUTER sensor (S1 on the left, S5 on the right) touched the
// line within this distance before the line vanished, even for a single
// unfiltered reading, the line turned that way: pivot toward it instead of
// treating the loss as a gap. Gaps are only assumed when no outer sensor
// touched the line recently.
const float SIDE_MEMORY_MM     = 80.0f;
// S5 (HW-201) reads anything dark as line, including tile grout, which the
// BFD sensors can't see. So S5 is only believed when the line was already
// right of centre: an S5 touch counts for the turn memory only if the line was
// more than S5_TRUST_MM right of centre, and S5 seeing "line" on its own is
// ignored while the line was left of S4.
const float S5_TRUST_MM        = 5.5f;
// Ending a pivot cleanly (stops overshoot after 90-degree turns):
//  - keep pivoting until a CENTRE sensor (S2-S4) has the line, at
//    PIVOT_FIND_FACTOR x pivot speed once only an outer sensor sees it;
//  - then short-brake both wheels for PIVOT_BRAKE_MS to kill the rotation;
//  - then limit the steering correction to POST_TURN_MAX_CORR for
//    POST_TURN_MM, so PD can't throw the robot straight into another swing.
const float PIVOT_FIND_FACTOR  = 0.6f;
const uint32_t PIVOT_BRAKE_MS  = 60;
const float POST_TURN_MM       = 60.0f;
const int   POST_TURN_MAX_CORR = 60;
// Simulation: -1 (pivot) is the only value that passed every hairpin; with the
// sensors 185 mm ahead of the axle, an arc carries them past tight turns.
const float CORNER_INNER_FACTOR = -1.0f;
// Prediction: pivot when the predicted line is this far beyond the outermost
// sensor; give up predicting after turning this much without finding it.
const float PIVOT_MARGIN_MM    = 10.0f;
const float SEARCH_MAX_TURN_DEG = 200.0f;
const float PREDICT_MAX_MM     = 300.0f; // give up predicting after driving this far
const uint32_t SWEEP_FIRST_MS  = 400;    // then sweep: 0.4 s, 0.8 s, 1.6 s ...

// ---- Fallbacks (classic line-follower safety habits) -----------------------

// While predicting a lost line, cap speed to this fraction of base.
const float LOST_SPEED_FACTOR  = 0.8f;
// After the line is found again, drive at this fraction of base for a short
// distance so the robot settles before speeding up.
const float RECOVER_SPEED_FACTOR = 0.85f;
const float RECOVER_MM         = 30.0f;

// ---- Track learning and map -------------------------------------------------

// 0 = race firmware. 1 = track-learning firmware: drives the course once at
// LEARN_BASE_SPEED, records a map, saves it to flash when the line ends
// (or on "save"), and prints it with "export". Build the learning firmware by
// setting this to 1 (or use the TrackLearn sketch, which does exactly that).
#ifndef TRACK_LEARN_MODE
#define TRACK_LEARN_MODE 0
#endif
const int      LEARN_BASE_SPEED  = 110;   // steady speed for the learning run
const float    MAP_STEP_MM       = 20.0f; // one map sample every 20 mm driven
const uint32_t LEARN_END_LOST_MS = 3000;  // line gone this long = end of course (hairpins can take ~2 s)

// Race mode: if tools/export_track.py generated AllInOne/track_map.h, the
// robot uses it to plan speed (fast on straights, slow before curves).
#define USE_TRACK_MAP 1
const float MAP_LOOKAHEAD_MM   = 120.0f;  // plan speed this far ahead
const int   MAP_MIN_BASE       = 90;      // base speed limits when using the map
const int   MAP_MAX_BASE       = 220;
// A junction/corner must appear within this distance of where the map says it
// is; otherwise the map is dropped for the rest of the run (normal driving).
const float MAP_SYNC_WINDOW_MM = 300.0f;

// ---- Pins -------------------------------------------------------------------

const uint8_t PIN_LED  = 2;
const uint8_t PIN_PWMA = 18;
const uint8_t PIN_AIN1 = 19;
const uint8_t PIN_AIN2 = 21;
const uint8_t PIN_PWMB = 23;
const uint8_t PIN_BIN1 = 22;
const uint8_t PIN_BIN2 = 5;
const uint8_t PIN_STBY = 25;

// ---- Boot -------------------------------------------------------------------

const uint32_t START_DELAY_MS   = 2000;  // pause before following starts (power-on only)
// If the ESP32 restarts unexpectedly mid-run (brownout, crash, watchdog), skip
// the start delay and continue driving at once.
const bool     RESUME_AFTER_CRASH = true;
// Two brownouts in a row: keep racing at reduced power (less current, so the
// supply holds) instead of stopping.
const float    BROWNOUT_POWER_FACTOR = 0.7f;

// ############################################################################
// ##                    END OF USER SETTINGS                                ##
// ############################################################################

#if USE_BLUETOOTH
#include <BluetoothSerial.h>
#endif

#if !TRACK_LEARN_MODE && USE_TRACK_MAP && __has_include("track_map.h")
#include "track_map.h"
#define HAVE_TRACK_MAP 1
#else
#define HAVE_TRACK_MAP 0
#endif

// ERROR CODES (LED blinks N times, pauses, repeats; motors stay off)
const uint8_t ERR_RAM      = 2;
const uint8_t ERR_FLASH    = 3;
const uint8_t ERR_PINS     = 4;
const uint8_t ERR_BROWNOUT = 5;

const uint32_t LOOP_PERIOD_MS = 5;

// What the sensors see this step (shown in "watch" as - L J < >)
enum LineEvent : uint8_t { EV_NONE, EV_LINE, EV_JUNCTION, EV_CORNER_LEFT, EV_CORNER_RIGHT };
const char EVENT_CHARS[] = {'-', 'L', 'J', '<', '>'};

// Distance and heading along the run (estimated from wheel commands)
float runDistMm = 0;     // distance driven forward since following started
float runHeading = 0;    // rad, + = turned right

// Live-tunable values (start at the defaults above)
int   BASE_SPEED = DEFAULT_BASE_SPEED;
int   MAX_SPEED  = DEFAULT_MAX_SPEED;
float Kp = DEFAULT_KP;
float Ki = DEFAULT_KI;
float Kd = DEFAULT_KD;
float lineWidthMm = DEFAULT_LINE_WIDTH_MM;

const uint8_t NUM_SENSORS = 5;
const uint8_t* const SENSOR_PINS = SENSOR_PINS_CFG;
const bool    SENSOR_ENABLED[NUM_SENSORS] = {USE_S1, true, true, true, USE_S5};

// Each sensor's lateral floor position (mm, + = right of S3) and its steering
// weight (1000 per BFD pitch, so Kp/Kd keep their meaning).
float SENSOR_X_MM[NUM_SENSORS];
int   SENSOR_WEIGHT[NUM_SENSORS];
float coverLeftMm, coverRightMm;  // outermost enabled sensor positions

void computeSensorWeights() {
  float hwHeight = SENSOR_HEIGHT_MM + HW201_RAISE_MM;
  float hwSpotMm = BFD_PITCH_MM + HW201_RIGHT_MM + hwHeight * tanf(HW201_TILT_DEG * PI / 180.0f);
  float xMm[NUM_SENSORS] = {-2 * BFD_PITCH_MM, -BFD_PITCH_MM, 0, BFD_PITCH_MM, hwSpotMm};
  coverLeftMm = 1e9f;
  coverRightMm = -1e9f;
  for (uint8_t i = 0; i < NUM_SENSORS; i++) {
    SENSOR_X_MM[i] = xMm[i];
    SENSOR_WEIGHT[i] = (int)lroundf(xMm[i] * 1000.0f / BFD_PITCH_MM);
    if (SENSOR_ENABLED[i]) {
      coverLeftMm = min(coverLeftMm, xMm[i]);
      coverRightMm = max(coverRightMm, xMm[i]);
    }
  }
}

const uint8_t MOTOR_PINS[]  = {PIN_STBY, PIN_PWMA, PIN_AIN1, PIN_AIN2, PIN_PWMB, PIN_BIN1, PIN_BIN2};
const char*   MOTOR_NAMES[] = {"STBY", "PWMA", "AIN1", "AIN2", "PWMB", "BIN1", "BIN2"};
const uint8_t NUM_MOTOR_PINS = sizeof(MOTOR_PINS);

// ============================== PWM =========================================

const uint32_t PWM_FREQ = 20000;
const uint8_t  PWM_RES  = 8;
const uint8_t  PWM_CH_A = 0;  // used only on core < 3.0
const uint8_t  PWM_CH_B = 1;

void pwmInit() {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(PIN_PWMA, PWM_FREQ, PWM_RES);
  ledcAttach(PIN_PWMB, PWM_FREQ, PWM_RES);
#else
  ledcSetup(PWM_CH_A, PWM_FREQ, PWM_RES);
  ledcSetup(PWM_CH_B, PWM_FREQ, PWM_RES);
  ledcAttachPin(PIN_PWMA, PWM_CH_A);
  ledcAttachPin(PIN_PWMB, PWM_CH_B);
#endif
}

void pwmWrite(uint8_t pin, uint8_t channel, uint32_t duty) {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  (void)channel;
  ledcWrite(pin, duty);
#else
  (void)pin;
  ledcWrite(channel, duty);
#endif
}

// ============================== MOTORS ======================================

// speed: -255 (full reverse) .. +255 (full forward)
bool brakeAtZero = true;
float powerLimit = 1.0f;  // lowered after repeated brownouts

void driveOne(int speed, uint8_t in1, uint8_t in2, uint8_t pwmPin, uint8_t ch) {
  speed = constrain(speed, -MAX_SPEED, MAX_SPEED);
  if (speed > 0) {
    digitalWrite(in1, HIGH);
    digitalWrite(in2, LOW);
  } else if (speed < 0) {
    digitalWrite(in1, LOW);
    digitalWrite(in2, HIGH);
  } else if (brakeAtZero) {
    // short brake (explicit stop)
    digitalWrite(in1, HIGH);
    digitalWrite(in2, HIGH);
  } else {
    // coast while driving, so passing through zero doesn't brake the wheel
    digitalWrite(in1, LOW);
    digitalWrite(in2, LOW);
  }
  pwmWrite(pwmPin, ch, abs(speed));
}

int curLeft = 0, curRight = 0;  // last values actually sent to the driver

int slew(int cur, int target) {
  // Changing direction (or slowing toward zero): use the faster ramp so the
  // wheel doesn't spend ~150 ms creeping through zero.
  bool reversing = (cur > 0 && target < cur) || (cur < 0 && target > cur);
  int step = (reversing && !LOW_CURRENT_MODE) ? MOTOR_REVERSE_SLEW : MOTOR_SLEW;
  if (target > cur + step) return cur + step;
  if (target < cur - step) return cur - step;
  return target;
}

// Command (-255..255) -> PWM actually sent: power scale, then lifted above
// MOTOR_MIN_PWM so any non-zero command really turns the wheel.
int effectivePwm(int cmd, float scale) {
  if (cmd == 0) return 0;
  float a = fabsf(cmd) * scale;
  int pwm = (int)(MOTOR_MIN_PWM + a * (255 - MOTOR_MIN_PWM) / 255.0f);
  return cmd < 0 ? -pwm : pwm;
}

void applyMotors(int left, int right) {
  curLeft = left;
  curRight = right;
  left  = effectivePwm(left,  LEFT_SCALE * powerLimit);
  right = effectivePwm(right, RIGHT_SCALE * powerLimit);
  if (INVERT_LEFT)  left  = -left;
  if (INVERT_RIGHT) right = -right;
  driveOne(left,  PIN_AIN1, PIN_AIN2, PIN_PWMA, PWM_CH_A);
  driveOne(right, PIN_BIN1, PIN_BIN2, PIN_PWMB, PWM_CH_B);
}

// Moves toward the target speed by at most MOTOR_SLEW per call
void setMotors(int left, int right) {
  brakeAtZero = false;
  applyMotors(slew(curLeft, left), slew(curRight, right));
}

void stopMotors() { brakeAtZero = true; applyMotors(0, 0); }  // immediate, brakes

// ============================== RESET LOG ===================================

enum Mode : uint8_t { MODE_SETUP, MODE_MOTOR_TEST, MODE_FOLLOW, MODE_LOST, MODE_STOPPED, MODE_FAULT };
const char* MODE_NAMES[] = {"setup/diagnostics", "motor test", "following line", "searching (line lost)",
                            "stopped (line lost)", "FAULT (motors off)"};

struct LogEntry {
  uint32_t boot;          // boot number since log was cleared
  uint32_t prevUptimeMs;  // how long the previous run lasted (last saved value)
  uint8_t  reason;        // esp_reset_reason_t of this boot
  uint8_t  pinsOk;        // motor pin self-test result this boot
  uint8_t  prevMode;      // what the previous run was doing when it ended
  uint8_t  pad;
};

const int      LOG_SIZE       = 32;    // ring buffer of the last 32 boots
const uint32_t UPTIME_SAVE_MS = 2000;         // when stopped
const uint32_t UPTIME_SAVE_DRIVING_MS = 10000; // while driving: flash writes can stall the CPU

Preferences prefs;
LogEntry logBuf[LOG_SIZE];
uint32_t bootCount = 0;
uint32_t logHead   = 0;
Mode     mode      = MODE_SETUP;

const char* resetReasonName(esp_reset_reason_t r) {
  switch (r) {
    case ESP_RST_POWERON:   return "power-on / EN pin";
    case ESP_RST_EXT:       return "external pin";
    case ESP_RST_SW:        return "software";
    case ESP_RST_PANIC:     return "PANIC (crash)";
    case ESP_RST_INT_WDT:   return "interrupt watchdog";
    case ESP_RST_TASK_WDT:  return "task watchdog";
    case ESP_RST_WDT:       return "other watchdog";
    case ESP_RST_BROWNOUT:  return "BROWNOUT (supply dipped)";
    case ESP_RST_DEEPSLEEP: return "deep sleep wake";
    default:                return "unknown";
  }
}

// Mode is saved to flash by service() every 2 s, not on every change
void setMode(uint8_t m) { mode = (Mode)m; }

void logClear() {
  prefs.clear();
  memset(logBuf, 0, sizeof(logBuf));
  bootCount = 0;
  logHead = 0;
  prefs.putString("build", __DATE__ " " __TIME__);
}

void logDump() {
  Serial.println("----- RESET LOG (oldest first) -----");
  Serial.printf("Total boots recorded: %lu\n", (unsigned long)bootCount);
  uint32_t n = logHead < LOG_SIZE ? logHead : LOG_SIZE;
  if (logHead > LOG_SIZE) Serial.printf("(only the last %d kept)\n", LOG_SIZE);
  uint32_t brownouts = 0, crashes = 0;
  for (uint32_t k = 0; k < n; k++) {
    const LogEntry& e = logBuf[(logHead - n + k) % LOG_SIZE];
    esp_reset_reason_t r = (esp_reset_reason_t)e.reason;
    if (r == ESP_RST_BROWNOUT) brownouts++;
    if (r == ESP_RST_PANIC || r == ESP_RST_INT_WDT || r == ESP_RST_TASK_WDT || r == ESP_RST_WDT) crashes++;
    Serial.printf("  boot #%-3lu %-26s pins:%s | previous run lasted %lu.%lu s, ended while %s\n",
                  (unsigned long)e.boot, resetReasonName(r), e.pinsOk ? "OK  " : "FAIL",
                  (unsigned long)(e.prevUptimeMs / 1000), (unsigned long)(e.prevUptimeMs % 1000 / 100),
                  e.prevMode <= MODE_FAULT ? MODE_NAMES[e.prevMode] : "-");
  }
  Serial.printf("Brownouts: %lu | Crashes/watchdogs: %lu\n", (unsigned long)brownouts, (unsigned long)crashes);
  Serial.println("------------------------------------");
}

void logBoot(esp_reset_reason_t reason, bool pinsOk) {
  LogEntry e = {};
  e.boot         = ++bootCount;
  e.prevUptimeMs = prefs.getUInt("uptime", 0);
  e.prevMode     = prefs.getUChar("mode", MODE_SETUP);
  e.reason       = (uint8_t)reason;
  e.pinsOk       = pinsOk;
  logBuf[logHead % LOG_SIZE] = e;
  logHead++;
  prefs.putBytes("log", logBuf, sizeof(logBuf));
  prefs.putUInt("head", logHead);
  prefs.putUInt("boots", bootCount);
  prefs.putUInt("uptime", 0);
  prefs.putUChar("mode", MODE_SETUP);
}

void logInit(esp_reset_reason_t reason, bool pinsOk) {
  prefs.begin("aiolog", false);
  if (prefs.getString("build", "") != String(__DATE__ " " __TIME__)) {
    Serial.println("New firmware build: clearing reset log and tuned values.");
    logClear();
    Preferences t;
    t.begin("tune", false);
    t.clear();
    t.end();
  }
  memset(logBuf, 0, sizeof(logBuf));
  bootCount = prefs.getUInt("boots", 0);
  logHead   = prefs.getUInt("head", 0);
  prefs.getBytes("log", logBuf, sizeof(logBuf));
  logBoot(reason, pinsOk);
}

// True if this boot and the one before it were both brownouts
bool repeatedBrownout() {
  if (logHead < 2) return false;
  const LogEntry& a = logBuf[(logHead - 1) % LOG_SIZE];
  const LogEntry& b = logBuf[(logHead - 2) % LOG_SIZE];
  return a.reason == ESP_RST_BROWNOUT && b.reason == ESP_RST_BROWNOUT;
}

uint32_t lastSave = 0;

// ============================== LIVE TUNING =================================

#if USE_BLUETOOTH
BluetoothSerial SerialBT;
#endif
Preferences tune;
String usbLine, btLine;
bool paused = false;
bool watching = false;
bool btReady = false;  // Bluetooth starts after the boot checks

void tuneSave() {
  tune.putFloat("kp", Kp);
  tune.putFloat("ki", Ki);
  tune.putFloat("kd", Kd);
  tune.putInt("base", BASE_SPEED);
  tune.putInt("max", MAX_SPEED);
  tune.putFloat("width", lineWidthMm);
}

void tuneLoad() {
  tune.begin("tune", false);
  Kp         = tune.getFloat("kp", DEFAULT_KP);
  Ki         = tune.getFloat("ki", DEFAULT_KI);
  Kd         = tune.getFloat("kd", DEFAULT_KD);
  BASE_SPEED = tune.getInt("base", DEFAULT_BASE_SPEED);
  MAX_SPEED  = tune.getInt("max", DEFAULT_MAX_SPEED);
  lineWidthMm = tune.getFloat("width", DEFAULT_LINE_WIDTH_MM);
}

void tuneReset() {
  tune.clear();
  Kp = DEFAULT_KP; Ki = DEFAULT_KI; Kd = DEFAULT_KD;
  BASE_SPEED = DEFAULT_BASE_SPEED;
  MAX_SPEED  = DEFAULT_MAX_SPEED;
  lineWidthMm = DEFAULT_LINE_WIDTH_MM;
}

void showTuning(Stream& out) {
  out.printf("Kp=%.4f Ki=%.4f Kd=%.4f base=%d max=%d width=%.0fmm %s\n",
             Kp, Ki, Kd, BASE_SPEED, MAX_SPEED, lineWidthMm, paused ? "[STOPPED]" : "[running]");
}

void handleCommand(String cmd, Stream& out) {
  cmd.trim();
  cmd.toLowerCase();
  cmd.replace("=", " ");
  if (cmd.length() == 0) return;
  int sp = cmd.indexOf(' ');
  String key = sp < 0 ? cmd : cmd.substring(0, sp);
  String val = sp < 0 ? "" : cmd.substring(sp + 1);
  val.trim();
  bool hasVal = val.length() > 0;

  if      (key == "show")  { showTuning(out); return; }
  else if (key == "stop")  { paused = true;  stopMotors(); out.println("Motors stopped. 'go' to resume."); return; }
  else if (key == "go")    { paused = false; out.println("Running."); return; }
  else if (key == "watch") { watching = !watching; out.printf("Live data %s\n", watching ? "ON" : "OFF"); return; }
  else if (key == "reset") { tuneReset(); out.print("Defaults restored: "); showTuning(out); return; }
  else if (key == "log")   { logDump(); return; }
  else if (key == "clear") { logClear(); out.println("Reset log cleared."); return; }
  else if (key == "export") { mapExport(out); return; }
  else if (key == "save")   { learnFinish(out); return; }
  else if (key == "map")    { mapStatus(out); return; }
  else if (key == "kp" && hasVal)   Kp = max(0.0f, val.toFloat());
  else if (key == "ki" && hasVal)   Ki = max(0.0f, val.toFloat());
  else if (key == "kd" && hasVal)   Kd = max(0.0f, val.toFloat());
  else if (key == "base" && hasVal) BASE_SPEED = constrain(val.toInt(), 0, 255);
  else if (key == "max" && hasVal)  MAX_SPEED  = constrain(val.toInt(), 0, 255);
  else if (key == "width" && hasVal) lineWidthMm = constrain(val.toFloat(), 3.0f, 100.0f);
  else { out.println("Unknown. Try: show, kp 0.08, kd 0.6, ki 0, base 150, max 255, width 18, stop, go, watch, reset, map, export, save"); return; }
  tuneSave();
  showTuning(out);
}

void pollCommands(Stream& in, String& buf) {
  while (in.available()) {
    char c = in.read();
    if (c == '\n' || c == '\r') {
      handleCommand(buf, in);
      buf = "";
    } else if (buf.length() < 40) {
      buf += c;
    }
  }
}

// Call often: saves uptime for the log and handles serial commands
void service() {
  uint32_t now = millis();
  bool driving = (mode == MODE_FOLLOW || mode == MODE_LOST) && !paused;
  if (now - lastSave >= (driving ? UPTIME_SAVE_DRIVING_MS : UPTIME_SAVE_MS)) {
    lastSave = now;
    prefs.putUInt("uptime", now);
    if (prefs.getUChar("mode", 255) != mode) prefs.putUChar("mode", mode);
  }
  pollCommands(Serial, usbLine);
#if USE_BLUETOOTH
  if (btReady) pollCommands(SerialBT, btLine);
#endif
}

// ============================== DIAGNOSTICS =================================

bool ramTest() {
  const size_t BLOCK = 32 * 1024;
  const int    MAX_BLOCKS = 16;
  uint32_t* blocks[MAX_BLOCKS] = {nullptr};
  int n = 0;
  bool ok = true;

  while (n < MAX_BLOCKS && (blocks[n] = (uint32_t*)malloc(BLOCK)) != nullptr) n++;
  Serial.printf("  allocated %d x 32 KB = %d KB\n", n, n * 32);

  const uint32_t patterns[] = {0x00000000, 0xFFFFFFFF, 0xAAAAAAAA, 0x55555555};
  for (uint32_t p : patterns) {
    for (int b = 0; b < n; b++)
      for (size_t i = 0; i < BLOCK / 4; i++) blocks[b][i] = p ^ (i * 2654435761u);
    for (int b = 0; b < n && ok; b++)
      for (size_t i = 0; i < BLOCK / 4; i++)
        if (blocks[b][i] != (p ^ (i * 2654435761u))) {
          Serial.printf("  MISMATCH block %d word %u pattern %08lX\n", b, (unsigned)i, (unsigned long)p);
          ok = false;
          break;
        }
  }
  for (int b = 0; b < n; b++) free(blocks[b]);
  return ok && n > 0;
}

// Drive a pin and read back the actual pad level
bool pinSelfTest(uint8_t pin) {
  gpio_reset_pin((gpio_num_t)pin);
  gpio_set_direction((gpio_num_t)pin, GPIO_MODE_INPUT_OUTPUT);
  gpio_set_level((gpio_num_t)pin, 1);
  delayMicroseconds(200);
  int high = gpio_get_level((gpio_num_t)pin);
  gpio_set_level((gpio_num_t)pin, 0);
  delayMicroseconds(200);
  int low = gpio_get_level((gpio_num_t)pin);
  gpio_reset_pin((gpio_num_t)pin);
  return high == 1 && low == 0;
}

// Blink an error code forever with the motors off
void fault(uint8_t code, const char* why) {
  pinMode(PIN_STBY, OUTPUT);
  digitalWrite(PIN_STBY, LOW);
  setMode(MODE_FAULT);
  prefs.putUChar("mode", MODE_FAULT);
  Serial.printf("FAULT %u: %s. Motors disabled. Send 'd' for log, 'c' to clear.\n", code, why);
  while (true) {
    for (uint8_t i = 0; i < code; i++) {
      digitalWrite(PIN_LED, HIGH); delay(200);
      digitalWrite(PIN_LED, LOW);  delay(200);
      service();
    }
    for (int i = 0; i < 10; i++) { delay(100); service(); }
  }
}

// ============================== SENSORS =====================================


// Debounced sensor states: a change is accepted only after SENSOR_FILTER_SAMPLES
// identical raw readings in a row.
bool    filteredOn[NUM_SENSORS] = {false};
uint8_t changeCount[NUM_SENSORS] = {0};

uint8_t rawMask = 0;  // this reading, before the flicker filter

uint8_t readSensorMask() {
  uint8_t mask = 0;
  rawMask = 0;
  for (uint8_t i = 0; i < NUM_SENSORS; i++) {
    if (!SENSOR_ENABLED[i]) continue;
    bool lineIsHigh = (i == 4) ? HW201_LINE_IS_HIGH : LINE_IS_HIGH;
    bool raw = (digitalRead(SENSOR_PINS[i]) == HIGH) == lineIsHigh;
    if (raw) rawMask |= (1 << i);
    if (raw != filteredOn[i]) {
      if (++changeCount[i] >= SENSOR_FILTER_SAMPLES) {
        filteredOn[i] = raw;
        changeCount[i] = 0;
      }
    } else {
      changeCount[i] = 0;
    }
    if (filteredOn[i]) mask |= (1 << i);
  }
  return mask;
}

// Classifies what the sensors see. pos = steering position in weight units
// (1000 per BFD pitch, - = left, + = right); xMm = line position in mm.
LineEvent readLine(int &pos, uint8_t &mask, float &xMm) {
  mask = readSensorMask();
  long sum = 0;
  int count = 0;
  float minX = 1e9f, maxX = -1e9f;
  for (uint8_t i = 0; i < NUM_SENSORS; i++) {
    if (!(mask & (1 << i))) continue;
    sum += SENSOR_WEIGHT[i];
    count++;
    minX = min(minX, SENSOR_X_MM[i]);
    maxX = max(maxX, SENSOR_X_MM[i]);
  }
  if (count == 0) return EV_NONE;
  pos = sum / count;
  xMm = pos * BFD_PITCH_MM / 1000.0f;

  // One line of lineWidthMm can't light sensors further apart than its width
  // plus half a pitch (sensor spots overlap its edges). Wider = junction or corner.
  float half = BFD_PITCH_MM * 0.5f;
  if (count >= 2 && maxX - minX > lineWidthMm + half) {
    if (minX < -half && maxX > half) return EV_JUNCTION;  // line on both sides
    return maxX > half ? EV_CORNER_RIGHT : EV_CORNER_LEFT;
  }
  return EV_LINE;
}

void printSensors() {
  int pos = 0;
  uint8_t mask = 0;
  float xMm = 0;
  for (int i = 0; i < SENSOR_FILTER_SAMPLES; i++) readLine(pos, mask, xMm);  // settle the filter
  Serial.print("Sensors S1..S5: ");
  for (uint8_t i = 0; i < NUM_SENSORS; i++)
    Serial.print(SENSOR_ENABLED[i] ? ((mask >> i) & 1 ? '1' : '0') : 'x');
  Serial.println("   (1 = line, 0 = no line, x = disabled)");
}

// ============================== SETUP =======================================

void setup() {
  // Driver held in standby until everything checks out
  pinMode(PIN_STBY, OUTPUT);
  digitalWrite(PIN_STBY, LOW);
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, HIGH);  // LED on during diagnostics

  Serial.begin(115200);
  delay(300);
  Serial.println("\n===== LINE FOLLOWER: DIAGNOSTICS =====");

  esp_chip_info_t info;
  esp_chip_info(&info);
  esp_reset_reason_t reason = esp_reset_reason();
  Serial.printf("Chip: %s rev %d, %d cores, CPU %lu MHz, XTAL %lu MHz\n",
                ESP.getChipModel(), ESP.getChipRevision(), info.cores,
                (unsigned long)getCpuFrequencyMhz(), (unsigned long)getXtalFrequencyMhz());
  Serial.printf("Reset reason: %s\n", resetReasonName(reason));
  Serial.printf("Flash: %lu KB @ %lu MHz | Heap: %lu KB free\n",
                (unsigned long)(ESP.getFlashChipSize() / 1024),
                (unsigned long)(ESP.getFlashChipSpeed() / 1000000),
                (unsigned long)(ESP.getFreeHeap() / 1024));

  Serial.println("RAM test...");
  bool ramOk = ramTest();
  Serial.println(ramOk ? "RAM: PASS" : "RAM: FAIL");

  Serial.println("Flash read test...");
  String md5 = ESP.getSketchMD5();  // reads the whole sketch back from flash
  bool flashOk = md5.length() == 32;
  Serial.println(flashOk ? "FLASH: PASS" : "FLASH: FAIL");

  Serial.println("Motor pin self-test (drive HIGH/LOW, read pad back)...");
  bool pinsOk = true;
  for (uint8_t i = 0; i < NUM_MOTOR_PINS; i++) {
    if (MOTOR_PINS[i] == PIN_STBY) continue;  // keep driver in standby during test
    bool ok = pinSelfTest(MOTOR_PINS[i]);
    pinsOk &= ok;
    Serial.printf("  %-4s GPIO%-2d : %s\n", MOTOR_NAMES[i], MOTOR_PINS[i],
                  ok ? "OK" : "FAIL (shorted/overloaded or damaged)");
  }
  Serial.println(pinsOk ? "PINS: PASS" : "PINS: FAIL");

  // Restore motor pins for normal use (STBY still LOW)
  pinMode(PIN_AIN1, OUTPUT);
  pinMode(PIN_AIN2, OUTPUT);
  pinMode(PIN_BIN1, OUTPUT);
  pinMode(PIN_BIN2, OUTPUT);
  pwmInit();
  stopMotors();

  for (uint8_t i = 0; i < NUM_SENSORS; i++) {
    if (SENSOR_ENABLED[i]) pinMode(SENSOR_PINS[i], INPUT);
  }

  computeSensorWeights();
  Serial.printf("Sensor weights S1..S5: %d %d %d %d %d\n", SENSOR_WEIGHT[0], SENSOR_WEIGHT[1],
                SENSOR_WEIGHT[2], SENSOR_WEIGHT[3], SENSOR_WEIGHT[4]);
  logInit(reason, pinsOk);
  logDump();

  if (!ramOk)             fault(ERR_RAM, "RAM test failed");
  if (!flashOk)           fault(ERR_FLASH, "flash read failed");
  if (!pinsOk)            fault(ERR_PINS, "motor pin self-test failed");
  if (repeatedBrownout()) {
    powerLimit = BROWNOUT_POWER_FACTOR;
    Serial.printf("WARNING: two brownouts in a row - racing at %.0f%% power. Check the supply!\n",
                  BROWNOUT_POWER_FACTOR * 100);
  }

  printSensors();

  bool crashRestart = RESUME_AFTER_CRASH &&
      (reason == ESP_RST_BROWNOUT || reason == ESP_RST_PANIC || reason == ESP_RST_INT_WDT ||
       reason == ESP_RST_TASK_WDT || reason == ESP_RST_WDT);
  uint32_t startDelay = crashRestart ? 0 : START_DELAY_MS;
  Serial.printf("===== ALL CHECKS PASSED: following line in %lu ms%s =====\n",
                (unsigned long)startDelay, crashRestart ? " (resuming after unexpected restart)" : "");
  tuneLoad();
#if USE_BLUETOOTH
  btReady = SerialBT.begin("LineFollower");
#endif
  Serial.println(USE_BLUETOOTH ? "Tuning over USB or Bluetooth 'LineFollower'. Type 'show' for values."
                               : "Tuning over USB serial (Bluetooth off). Type 'show' for values.");
  showTuning(Serial);
  digitalWrite(PIN_LED, LOW);

  // Blink while waiting so you know it's about to move
  uint32_t t = millis();
  while (millis() - t < startDelay) {
    digitalWrite(PIN_LED, ((millis() - t) / 125) % 2);
    service();
  }
  digitalWrite(PIN_LED, LOW);
  digitalWrite(PIN_STBY, HIGH);  // enable the motor driver: all checks passed
  setMode(MODE_FOLLOW);
}

// ============================== LINE FOLLOWING ==============================

// Robot motion from the commanded wheel PWM (dead reckoning).
const float WHEEL_MAX_MMPS = PI * WHEEL_DIAMETER_MM * MOTOR_RPM_AT_FULL / 60.0f;

float wheelMmps(float pwm) {
  float a = fabsf(pwm);
  if (a < MOTOR_DEADBAND) return 0;
  float v = (a - MOTOR_DEADBAND) / (255.0f - MOTOR_DEADBAND) * WHEEL_MAX_MMPS;
  return pwm < 0 ? -v : v;
}

// Distance driven (mm) and turn (rad, + = right) over one loop step.
void odometry(float &ds, float &dth) {
  float vL = wheelMmps(effectivePwm(curLeft, LEFT_SCALE * powerLimit));
  float vR = wheelMmps(effectivePwm(curRight, RIGHT_SCALE * powerLimit));
  float dt = LOOP_PERIOD_MS / 1000.0f;
  ds  = (vL + vR) * 0.5f * dt;
  dth = (vL - vR) / WHEEL_BASE_MM * dt;
}

// Line model, in the robot's frame: where the line crosses the sensor row
// (mm, + = right) and its angle to the robot's heading (rad, + = runs right).
float lineX = 0, lineAngle = 0;
float prevMeasX = 0;
bool  haveMeas = false;

// Lost-line state
bool  lost = false;
float lostDistMm = 0, lostTurnDeg = 0;
float lossX = 0, lossAngle = 0;  // line model at the moment it vanished
uint32_t sweepStartMs = 0;
uint32_t lostStartMs = 0;

// Feature memory
float junctionLeftMm = 0;   // distance left to drive straight through a junction
float sinceCornerMm = 1e9f; // distance since the last corner was seen
int   cornerDir = 0;        // +1 right, -1 left

float lastError = 0, integral = 0;
uint32_t lastLoopMs = 0;

// Distance (runDistMm) when each outer sensor last touched the line
float leftEdgeSeenMm = -1e9f, rightEdgeSeenMm = -1e9f;

// Pivot turn in progress (started while the line was lost)
int      turnDir = 0;          // +1 right, -1 left, 0 = none
float    turnStartHeading = 0;
uint32_t brakeUntilMs = 0;
float    postTurnLeftMm = 0;

const float MAX_LINE_ANGLE = 85.0f * PI / 180.0f;

void steer(float error, int base) {
  float derivative = error - lastError;
  integral = constrain(integral + error, -10000.0f, 10000.0f);
  float correction = Kp * error + Ki * integral + Kd * derivative;
  lastError = error;
  if (postTurnLeftMm > 0)  // just came out of a pivot: gentle steering only
    correction = constrain(correction, (float)-POST_TURN_MAX_CORR, (float)POST_TURN_MAX_CORR);
  setMotors(base + (int)correction, base - (int)correction);
}

int searchSpeed() { return LOW_CURRENT_MODE ? LOW_CURRENT_SEARCH_SPEED : SEARCH_SPEED; }

// Pivot toward dir and remember that a turn is in progress, so it only ends
// once the line reaches a centre sensor (see loop step 3).
void turnPivot(int dir) {
  if (turnDir != dir) {
    turnDir = dir;
    turnStartHeading = runHeading;
  }
  setMotors(dir * searchSpeed(), -dir * searchSpeed());
}

void pivot(int dir) {  // dir +1 = turn right in place
  setMotors(dir * searchSpeed(), -dir * searchSpeed());
}

// Base speed for this moment: learning speed, or the map's planned speed,
// reduced while recovering from a lost line.
float recoverLeftMm = 0;
int runBase();

int curveBase(float error) {
  float k = 1.0f - CURVE_SLOWDOWN * min(1.0f, fabsf(error) / 2000.0f);
  return (int)(runBase() * k);
}

void watchPrint(uint32_t now, uint8_t mask, LineEvent ev, const char* action) {
  static uint32_t lastWatch = 0;
  if (!(watching || DEBUG_SERIAL) || now - lastWatch < 100) return;
  lastWatch = now;
  char s[6];
  for (uint8_t i = 0; i < NUM_SENSORS; i++)
    s[i] = SENSOR_ENABLED[i] ? ((mask >> i) & 1 ? '1' : '0') : 'x';
  s[5] = 0;
  char line[120];
  snprintf(line, sizeof(line), "%s %c %-8s lineX=%6.1fmm ang=%5.1fdeg L=%4d R=%4d\n",
           s, EVENT_CHARS[ev], action, lineX, lineAngle * 180.0f / PI, curLeft, curRight);
  Serial.print(line);
#if USE_BLUETOOTH
  if (btReady && SerialBT.hasClient()) SerialBT.print(line);
#endif
}

// ============================== TRACK MAP ===================================
//
// Distance and heading along the run, estimated from the wheel commands
// (no encoders). The learning run and the race run use the same estimate, so
// its errors are similar in both and partly cancel; junctions and corners are
// used as landmarks to correct the distance during the race.

const uint8_t MF_JUNCTION = 1, MF_CORNER_L = 2, MF_CORNER_R = 4, MF_GAP = 8, MF_LOST = 16;

uint8_t prevFlags = 0;

const char* MAP_FILE = "/track.bin";
const uint32_t MAP_MAGIC = 0x4D50544CUL;  // "LTPM"

struct MapSample {
  uint16_t s;      // mm
  int16_t  head;   // heading in 0.1 deg, wrapped to -1800..1800
  uint8_t  flags;  // MF_* seen since the previous sample
  uint8_t  pad;
};

bool fsReady = false;
bool ensureFs() {
  if (!fsReady) fsReady = LittleFS.begin(true);
  return fsReady;
}

#if TRACK_LEARN_MODE
const int MAP_MAX_SAMPLES = 3000;  // 60 m at 20 mm per sample
MapSample mapBuf[MAP_MAX_SAMPLES];
int   mapCount = 0;
float nextSampleMm = 0;
uint8_t pendingFlags = 0;
bool  learnDone = false;
#endif

#if HAVE_TRACK_MAP
bool mapValid = true;

// Planned speed (mm/s) at distance s, from the generated profile.
float mapSpeedAt(float s) {
  if (s <= TRACK_MAP_S[0]) return TRACK_MAP_V[0];
  for (int i = 1; i < TRACK_MAP_POINTS; i++)
    if (s < TRACK_MAP_S[i]) return TRACK_MAP_V[i - 1];
  return TRACK_MAP_V[TRACK_MAP_POINTS - 1];
}

// A junction or corner was just seen: snap the distance to the matching
// landmark on the map, or drop the map if none is close enough.
void mapSync(uint8_t type) {
  if (!mapValid) return;
  int best = -1;
  float bestD = MAP_SYNC_WINDOW_MM;
  for (int i = 0; i < TRACK_MAP_LANDMARKS; i++) {
    if (TRACK_MAP_LM_TYPE[i] != type) continue;
    float d = fabsf(TRACK_MAP_LM_S[i] - runDistMm);
    if (d < bestD) { bestD = d; best = i; }
  }
  if (best >= 0) {
    runDistMm = TRACK_MAP_LM_S[best];
  } else {
    mapValid = false;
    Serial.printf("MAP: unexpected landmark at %.0f mm, map off for this run\n", runDistMm);
  }
}
#endif

// Wheel speed (mm/s) -> command 0-255, inverting the motor model
// (power scale and MOTOR_MIN_PWM lift included).
int speedToCmd(float v) {
  float eff = MOTOR_DEADBAND + v / WHEEL_MAX_MMPS * (255.0f - MOTOR_DEADBAND);
  float scale = (LEFT_SCALE + RIGHT_SCALE) * 0.5f * powerLimit;
  float cmd = (eff - MOTOR_MIN_PWM) * 255.0f / (255.0f - MOTOR_MIN_PWM) / scale;
  return constrain((int)cmd, 0, 255);
}

int runBase() {
#if TRACK_LEARN_MODE
  int base = LEARN_BASE_SPEED;
#else
  int base = BASE_SPEED;
#if HAVE_TRACK_MAP
  if (mapValid && runDistMm < TRACK_MAP_LENGTH_MM)
    base = constrain(speedToCmd(mapSpeedAt(runDistMm + MAP_LOOKAHEAD_MM)), MAP_MIN_BASE, MAP_MAX_BASE);
#endif
#endif
  if (recoverLeftMm > 0) base = (int)(base * RECOVER_SPEED_FACTOR);
  return base;
}

// Called every step with the robot's movement.
void trackUpdate(float ds, float dth) {
  runDistMm += max(0.0f, ds);
  runHeading += dth;
  recoverLeftMm = max(0.0f, recoverLeftMm - fabsf(ds));
  postTurnLeftMm = max(0.0f, postTurnLeftMm - fabsf(ds));
#if TRACK_LEARN_MODE
  if (!learnDone && runDistMm >= nextSampleMm && mapCount < MAP_MAX_SAMPLES) {
    float deg = fmodf(runHeading * 180.0f / PI, 360.0f);
    if (deg > 180) deg -= 360;
    if (deg < -180) deg += 360;
    mapBuf[mapCount++] = {(uint16_t)min(65535.0f, runDistMm), (int16_t)lroundf(deg * 10), pendingFlags, 0};
    pendingFlags = 0;
    nextSampleMm += MAP_STEP_MM;
  }
#endif
}

// Called every step with what the sensors saw.
void trackEvent(LineEvent ev, bool isGap, bool isLost) {
  uint8_t f = 0;
  if (ev == EV_JUNCTION)     f |= MF_JUNCTION;
  if (ev == EV_CORNER_LEFT)  f |= MF_CORNER_L;
  if (ev == EV_CORNER_RIGHT) f |= MF_CORNER_R;
  if (isGap)  f |= MF_GAP;
  if (isLost) f |= MF_LOST;
#if TRACK_LEARN_MODE
  pendingFlags |= f;
#elif HAVE_TRACK_MAP
  uint8_t rising = f & ~prevFlags;
  if (rising & MF_JUNCTION) mapSync(MF_JUNCTION);
  if (rising & MF_CORNER_L) mapSync(MF_CORNER_L);
  if (rising & MF_CORNER_R) mapSync(MF_CORNER_R);
#endif
  prevFlags = f;
}

// Learning run finished (line ended, or "save"): stop and write the map.
void learnFinish(Stream& out) {
#if TRACK_LEARN_MODE
  if (learnDone) { out.println("Map already saved. 'export' to print it."); return; }
  learnDone = true;
  paused = true;
  stopMotors();  // no flash writes while the motors run
  if (!ensureFs()) { out.println("MAP: flash filesystem not available, map NOT saved"); return; }
  File f = LittleFS.open(MAP_FILE, "w");
  if (!f) { out.println("MAP: could not open file, map NOT saved"); return; }
  uint32_t hdr[3] = {MAP_MAGIC, (uint32_t)mapCount, (uint32_t)MAP_STEP_MM};
  f.write((uint8_t*)hdr, sizeof(hdr));
  f.write((uint8_t*)mapBuf, mapCount * sizeof(MapSample));
  f.close();
  out.printf("MAP: saved %d samples, %.0f mm. Plug into the PC and run tools/export_track.py\n",
             mapCount, runDistMm);
#else
  out.println("This is the race firmware; 'save' only works in the learning firmware.");
#endif
}

// Prints the saved map (works in either firmware: the file survives reflashing).
void mapExport(Stream& out) {
  if (!ensureFs() || !LittleFS.exists(MAP_FILE)) { out.println("TRACK_EXPORT none"); return; }
  File f = LittleFS.open(MAP_FILE, "r");
  uint32_t hdr[3];
  if (f.read((uint8_t*)hdr, sizeof(hdr)) != sizeof(hdr) || hdr[0] != MAP_MAGIC) {
    out.println("TRACK_EXPORT bad_file");
    f.close();
    return;
  }
  out.println("TRACK_EXPORT v1");
  out.printf("step_mm=%lu\nsamples=%lu\n", (unsigned long)hdr[2], (unsigned long)hdr[1]);
  out.println("s_mm,heading_deg,flags");
  MapSample m;
  uint32_t n = 0;
  while (n < hdr[1] && f.read((uint8_t*)&m, sizeof(m)) == sizeof(m)) {
    out.printf("%u,%.1f,%u\n", m.s, m.head / 10.0f, m.flags);
    n++;
  }
  f.close();
  out.printf("TRACK_END count=%lu\n", (unsigned long)n);
}

void mapStatus(Stream& out) {
#if TRACK_LEARN_MODE
  out.printf("LEARNING firmware: %d samples, %.0f mm so far, %s\n",
             mapCount, runDistMm, learnDone ? "saved" : "recording");
#elif HAVE_TRACK_MAP
  out.printf("RACE firmware with map: %d points, %d landmarks, %.0f mm long; now at %.0f mm, map %s\n",
             TRACK_MAP_POINTS, TRACK_MAP_LANDMARKS, (float)TRACK_MAP_LENGTH_MM, runDistMm,
             mapValid ? "in use" : "dropped (normal driving)");
#else
  out.println("RACE firmware without a map (track_map.h not found): normal driving");
#endif
}

void loop() {
  service();

  uint32_t now = millis();
  if (now - lastLoopMs < LOOP_PERIOD_MS) return;
  lastLoopMs = now;

  if (paused) {
    stopMotors();
#if TRACK_LEARN_MODE
    if (learnDone) digitalWrite(PIN_LED, (now / 500) % 2);  // slow blink: map saved
#endif
    return;
  }

  // 1. Move the line model by how the robot moved since the last step:
  //    driving forward slides the crossing point along the line's angle, and
  //    turning swings the sensor row (SENSOR_AHEAD_MM in front of the axle).
  float ds, dth;
  odometry(ds, dth);
  lineX += ds * tanf(lineAngle) - SENSOR_AHEAD_MM * dth;
  lineAngle = constrain(lineAngle - dth, -MAX_LINE_ANGLE, MAX_LINE_ANGLE);
  sinceCornerMm += fabsf(ds);
  junctionLeftMm = max(0.0f, junctionLeftMm - fabsf(ds));
  trackUpdate(ds, dth);

  // 2. Read the sensors.
  int pos = 0;
  uint8_t mask = 0;
  float measX = 0;
  LineEvent ev = readLine(pos, mask, measX);
  digitalWrite(PIN_LED, ev != EV_NONE);
  trackEvent(ev, false, ev == EV_NONE);

  // S5 on its own while the line was left of S4: almost certainly the floor
  // (tile grout), not the line. Ignore it.
  if (USE_S5 && mask == (1 << 4) && lineX < SENSOR_X_MM[3]) {
    ev = EV_NONE;
    mask = 0;
  }

  // Remember brief touches of the outermost sensors (raw, unfiltered).
  // S1 always counts; S5 only when the line was already right of centre.
  const uint8_t leftOuter  = USE_S1 ? (1 << 0) : (1 << 1);
  const uint8_t rightOuter = USE_S5 ? (1 << 4) : (1 << 3);
  if (rawMask & leftOuter) leftEdgeSeenMm = runDistMm;
  if ((rawMask & rightOuter) && (!USE_S5 || lineX > S5_TRUST_MM)) rightEdgeSeenMm = runDistMm;

  // 3a. Braking after a pivot: short-brake briefly so the rotation stops.
  if (now < brakeUntilMs) {
    stopMotors();
    watchPrint(now, mask, ev, "brake");
    return;
  }

  // 3b. A pivot is in progress and a sensor sees the line again: keep turning
  //     (slower) until a centre sensor has it, then brake and hand over.
  if (ev != EV_NONE && turnDir != 0) {
    bool centre = mask & 0b01110;  // S2, S3 or S4
    float turned = fabsf(runHeading - turnStartHeading) * 180.0f / PI;
    if (!centre && turned < SEARCH_MAX_TURN_DEG) {
      int sp = (int)(searchSpeed() * PIVOT_FIND_FACTOR);
      setMotors(turnDir * sp, -turnDir * sp);
      watchPrint(now, mask, ev, "turn-find");
      return;
    }
    turnDir = 0;
    brakeUntilMs = now + PIVOT_BRAKE_MS;
    postTurnLeftMm = POST_TURN_MM;
    stopMotors();
    lost = false;
    lastError = pos;
    integral = 0;
    haveMeas = false;
    lineX = measX;
    watchPrint(now, mask, ev, "brake");
    return;
  }

  // 3. Line (or a feature) seen.
  if (ev != EV_NONE) {
    if (lost) {            // just found it again: no derivative kick
      lost = false;
      lastError = pos;
      integral = 0;
      haveMeas = false;
      recoverLeftMm = RECOVER_MM;  // settle at reduced speed first
    }
    setMode(MODE_FOLLOW);

    if (ev == EV_JUNCTION) {
      junctionLeftMm = JUNCTION_HOLD_MM;
      lineX = 0;
      lineAngle = 0;
    } else if (ev == EV_CORNER_LEFT || ev == EV_CORNER_RIGHT) {
      cornerDir = ev == EV_CORNER_RIGHT ? 1 : -1;
      sinceCornerMm = 0;
      lineX = measX;
      lineAngle = cornerDir * MAX_LINE_ANGLE;  // the branch runs sideways
      haveMeas = false;
    } else {
      // Normal line: learn its angle from how its position changed, after
      // removing the part caused by the robot's own turning.
      if (haveMeas && fabsf(ds) > 0.5f) {
        float obs = atanf((measX - prevMeasX + SENSOR_AHEAD_MM * dth) / ds);
        lineAngle = constrain(0.8f * lineAngle + 0.2f * obs, -MAX_LINE_ANGLE, MAX_LINE_ANGLE);
      }
      lineX = measX;
      prevMeasX = measX;
      haveMeas = true;
    }

    if (junctionLeftMm > 0) {
      // Through a junction: steer with the centre sensors only, so the side
      // branches don't pull the robot off course.
      long sum = 0;
      int n = 0;
      for (uint8_t i = 1; i <= 3; i++)
        if (mask & (1 << i)) { sum += SENSOR_WEIGHT[i]; n++; }
      steer(n ? (float)(sum / n) : 0.0f, runBase());
      watchPrint(now, mask, ev, "junction");
    } else if (ev == EV_CORNER_LEFT || ev == EV_CORNER_RIGHT) {
      steer(cornerDir * 2000.0f, curveBase(2000));
      watchPrint(now, mask, ev, "corner");
    } else {
      steer(pos, curveBase(pos));
      watchPrint(now, mask, ev, "follow");
    }
    return;
  }

  // 4. No sensor sees the line. Never stop: use the line model.
  setMode(MODE_LOST);
  if (!lost) {
    lost = true;
    lostDistMm = 0;
    lostTurnDeg = 0;
    lossX = lineX;
    lossAngle = lineAngle;
    sweepStartMs = 0;
    lostStartMs = now;
  }

#if TRACK_LEARN_MODE
  // Learning run: the line ending for a while means the course is finished.
  if (now - lostStartMs > LEARN_END_LOST_MS) {
    learnFinish(Serial);
    return;
  }
#endif
  lostDistMm += fabsf(ds);
  lostTurnDeg += fabsf(dth) * 180.0f / PI;

  // 4a. An outer sensor touched the line just before it vanished: the line
  //     turned that way. Pivot toward that side (the most recent one).
  {
    float leftAge  = runDistMm - leftEdgeSeenMm;
    float rightAge = runDistMm - rightEdgeSeenMm;
    float age = min(leftAge, rightAge);
    if (age < SIDE_MEMORY_MM && lostTurnDeg < SEARCH_MAX_TURN_DEG) {
      turnPivot(leftAge <= rightAge ? -1 : 1);
      watchPrint(now, mask, ev, leftAge <= rightAge ? "turnL" : "turnR");
      return;
    }
  }

  // 4b. Corner just seen: pivot toward it.
  if (sinceCornerMm < CORNER_MEMORY_MM && lostTurnDeg < SEARCH_MAX_TURN_DEG) {
    // Arc toward the corner: keeps some forward motion instead of stopping
    // to spin in place.
    if (CORNER_INNER_FACTOR <= -1.0f) {
      turnPivot(cornerDir);
    } else {
      int outer = searchSpeed(), inner = (int)(searchSpeed() * CORNER_INNER_FACTOR);
      if (cornerDir > 0) setMotors(outer, inner); else setMotors(inner, outer);
    }
    watchPrint(now, mask, ev, "corner>");
    return;
  }

  // 4c. Gap or dashed line: it vanished near the centre, running straight ahead,
  //     and no outer sensor touched the line recently.
  bool gapLike = fabsf(lossX) < GAP_CENTER_MM &&
                 fabsf(lossAngle) < GAP_MAX_ANGLE_DEG * PI / 180.0f;
  if (gapLike && lostDistMm < GAP_MAX_MM) {
    trackEvent(ev, true, true);
    setMotors(runBase(), runBase());
    watchPrint(now, mask, ev, "gap");
    return;
  }

  // 4d. Steer to where the model says the line is now.
  if (lostTurnDeg < SEARCH_MAX_TURN_DEG && lostDistMm < PREDICT_MAX_MM) {
    if (lineX > coverRightMm + PIVOT_MARGIN_MM) {
      turnPivot(1);
    } else if (lineX < coverLeftMm - PIVOT_MARGIN_MM) {
      turnPivot(-1);
    } else {
      turnDir = 0;
      float err = lineX * 1000.0f / BFD_PITCH_MM;
      steer(err, min(curveBase(err), (int)(runBase() * LOST_SPEED_FACTOR)));
    }
    watchPrint(now, mask, ev, "predict");
    return;
  }

  // 4e. Prediction failed: sweep left and right with growing sweeps,
  //     first back the other way.
  if (sweepStartMs == 0) sweepStartMs = now;
  uint32_t t = now - sweepStartMs;
  uint32_t len = SWEEP_FIRST_MS, start = 0;
  int dir = lineX >= 0 ? -1 : 1;
  while (t >= start + len) { start += len; len *= 2; dir = -dir; }
  pivot(dir);
  watchPrint(now, mask, ev, "sweep");
}
