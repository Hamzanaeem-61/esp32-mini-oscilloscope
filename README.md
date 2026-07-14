# ESP32 Oscilloscope

A simple two-channel-of-effort (one ADC channel) oscilloscope: the ESP32
samples an analog signal and streams it over USB serial; a Python app on
the PC displays it live, like a real scope.

```
[ signal source ] --> [ input protection/attenuator ] --> GPIO34 (ESP32 ADC)
                                                                |
                                                             USB cable
                                                                |
                                                     [ PC: oscilloscope_gui.py ]
```

## 1. Hardware

- Any ESP32 dev board (e.g. ESP32-DevKitC, NodeMCU-32S)
- USB cable
- The signal you want to view

**GPIO34** is used because it's an ADC1 pin (ADC1 stays available even
when Wi-Fi is on, unlike ADC2) and it's input-only, which is convenient
and safe for this purpose.

### ⚠️ Voltage limit — read this first

The ESP32 ADC input must stay within **0V to 3.3V**. Never connect a
signal directly if it could go negative or above 3.3V (e.g. mains,
audio signals, most microcontroller/analog circuits at 5V+ logic).

For anything else, add a simple front-end **before** GPIO34:

```
Vin ----[ R1 = 10k ]----+----[ R2 = 10k ]---- GND
                         |
                      GPIO34
                         |
                   [ 100nF cap to GND ] (optional, reduces noise)
```

- This divides Vin by 2 — adjust R1/R2 ratio to fit your signal's range
  into 0–3.3V.
- For **AC/bipolar signals**, add a DC offset so negative swings don't
  go below 0V: bias the midpoint with a resistor divider from 3.3V, and
  AC-couple the signal in through a capacitor. This is the same trick
  used in most hobby "PC oscilloscope" ADC front-ends — a low-cost
  op-amp buffer (e.g. an LM358 stage) ahead of the divider is worth
  adding if you want a clean, low-impedance input.

## 2. Flash the firmware

1. Open `esp32_firmware/esp32_firmware.ino` in the Arduino IDE.
2. Install the ESP32 board package if you haven't already
   (Boards Manager → search "esp32").
3. Select your board and port, then upload.
4. It will sit idle until the PC app sends a start command.

## 3. Run the PC app

```bash
pip install pyserial pyqtgraph PyQt5 numpy
python pc_app/oscilloscope_gui.py --port COM5      # Windows
python pc_app/oscilloscope_gui.py --port /dev/ttyUSB0   # Linux/Mac
```

Click **Start** to begin streaming, choose a sample rate from the
dropdown, and the live trace will appear. **Stop** halts streaming.

## 4. How it works

- The ESP32 samples GPIO34 in a tight loop, timed with `micros()` to
  hold a steady sample interval, and packs 512 samples into a binary
  frame (header, sample count, interval, raw data, checksum).
- Frames stream continuously over USB serial at 2 Mbps.
- The PC app runs the serial read on a background thread, validates
  each frame's checksum, converts raw ADC counts to volts, and plots
  it with `pyqtgraph` (fast enough for smooth real-time redraw).
- A simple rising-edge trigger finds the first crossing of the
  waveform's midpoint each frame and shifts the plot so the trace
  looks stable instead of jittering sideways — the same idea real
  scopes use.

## 5. Realistic performance

With this loop-based sampling approach, expect roughly **20–50 kSa/s**
maximum — enough for audio-frequency signals and slow-ish digital
signals, but not RF. The practical ceiling comes from ESP32 ADC
conversion time plus loop overhead.

## 6. Ideas to extend this project

- **Higher sample rate:** switch to the ESP32's I2S peripheral in ADC
  mode with DMA, which can sample into the hundreds of kSa/s without
  CPU-timed busy-waiting.
- **Second channel:** add GPIO35 (also ADC1) and interleave samples for
  a 2-channel scope.
- **Wi-Fi streaming:** replace USB serial with a UDP stream so the
  ESP32 can sit untethered near the circuit under test.
- **FFT view:** add a spectrum tab in the PC app using `numpy.fft`.
- **Adjustable trigger level/mode:** let the user set trigger voltage
  and falling/rising edge from the GUI instead of the fixed midpoint
  trigger.
- **On-screen volts/div and cursors:** add measurement cursors for
  amplitude and period, like a real bench scope.
