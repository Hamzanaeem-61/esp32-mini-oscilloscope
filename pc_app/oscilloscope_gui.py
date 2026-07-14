"""
ESP32 Oscilloscope — PC Display App
------------------------------------
Reads binary waveform frames streamed from the ESP32 firmware over
USB serial and displays them as a live oscilloscope trace, with a
simple rising-edge trigger to keep the waveform stable on screen.

INSTALL:
    pip install pyserial pyqtgraph PyQt5 numpy

RUN:
    python oscilloscope_gui.py --port COM5            (Windows)
    python oscilloscope_gui.py --port /dev/ttyUSB0    (Linux/Mac)
"""

import sys
import time
import struct
import argparse
import numpy as np
import serial
from PyQt5 import QtWidgets, QtCore
import pyqtgraph as pg

FRAME_HEADER = b'\xAA\x55'
FRAME_SAMPLES = 512
ADC_MAX = 4095
VREF = 3.3
FRAME_SIZE = 2 + 2 + 4 + FRAME_SAMPLES * 2 + 2  # header+count+interval+data+checksum

SAMPLE_INTERVALS_US = [20, 40, 80, 160, 320, 640, 1280, 2560, 5120, 10240]


class SerialReader(QtCore.QThread):
    frame_ready = QtCore.pyqtSignal(np.ndarray, float)

    status = QtCore.pyqtSignal(str)
    error = QtCore.pyqtSignal(str)

    def __init__(self, port, baud=921600):
        super().__init__()
        self.port = port
        self.baud = baud
        self.ser = None
        self.running = True

    def run(self):
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=1)
        except serial.SerialException as e:
            self.error.emit(f"Could not open {self.port}: {e}")
            return

        # Opening the port toggles DTR/RTS on most boards, which resets
        # the ESP32. Give it time to finish booting before we trust the
        # link, and throw away any boot-time garbage bytes.
        self.status.emit("Waiting for ESP32 to finish booting...")
        time.sleep(2.0)
        self.ser.reset_input_buffer()
        self.status.emit(f"Connected on {self.port}")

        buf = bytearray()
        try:
            while self.running:
                chunk = self.ser.read(4096)
                if chunk:
                    buf += chunk

                while True:
                    idx = buf.find(FRAME_HEADER)
                    if idx == -1:
                        # Keep the last byte in case it's the first half
                        # of a header that's split across reads.
                        if len(buf) > 1:
                            del buf[:-1]
                        break
                    if len(buf) - idx < FRAME_SIZE:
                        if idx > 0:
                            del buf[:idx]
                        break

                    frame = bytes(buf[idx: idx + FRAME_SIZE])
                    del buf[:idx + FRAME_SIZE]

                    n_samples = struct.unpack('<H', frame[2:4])[0]
                    interval_us = struct.unpack('<I', frame[4:8])[0]
                    data = np.frombuffer(frame[8:8 + n_samples * 2], dtype='<u2')
                    checksum = struct.unpack('<H', frame[8 + n_samples * 2: 10 + n_samples * 2])[0]

                    if (int(data.astype(np.uint32).sum()) & 0xFFFF) != checksum:
                        continue  # corrupted frame, drop it

                    volts = data.astype(np.float32) * (VREF / ADC_MAX)
                    self.frame_ready.emit(volts, float(interval_us))
        except serial.SerialException as e:
            self.error.emit(f"Serial connection lost: {e}")

    def send_command(self, cmd: str):
        if self.ser is not None and self.ser.is_open:
            self.ser.write(cmd.encode())
            self.ser.flush()

    def stop(self):
        self.running = False
        self.wait()
        if self.ser is not None and self.ser.is_open:
            self.ser.close()


class OscilloscopeWindow(QtWidgets.QMainWindow):
    def __init__(self, port):
        super().__init__()
        self.setWindowTitle("ESP32 Oscilloscope")
        self.resize(900, 600)

        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        self.setCentralWidget(central)

        self.plot = pg.PlotWidget()
        self.plot.setLabel('left', 'Voltage', 'V')
        self.plot.setLabel('bottom', 'Time', 's')
        self.plot.setYRange(0, VREF)
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.curve = self.plot.plot(pen=pg.mkPen('y', width=1.5))
        layout.addWidget(self.plot)

        controls = QtWidgets.QHBoxLayout()
        layout.addLayout(controls)

        self.start_btn = QtWidgets.QPushButton("Start")
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.rate_box = QtWidgets.QComboBox()
        self.rate_box.addItems([f"{1e6/us:,.0f} Sa/s" for us in SAMPLE_INTERVALS_US])
        self.rate_box.setCurrentIndex(4)

        controls.addWidget(QtWidgets.QLabel("Sample rate:"))
        controls.addWidget(self.rate_box)
        controls.addWidget(self.start_btn)
        controls.addWidget(self.stop_btn)
        controls.addStretch(1)

        self.status_label = QtWidgets.QLabel("Connecting...")
        self.statusBar().addWidget(self.status_label)
        self.frame_count = 0

        self.start_btn.clicked.connect(self.start_stream)
        self.stop_btn.clicked.connect(self.stop_stream)
        self.rate_box.currentIndexChanged.connect(self.set_rate)

        self.reader = SerialReader(port)
        self.reader.frame_ready.connect(self.update_plot)
        self.reader.status.connect(self.status_label.setText)
        self.reader.error.connect(self.on_error)
        self.reader.start()

    def on_error(self, msg):
        self.status_label.setText(f"ERROR: {msg}")
        QtWidgets.QMessageBox.critical(self, "Connection error", msg)

    def set_rate(self, idx):
        self.reader.send_command(str(idx))

    def start_stream(self):
        self.set_rate(self.rate_box.currentIndex())
        self.reader.send_command('G')

    def stop_stream(self):
        self.reader.send_command('S')

    def update_plot(self, volts: np.ndarray, interval_us: float):
        self.frame_count += 1
        self.status_label.setText(f"Streaming — {self.frame_count} frames received")

        t = np.arange(len(volts)) * (interval_us * 1e-6)

        # Simple rising-edge trigger so the waveform doesn't drift
        # sideways on screen every frame.
        mid = (float(volts.max()) + float(volts.min())) / 2.0
        above = volts > mid
        crossings = np.where(np.diff(above.astype(int)) == 1)[0]
        trig_idx = int(crossings[0]) if len(crossings) > 0 else 0

        t = t[trig_idx:] - t[trig_idx]
        v = volts[trig_idx:]
        self.curve.setData(t, v)

    def closeEvent(self, event):
        self.reader.stop()
        event.accept()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', required=True, help='Serial port, e.g. COM5 or /dev/ttyUSB0')
    args = parser.parse_args()

    app = QtWidgets.QApplication(sys.argv)
    win = OscilloscopeWindow(args.port)
    win.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
