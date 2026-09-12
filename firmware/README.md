# Feather firmware

This directory contains two CircuitPython programs for the physical plant
monitor:

- `code.py` is the hardware-tested bench diagnostic.
- `telemetry_code.py` is the production network build. It sends raw soil
  observations during calibration and deliberately does not invent a 0–100
  moisture value.

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
  adafruit_bme280 adafruit_seesaw adafruit_max1704x \
  adafruit_requests adafruit_ntp
```

Use `code.py` for diagnostics. After the soak passes and `settings.toml` is
complete, copy `telemetry_code.py` to `/Volumes/CIRCUITPY/code.py`.

## Wi-Fi credentials

Copy `settings.toml.example` to `CIRCUITPY/settings.toml` and replace the Wi-Fi
placeholders locally. Never commit the populated file. To verify connectivity,
temporarily copy `wifi_test.py` to `CIRCUITPY/code.py` and read the serial output.

Writing files on `CIRCUITPY` triggers automatic reload, so do not configure Wi-Fi
during an uninterrupted hardware soak test.

Run bench soaks with `scripts/hardware_soak.py`. Unlike the original temporary
monitor, it appends and fsyncs every serial line to JSONL and always writes a
separate JSON summary. Store captures under `.local/soaks/`, which is ignored by
Git but remains on the workstation:

```bash
python scripts/hardware_soak.py \
  --port /dev/cu.usbmodem0DFC31A0E98C1 \
  --duration 3600 \
  --output-dir .local/soaks
```

## Telemetry behavior

The production build samples once per minute. It sends meaningful climate,
battery, or raw-soil changes; a second observation when a problem persists for
two minutes; and an hourly silent check-in. While `PLANT_CALIBRATION_MODE` is
true, it also stores a raw soil observation every five minutes so the installed
watering curve can be calibrated. Failed deliveries are retried on a later
cycle, and Wi-Fi plus UTC/NTP synchronization recover automatically.

Raw soil readings are accepted by telemetry schema `1.2`. The service logs them
but suppresses `needs_water` until the foliage-zone care profile contains valid
`alert_below` and `recover_above` calibration targets. After calibration, the
firmware will map raw readings to the profile's relative 0–100 index and
`PLANT_CALIBRATION_MODE` can be disabled.

## Battery behavior

The production requirement is deliberately simple: warn when an installed
battery remains low, so the owner knows to plug the plant in. The firmware does
not attempt to classify USB versus battery power.

MAX17048 percentage is clamped to `0–100` before telemetry. Initial thresholds
are 30% for low and 15% for critical; confirmation and recovery hysteresis will
prevent alert storms. When no LiPo is attached, USB can make the gauge appear
full, so no-battery bench readings must not be treated as proof of a battery.
