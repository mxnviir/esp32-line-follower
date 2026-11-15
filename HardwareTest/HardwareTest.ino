/*
 * ESP32 Line Follower — hardware test
 *
 *  - Blue LED (GPIO2) blinks each time a sensor newly detects the line.
 *  - Both motors run forward, stop, backward, stop, on repeat.
 *  - Sensor states and detections are printed on Serial (115200).
 *
 * Sensors (left -> right):  S1=D15  S2=D33  S3=D32  S4=D35  S5=D34 (DISABLED: broken)
 * TB6612FNG:  PWMA=D18 AIN1=D19 AIN2=D21  |  PWMB=D23 BIN1=D22 BIN2=D5  |  STBY=D25
 */

#include <Arduino.h>

// ============================== CONFIG ======================================

#define USE_S5 0  // S5 is broken

// Set true if sensor output is HIGH when over the black line.
const bool LINE_IS_HIGH = true;

const int      TEST_SPEED   = 150;   // 0-255
const uint32_t RUN_MS       = 1000;  // time driving in each direction
const uint32_t PAUSE_MS     = 300;   // stop between direction changes
const uint32_t BLINK_MS     = 80;    // LED on-time per detection

// ============================== PINS ========================================

const uint8_t NUM_SENSORS = 5;
const uint8_t SENSOR_PINS[NUM_SENSORS]    = {15, 33, 32, 35, 34};
const bool    SENSOR_ENABLED[NUM_SENSORS] = {true, true, true, true, USE_S5};

const uint8_t PIN_LED  = 2;

const uint8_t PIN_PWMA = 18;
const uint8_t PIN_AIN1 = 19;
const uint8_t PIN_AIN2 = 21;
const uint8_t PIN_PWMB = 23;
const uint8_t PIN_BIN1 = 22;
const uint8_t PIN_BIN2 = 5;
const uint8_t PIN_STBY = 25;

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

void driveOne(int speed, uint8_t in1, uint8_t in2, uint8_t pwmPin, uint8_t ch) {
  speed = constrain(speed, -255, 255);
  if (speed > 0) {
    digitalWrite(in1, HIGH);
    digitalWrite(in2, LOW);
  } else if (speed < 0) {
    digitalWrite(in1, LOW);
    digitalWrite(in2, HIGH);
  } else {
    digitalWrite(in1, HIGH);
    digitalWrite(in2, HIGH);
  }
  pwmWrite(pwmPin, ch, abs(speed));
}

void setMotors(int left, int right) {
  driveOne(left,  PIN_AIN1, PIN_AIN2, PIN_PWMA, PWM_CH_A);
  driveOne(right, PIN_BIN1, PIN_BIN2, PIN_PWMB, PWM_CH_B);
}

// ============================== STATE =======================================

bool     lastOnLine[NUM_SENSORS] = {false};
uint32_t ledOffAt = 0;

// Motor test sequence: forward -> stop -> backward -> stop
const int      PHASE_SPEED[4] = {TEST_SPEED, 0, -TEST_SPEED, 0};
const uint32_t PHASE_MS[4]    = {RUN_MS, PAUSE_MS, RUN_MS, PAUSE_MS};
const char*    PHASE_NAME[4]  = {"FORWARD", "STOP", "BACKWARD", "STOP"};
uint8_t  phase = 0;
uint32_t phaseStart = 0;

// ============================== SETUP / LOOP ================================

void setup() {
  pinMode(PIN_STBY, OUTPUT);
  digitalWrite(PIN_STBY, LOW);

  pinMode(PIN_AIN1, OUTPUT);
  pinMode(PIN_AIN2, OUTPUT);
  pinMode(PIN_BIN1, OUTPUT);
  pinMode(PIN_BIN2, OUTPUT);
  pwmInit();
  setMotors(0, 0);

  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);

  for (uint8_t i = 0; i < NUM_SENSORS; i++) {
    if (SENSOR_ENABLED[i]) pinMode(SENSOR_PINS[i], INPUT);
  }

  Serial.begin(115200);
  Serial.println("Hardware test: S5 disabled. Motors start in 2 s.");
  delay(2000);

  digitalWrite(PIN_STBY, HIGH);
  phaseStart = millis();
  setMotors(PHASE_SPEED[phase], PHASE_SPEED[phase]);
  Serial.println(PHASE_NAME[phase]);
}

void loop() {
  uint32_t now = millis();

  // ---- Sensors: blink LED on each new detection ----
  for (uint8_t i = 0; i < NUM_SENSORS; i++) {
    if (!SENSOR_ENABLED[i]) continue;
    bool onLine = (digitalRead(SENSOR_PINS[i]) == HIGH) == LINE_IS_HIGH;
    if (onLine && !lastOnLine[i]) {
      digitalWrite(PIN_LED, HIGH);
      ledOffAt = now + BLINK_MS;
      Serial.printf("S%u detected\n", i + 1);
    }
    lastOnLine[i] = onLine;
  }
  if (ledOffAt && (int32_t)(now - ledOffAt) >= 0) {
    digitalWrite(PIN_LED, LOW);
    ledOffAt = 0;
  }

  // ---- Motors: alternate forward / backward ----
  if (now - phaseStart >= PHASE_MS[phase]) {
    phase = (phase + 1) % 4;
    phaseStart = now;
    setMotors(PHASE_SPEED[phase], PHASE_SPEED[phase]);
    Serial.println(PHASE_NAME[phase]);
  }

  delay(2);  // light debounce
}
