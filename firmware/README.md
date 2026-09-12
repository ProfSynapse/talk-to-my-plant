# Feather firmware

This directory contains the CircuitPython firmware for the physical plant
monitor. `code.py` is currently a hardware-tested bench diagnostic; network
telemetry will be layered onto it after the sensors have completed their soak
test and soil calibration.

## Verified hardware

- Adafruit Feather ESP32-S3, 4 MB Flash / 2 MB PSRAM, PID 5477
- TinyUF2 0.33.0
- CircuitPython 10.3.0
- Onboard MAX17048 at `0x36`
- Soil sensor behind the LTC4316 at translated address `0x76`
- BME280 at `0x77`

The verified physical chain is:

```text
Feather -> BME280 -> LTC4316 input | output -> soil sensor
```

Both LTC4316 DIP switches are set toward `ON`.

## Install libraries

With `CIRCUITPY` mounted, install the required libraries and their dependencies:

```bash
circup --path /Volumes/CIRCUITPY install \
  adafruit_bme280 adafruit_seesaw adafruit_max1704x
```

Then copy `code.py` to the root of `CIRCUITPY`.

## Wi-Fi credentials

Copy `settings.toml.example` to `CIRCUITPY/settings.toml` and replace the Wi-Fi
placeholders locally. Never commit the populated file. To verify connectivity,
temporarily copy `wifi_test.py` to `CIRCUITPY/code.py` and read the serial output.

Writing files on `CIRCUITPY` triggers automatic reload, so do not configure Wi-Fi
during an uninterrupted hardware soak test.

## Battery behavior

The production requirement is deliberately simple: warn when an installed
battery remains low, so the owner knows to plug the plant in. The firmware does
not attempt to classify USB versus battery power.

MAX17048 percentage is clamped to `0–100` before telemetry. Initial thresholds
are 30% for low and 15% for critical; confirmation and recovery hysteresis will
prevent alert storms. When no LiPo is attached, USB can make the gauge appear
full, so no-battery bench readings must not be treated as proof of a battery.
