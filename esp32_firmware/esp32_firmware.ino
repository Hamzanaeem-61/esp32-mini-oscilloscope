/*
 * ESP32 Mini Oscilloscope — Firmware
 * -----------------------------------
 * Samples an analog signal on GPIO34 (ADC1_CH6) and streams the data
 * to a PC over USB serial in binary frames. The companion Python app
 * (pc_app/oscilloscope_gui.py) receives the stream and draws it like
 * a real oscilloscope.
 *
 * WIRING
 *   Signal (0-3.3V only!) --> GPIO34
 *   GND                   --> GND (common with the signal source)
 *
 * IMPORTANT: the ESP32 ADC input must stay within 0-3.3V at all times,
 * or you risk damaging the chip. For larger or AC-coupled signals, use
 * an attenuator / level-shifter first — see README.md for a simple
 * voltage-divider + offset circuit.
 *
 * SERIAL PROTOCOL (binary, little-endian), one frame per packet:
 *   bytes 0-1   : header  0xAA 0x55
 *   bytes 2-3   : uint16  number of samples in this frame (N)
 *   bytes 4-7   : uint32  sample interval in microseconds
 *   bytes 8..   : N * uint16  raw ADC samples (0-4095)
 *   last 2 bytes: uint16  checksum (sum of all sample values, low 16 bits)
 *
 * COMMANDS FROM PC (single ASCII byte over serial):
 *   'G'      -> start/continue streaming
 *   'S'      -> stop streaming
 *   '0'-'9'  -> select sample-rate preset (index into SAMPLE_INTERVALS_US)
 */

#include <Arduino.h>

#define ADC_PIN 34
#define FRAME_SAMPLES 512
#define BAUD_RATE 921600

// Preset sample intervals in microseconds ("time/div" control).
// Actual achievable minimum is limited by ADC conversion + loop
// overhead (~15-20us on ESP32), so index 0 already runs close to the
// practical ceiling (~50 kSa/s). See README for how to go faster with
// I2S/DMA sampling.
const uint32_t SAMPLE_INTERVALS_US[10] = {
  20, 40, 80, 160, 320, 640, 1280, 2560, 5120, 10240
};

volatile uint32_t sampleIntervalUs = SAMPLE_INTERVALS_US[4]; // default ~320us
volatile bool streaming = false;

uint16_t buffer[FRAME_SAMPLES];

void setup() {
  Serial.begin(BAUD_RATE);
  analogReadResolution(12);        // 0-4095
  analogSetAttenuation(ADC_11db);  // usable range up to ~3.3V
  pinMode(ADC_PIN, INPUT);

  pinMode(LED_BUILTIN, OUTPUT);
  // Quick boot blink so you can see the board has (re)started and is
  // ready to receive commands.
  for (int i = 0; i < 3; i++) {
    digitalWrite(LED_BUILTIN, HIGH);
    delay(100);
    digitalWrite(LED_BUILTIN, LOW);
    delay(100);
  }
}

void sendFrame() {
  uint32_t sum = 0;

  for (int i = 0; i < FRAME_SAMPLES; i++) {
    uint32_t t0 = micros();
    buffer[i] = analogRead(ADC_PIN);
    sum += buffer[i];
    while (micros() - t0 < sampleIntervalUs) {
      // busy-wait to hold a steady sample interval
    }
  }

  uint8_t header[2] = {0xAA, 0x55};
  uint16_t nSamples = FRAME_SAMPLES;
  uint16_t checksum = (uint16_t)(sum & 0xFFFF);

  Serial.write(header, 2);
  Serial.write((uint8_t*)&nSamples, 2);
  Serial.write((uint8_t*)&sampleIntervalUs, 4);
  Serial.write((uint8_t*)buffer, FRAME_SAMPLES * 2);
  Serial.write((uint8_t*)&checksum, 2);
}

void loop() {
  if (Serial.available()) {
    char c = Serial.read();
    if (c == 'G') {
      streaming = true;
      digitalWrite(LED_BUILTIN, HIGH);   // lit = board received Start and is streaming
    } else if (c == 'S') {
      streaming = false;
      digitalWrite(LED_BUILTIN, LOW);
    } else if (c >= '0' && c <= '9') {
      sampleIntervalUs = SAMPLE_INTERVALS_US[c - '0'];
    }
  }

  if (streaming) {
    sendFrame();
  }
}
