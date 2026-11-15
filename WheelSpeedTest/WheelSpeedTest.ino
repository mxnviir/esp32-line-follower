/*
 * ESP32 Line Follower — wheel speed test
 *
 * Compares the two wheels at the same power. Lift the bot so the wheels
 * spin freely, put a tape marker on each wheel, and count (or film) the turns.
 *
 *   LED blinks 3 s       -> get ready
 *   LED slow blink 10 s  -> both motors forward at HALF power (128)
 *   LED off 3 s          -> stopped
 *   LED solid 10 s       -> both motors forward at FULL power (255)
 *   LED off 8 s          -> stopped, then repeats
 *
 * Both motors always get identical commands (no scaling), so any speed
 * difference you see is hardware: motor, gearbox, wiring or driver channel.
 *
 * TB6612FNG:  PWMA=D18 AIN1=D19 AIN2=D21  |  PWMB=D23 BIN1=D22 BIN2=D5  |  STBY=D25
 */

#include <Arduino.h>

const int      HALF_SPEED = 128;    // same PWM for both motors (0-255)
const int      FULL_SPEED = 255;
const uint32_t READY_MS   = 3000;
const uint32_t RUN_MS     = 10000;
const uint32_t GAP_MS     = 3000;
const uint32_t REST_MS    = 8000;

const bool INVERT_LEFT  = false;
const bool INVERT_RIGHT = false;  // matches the line follower

const uint8_t PIN_LED  = 2;
const uint8_t PIN_PWMA = 18;
const uint8_t PIN_AIN1 = 19;
const uint8_t PIN_AIN2 = 21;
const uint8_t PIN_PWMB = 23;
const uint8_t PIN_BIN1 = 22;
const uint8_t PIN_BIN2 = 5;
const uint8_t PIN_STBY = 25;

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
  if (INVERT_LEFT)  left  = -left;
  if (INVERT_RIGHT) right = -right;
  driveOne(left,  PIN_AIN1, PIN_AIN2, PIN_PWMA, PWM_CH_A);
  driveOne(right, PIN_BIN1, PIN_BIN2, PIN_PWMB, PWM_CH_B);
}

void setup() {
  pinMode(PIN_STBY, OUTPUT);
  digitalWrite(PIN_STBY, LOW);
  pinMode(PIN_AIN1, OUTPUT);
  pinMode(PIN_AIN2, OUTPUT);
  pinMode(PIN_BIN1, OUTPUT);
  pinMode(PIN_BIN2, OUTPUT);
  pinMode(PIN_LED, OUTPUT);
  pwmInit();
  setMotors(0, 0);

  Serial.begin(115200);
  delay(300);
  Serial.println("\nWheel speed test: both motors get identical commands, no scaling.");
  Serial.println("Count each wheel's turns at half power, then at full power.");
  digitalWrite(PIN_STBY, HIGH);
}

// Ramp both motors to the same speed, hold, then stop
void runBoth(const char* label, int speed, bool blink) {
  Serial.printf("RUN %s (PWM %d on both): start counting now\n", label, speed);
  for (int s = 0; s <= speed; s += 10) {
    setMotors(s, s);
    delay(5);
  }
  setMotors(speed, speed);
  for (uint32_t t = 0; t < RUN_MS; t += 500) {
    digitalWrite(PIN_LED, blink ? (t / 500) % 2 : HIGH);
    if (t % 1000 == 0) Serial.printf("  %lu s left\n", (unsigned long)((RUN_MS - t) / 1000));
    delay(500);
  }
  setMotors(0, 0);
  digitalWrite(PIN_LED, LOW);
  Serial.printf("STOP %s: note the counts.\n", label);
}

void loop() {
  Serial.println("Get ready...");
  for (uint32_t t = 0; t < READY_MS; t += 250) {
    digitalWrite(PIN_LED, (t / 250) % 2);
    delay(250);
  }
  digitalWrite(PIN_LED, LOW);

  runBoth("HALF", HALF_SPEED, true);
  delay(GAP_MS);
  runBoth("FULL", FULL_SPEED, false);
  Serial.println("Next cycle in 8 s.");
  delay(REST_MS);
}
