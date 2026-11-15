/*
 * ESP32 Line Follower — live sensor monitor
 *
 * Prints S1-S5 digital levels and the raw voltage on each pin ~10x per second.
 * Motors are kept in standby (STBY LOW) so the bot can't move.
 *
 * Sensors (left -> right):  S1=D15  S2=D33  S3=D32  S4=D35  S5=D34
 */

#include <Arduino.h>

const uint8_t NUM_SENSORS = 5;
const uint8_t SENSOR_PINS[NUM_SENSORS] = {15, 33, 32, 35, 34};
const uint8_t PIN_STBY = 25;

void setup() {
  pinMode(PIN_STBY, OUTPUT);
  digitalWrite(PIN_STBY, LOW);  // motors off

  Serial.begin(115200);
  analogReadResolution(12);
}

void loop() {
  for (uint8_t i = 0; i < NUM_SENSORS; i++) {
    // Arduino Serial Plotter format: "S1:1234,S2:...", values in millivolts
    uint32_t mv = analogReadMilliVolts(SENSOR_PINS[i]);
    Serial.printf("%sS%u:%lu", i ? "," : "", i + 1, (unsigned long)mv);
  }
  Serial.println();
  delay(100);
}
