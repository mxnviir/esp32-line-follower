/*
 * ESP32 Line Follower — board diagnostics
 *
 * 1. Chip / reset-reason / clock report
 * 2. RAM test (heap blocks written and verified with patterns)
 * 3. Flash test (MD5 of the running sketch read back from flash)
 * 4. Motor pin self-test: drives each TB6612 control pin HIGH then LOW and
 *    reads the pad back. A mismatch means the pin is shorted or overloaded.
 * 5. Slow motor drive for multimeter checks: both motors full forward 5 s,
 *    stop 2 s, full reverse 5 s, stop 2 s, repeat. Pin levels are printed.
 * 6. Reset log kept in flash (NVS), so it survives power loss: every boot
 *    records its reset reason, pin-test result, and how long the previous run
 *    lasted (uptime saved every 2 s) and which motor phase it was in.
 *    The log is printed at every boot. Serial commands: 'd' = dump, 'c' = clear.
 *    Flashing a new build clears the log automatically.
 *
 * TB6612FNG:  PWMA=D18 AIN1=D19 AIN2=D21  |  PWMB=D23 BIN1=D22 BIN2=D5  |  STBY=D25
 */

#include <Arduino.h>
#include <esp_system.h>
#include <esp_chip_info.h>
#include <driver/gpio.h>
#include <Preferences.h>

const uint8_t PIN_PWMA = 18;
const uint8_t PIN_AIN1 = 19;
const uint8_t PIN_AIN2 = 21;
const uint8_t PIN_PWMB = 23;
const uint8_t PIN_BIN1 = 22;
const uint8_t PIN_BIN2 = 5;
const uint8_t PIN_STBY = 25;

const uint8_t MOTOR_PINS[] = {PIN_STBY, PIN_PWMA, PIN_AIN1, PIN_AIN2, PIN_PWMB, PIN_BIN1, PIN_BIN2};
const char*   MOTOR_NAMES[] = {"STBY", "PWMA", "AIN1", "AIN2", "PWMB", "BIN1", "BIN2"};
const uint8_t NUM_MOTOR_PINS = sizeof(MOTOR_PINS);

const char* resetReasonName(esp_reset_reason_t r) {
  switch (r) {
    case ESP_RST_POWERON:  return "power-on";
    case ESP_RST_EXT:      return "external pin";
    case ESP_RST_SW:       return "software";
    case ESP_RST_PANIC:    return "PANIC (crash)";
    case ESP_RST_INT_WDT:  return "interrupt watchdog";
    case ESP_RST_TASK_WDT: return "task watchdog";
    case ESP_RST_WDT:      return "other watchdog";
    case ESP_RST_BROWNOUT: return "BROWNOUT (supply voltage dipped)";
    case ESP_RST_DEEPSLEEP:return "deep sleep wake";
    default:               return "unknown";
  }
}

// ============================== RESET LOG ===================================

struct LogEntry {
  uint32_t boot;          // boot number since log was cleared
  uint32_t prevUptimeMs;  // how long the previous run lasted (last saved value)
  uint8_t  reason;        // esp_reset_reason_t of this boot
  uint8_t  pinsOk;        // motor pin self-test result this boot
  uint8_t  prevPhase;     // motor phase the previous run was in when it ended
  uint8_t  pad;
};

const int      LOG_SIZE        = 32;      // ring buffer of the last 32 boots
const uint32_t UPTIME_SAVE_MS  = 2000;
const char*    PHASE_NAMES[]   = {"FORWARD", "STOP", "REVERSE", "STOP", "setup"};
const uint8_t  PHASE_SETUP     = 4;

Preferences prefs;
LogEntry logBuf[LOG_SIZE];
uint32_t bootCount = 0;   // total boots since clear
uint32_t logHead   = 0;   // number of entries ever written

void logLoad() {
  memset(logBuf, 0, sizeof(logBuf));
  bootCount = prefs.getUInt("boots", 0);
  logHead   = prefs.getUInt("head", 0);
  prefs.getBytes("log", logBuf, sizeof(logBuf));
}

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
    Serial.printf("  boot #%-3lu reason: %-32s pins:%s | previous run lasted %lu.%lu s, ended in %s\n",
                  (unsigned long)e.boot, resetReasonName(r), e.pinsOk ? "OK  " : "FAIL",
                  (unsigned long)(e.prevUptimeMs / 1000), (unsigned long)(e.prevUptimeMs % 1000 / 100),
                  e.prevPhase <= PHASE_SETUP ? PHASE_NAMES[e.prevPhase] : "-");
  }
  Serial.printf("Brownouts: %lu | Crashes/watchdogs: %lu\n", (unsigned long)brownouts, (unsigned long)crashes);
  Serial.println("------------------------------------");
}

void logBoot(esp_reset_reason_t reason, bool pinsOk) {
  LogEntry e = {};
  e.boot         = ++bootCount;
  e.prevUptimeMs = prefs.getUInt("uptime", 0);
  e.prevPhase    = prefs.getUChar("phase", PHASE_SETUP);
  e.reason       = (uint8_t)reason;
  e.pinsOk       = pinsOk;
  logBuf[logHead % LOG_SIZE] = e;
  logHead++;
  prefs.putBytes("log", logBuf, sizeof(logBuf));
  prefs.putUInt("head", logHead);
  prefs.putUInt("boots", bootCount);
  prefs.putUInt("uptime", 0);
  prefs.putUChar("phase", PHASE_SETUP);
}

// ============================== TESTS =======================================

bool ramTest() {
  const size_t BLOCK = 32 * 1024;
  const int    MAX_BLOCKS = 16;
  uint32_t* blocks[MAX_BLOCKS] = {nullptr};
  int n = 0;
  bool ok = true;

  // Grab as much heap as we reasonably can in 32 KB chunks
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
  return high == 1 && low == 0;
}

void pinWrite(uint8_t pin, int level) { gpio_set_level((gpio_num_t)pin, level); }

void setDir(uint8_t in1, uint8_t in2, int dir) {
  pinWrite(in1, dir >= 0 ? 1 : 0);  // fwd: H/L, rev: L/H, stop: H/H (brake)
  pinWrite(in2, dir <= 0 ? 1 : 0);
}

void drive(int dir) {
  setDir(PIN_AIN1, PIN_AIN2, dir);
  setDir(PIN_BIN1, PIN_BIN2, dir);
  // PWM pins held fully on (plain digital, no LEDC) so they're easy to measure
  pinWrite(PIN_PWMA, dir != 0 ? 1 : 0);
  pinWrite(PIN_PWMB, dir != 0 ? 1 : 0);
}

void printLevels(const char* label) {
  Serial.printf("[%s] ", label);
  for (uint8_t i = 0; i < NUM_MOTOR_PINS; i++)
    Serial.printf("%s=%d ", MOTOR_NAMES[i], gpio_get_level((gpio_num_t)MOTOR_PINS[i]));
  Serial.println();
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n===== ESP32 DIAGNOSTICS =====");

  // ---- 1. Chip info ----
  esp_chip_info_t info;
  esp_chip_info(&info);
  Serial.printf("Chip: %s rev %d, %d cores, CPU %lu MHz, XTAL %lu MHz\n",
                ESP.getChipModel(), ESP.getChipRevision(), info.cores,
                (unsigned long)getCpuFrequencyMhz(), (unsigned long)getXtalFrequencyMhz());
  esp_reset_reason_t reason = esp_reset_reason();
  Serial.printf("Reset reason: %s\n", resetReasonName(reason));
  Serial.printf("Flash: %lu KB @ %lu MHz | Heap: %lu KB free (%lu KB total) | PSRAM: %lu KB\n",
                (unsigned long)(ESP.getFlashChipSize() / 1024),
                (unsigned long)(ESP.getFlashChipSpeed() / 1000000),
                (unsigned long)(ESP.getFreeHeap() / 1024),
                (unsigned long)(ESP.getHeapSize() / 1024),
                (unsigned long)(ESP.getPsramSize() / 1024));

  // ---- 2. RAM ----
  Serial.println("RAM test...");
  Serial.println(ramTest() ? "RAM: PASS" : "RAM: FAIL");

  // ---- 3. Flash ----
  Serial.println("Flash read test...");
  String md5a = ESP.getSketchMD5();  // reads the whole sketch back from flash
  Serial.printf("Sketch MD5: %s (size %lu bytes)\n", md5a.c_str(), (unsigned long)ESP.getSketchSize());
  Serial.println(md5a.length() == 32 ? "FLASH: PASS (sketch read back OK)" : "FLASH: FAIL");

  // ---- 4. Motor pin self-test ----
  Serial.println("Motor pin self-test (drive HIGH/LOW, read pad back)...");
  bool allPins = true;
  for (uint8_t i = 0; i < NUM_MOTOR_PINS; i++) {
    bool ok = pinSelfTest(MOTOR_PINS[i]);
    allPins &= ok;
    Serial.printf("  %-4s GPIO%-2d : %s\n", MOTOR_NAMES[i], MOTOR_PINS[i],
                  ok ? "OK" : "FAIL (shorted/overloaded or damaged)");
  }
  Serial.println(allPins ? "PINS: PASS" : "PINS: FAIL");

  // ---- 6. Reset log ----
  prefs.begin("diaglog", false);
  if (prefs.getString("build", "") != String(__DATE__ " " __TIME__)) {
    Serial.println("New firmware build: clearing reset log.");
    logClear();
  }
  logLoad();
  logBoot(reason, allPins);
  logDump();

  // Leave pins as outputs that can still be read back
  for (uint8_t i = 0; i < NUM_MOTOR_PINS; i++) {
    gpio_set_direction((gpio_num_t)MOTOR_PINS[i], GPIO_MODE_INPUT_OUTPUT);
    gpio_set_level((gpio_num_t)MOTOR_PINS[i], 0);
  }

  Serial.println("===== DIAGNOSTICS DONE =====");
  Serial.println("Motor drive: FWD 5s / STOP 2s / REV 5s / STOP 2s (PWM pins held fully HIGH)");
  Serial.println("Commands: 'd' = dump reset log, 'c' = clear reset log");
  pinWrite(PIN_STBY, 1);
}

const int      PHASE_DIR[4] = {1, 0, -1, 0};
const uint32_t PHASE_MS[4]  = {5000, 2000, 5000, 2000};
int8_t   phase = -1;
uint32_t phaseStart = 0;
uint32_t lastSave = 0;

void loop() {
  uint32_t now = millis();

  if (phase < 0 || now - phaseStart >= PHASE_MS[phase]) {
    phase = (phase + 1) % 4;
    phaseStart = now;
    drive(PHASE_DIR[phase]);
    printLevels(PHASE_NAMES[phase]);
    prefs.putUChar("phase", phase);
  }

  if (now - lastSave >= UPTIME_SAVE_MS) {
    lastSave = now;
    prefs.putUInt("uptime", now);
  }

  while (Serial.available()) {
    char c = Serial.read();
    if (c == 'd') logDump();
    if (c == 'c') { logClear(); Serial.println("Reset log cleared."); }
  }
}
