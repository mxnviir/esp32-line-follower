/*
 * ESP32 Line Follower — 5-channel IR array + TB6612FNG
 *
 * Sensors (left -> right):  S1=D15  S2=D33  S3=D32  S4=D35  S5=D34 (DISABLED: broken)
 * TB6612FNG:  PWMA=D18 AIN1=D19 AIN2=D21  |  PWMB=D23 BIN1=D22 BIN2=D5  |  STBY=D25
 *
 * NOTE: GPIO34/35 are input-only with no internal pull-ups; fine for sensor
 *       modules that drive their own output.
 *
 * Works with ESP32 Arduino core 1.x/2.x and 3.x (LEDC API differs; handled below).
 */

#include <Arduino.h>

// ============================== CONFIG ======================================

// ---- Sensor S5 is broken: keep at 0 until it's replaced -------------------
#define USE_S5 0

// Set true if sensor output is HIGH when over the black line (most TCRT5000 /
// LM393 modules). Set false if your modules output LOW on the line.
const bool LINE_IS_HIGH = true;

// Assumes motor A = left wheel, motor B = right wheel.
// Flip these if a wheel spins backwards when it should go forward.
const bool INVERT_LEFT  = false;
const bool INVERT_RIGHT = false;

// Speeds (0-255)
const int BASE_SPEED   = 150;  // straight-line cruise speed
const int MAX_SPEED    = 255;
const int SEARCH_SPEED = 140;  // spin speed when line is lost

// PID gains (error range is about -2000..+2000)
float Kp = 0.08f;
float Ki = 0.0f;
float Kd = 0.6f;

const uint32_t LOOP_PERIOD_MS  = 5;     // control loop rate (200 Hz)
const uint32_t LOST_TIMEOUT_MS = 3000;  // stop motors if line lost this long
const uint32_t START_DELAY_MS  = 2000;  // time to place the bot after reset

#define DEBUG_SERIAL 0  // 1 = print sensor/PID data (slows loop a bit)

// ============================== PINS ========================================

const uint8_t NUM_SENSORS = 5;
const uint8_t SENSOR_PINS[NUM_SENSORS]    = {15, 33, 32, 35, 34};
const bool    SENSOR_ENABLED[NUM_SENSORS] = {true, true, true, true, USE_S5};
const int     SENSOR_WEIGHT[NUM_SENSORS]  = {-2000, -1000, 0, 1000, 2000};

const uint8_t PIN_PWMA = 18;
const uint8_t PIN_AIN1 = 19;
const uint8_t PIN_AIN2 = 21;
const uint8_t PIN_PWMB = 23;
const uint8_t PIN_BIN1 = 22;
const uint8_t PIN_BIN2 = 5;
const uint8_t PIN_STBY = 25;

// ============================== PWM =========================================

const uint32_t PWM_FREQ = 20000;  // 20 kHz: above audible range
const uint8_t  PWM_RES  = 8;      // 0-255
const uint8_t  PWM_CH_A = 0;      // used only on core < 3.0
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
void driveOne(int speed, uint8_t in1, uint8_t in2, uint8_t pwmPin, uint8_t ch) {
  speed = constrain(speed, -MAX_SPEED, MAX_SPEED);
  if (speed > 0) {
    digitalWrite(in1, HIGH);
    digitalWrite(in2, LOW);
  } else if (speed < 0) {
    digitalWrite(in1, LOW);
    digitalWrite(in2, HIGH);
  } else {
    // short brake
    digitalWrite(in1, HIGH);
    digitalWrite(in2, HIGH);
  }
  pwmWrite(pwmPin, ch, abs(speed));
}

void setMotors(int left, int right) {
  if (INVERT_LEFT)  left  = -left;
  if (INVERT_RIGHT) right = -right;
  driveOne(left,  PIN_AIN1, PIN_AIN2, PIN_PWMA, PWM_CH_A);
  driveOne(right, PIN_BIN1, PIN_BIN2, PIN_PWMB, PWM_CH_B);
}

void stopMotors() { setMotors(0, 0); }

// ============================== SENSORS =====================================

// Returns true if any enabled sensor sees the line; writes weighted position.
// pos < 0 => line is to the left, pos > 0 => line is to the right.
bool readLine(int &pos, uint8_t &mask) {
  long sum = 0;
  int count = 0;
  mask = 0;
  for (uint8_t i = 0; i < NUM_SENSORS; i++) {
    if (!SENSOR_ENABLED[i]) continue;
    bool onLine = (digitalRead(SENSOR_PINS[i]) == HIGH) == LINE_IS_HIGH;
    if (onLine) {
      sum += SENSOR_WEIGHT[i];
      count++;
      mask |= (1 << i);
    }
  }
  if (count == 0) return false;
  pos = sum / count;
  return true;
}

// ============================== STATE =======================================

float lastError = 0;
float integral = 0;
uint32_t lastSeenMs = 0;
uint32_t lastLoopMs = 0;

// ============================== SETUP / LOOP ================================

void setup() {
  // Hold driver in standby until everything is configured
  pinMode(PIN_STBY, OUTPUT);
  digitalWrite(PIN_STBY, LOW);

  pinMode(PIN_AIN1, OUTPUT);
  pinMode(PIN_AIN2, OUTPUT);
  pinMode(PIN_BIN1, OUTPUT);
  pinMode(PIN_BIN2, OUTPUT);
  pwmInit();
  stopMotors();

  for (uint8_t i = 0; i < NUM_SENSORS; i++) {
    if (SENSOR_ENABLED[i]) pinMode(SENSOR_PINS[i], INPUT);
  }

  Serial.begin(115200);
  Serial.println("Line follower: S5 disabled. Starting...");

  delay(START_DELAY_MS);
  digitalWrite(PIN_STBY, HIGH);
  lastSeenMs = millis();
  lastLoopMs = millis();
}

void loop() {
  uint32_t now = millis();
  if (now - lastLoopMs < LOOP_PERIOD_MS) return;
  lastLoopMs = now;

  int pos = 0;
  uint8_t mask = 0;
  bool found = readLine(pos, mask);

  if (!found) {
    // Line lost: spin toward the side it was last seen; give up after timeout.
    if (now - lastSeenMs > LOST_TIMEOUT_MS) {
      stopMotors();
    } else if (lastError > 0) {
      setMotors(SEARCH_SPEED, -SEARCH_SPEED);   // turn right
    } else if (lastError < 0) {
      setMotors(-SEARCH_SPEED, SEARCH_SPEED);   // turn left
    } else {
      setMotors(BASE_SPEED / 2, BASE_SPEED / 2); // was centred: creep forward
    }
#if DEBUG_SERIAL
    Serial.println("LOST");
#endif
    return;
  }

  lastSeenMs = now;

  float error = pos;
  integral = constrain(integral + error, -10000.0f, 10000.0f);
  float derivative = error - lastError;
  float correction = Kp * error + Ki * integral + Kd * derivative;
  lastError = error;

  // error > 0 => line on the right => speed up left, slow right
  int left  = BASE_SPEED + (int)correction;
  int right = BASE_SPEED - (int)correction;
  setMotors(left, right);

#if DEBUG_SERIAL
  for (uint8_t i = 0; i < NUM_SENSORS; i++) {
    Serial.print(SENSOR_ENABLED[i] ? ((mask >> i) & 1 ? '1' : '0') : 'x');
  }
  Serial.printf("  pos=%5d  corr=%7.1f  L=%4d R=%4d\n", pos, correction, left, right);
#endif
}
