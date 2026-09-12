"""Production telemetry firmware for the Talk to My Plant Feather."""

import gc
import os
import rtc
import time

import adafruit_connection_manager
import adafruit_ntp
import adafruit_requests
import board
import microcontroller
import wifi
from adafruit_bme280 import basic as adafruit_bme280
from adafruit_max1704x import MAX17048
from adafruit_seesaw.seesaw import Seesaw


FIRMWARE_VERSION = "0.2.0-telemetry"
BME280_ADDRESS = 0x77
SOIL_SENSOR_ADDRESS = 0x76

SAMPLE_INTERVAL_SECONDS = 60
CHECKIN_SECONDS = 3600
CONFIRM_SECONDS = 120
CALIBRATION_LOG_SECONDS = 300
NTP_REFRESH_SECONDS = 21600

TEMPERATURE_DELTA_F = 3.0
HUMIDITY_DELTA_PERCENT = 5.0
BATTERY_DELTA_PERCENT = 5.0
SOIL_RAW_DELTA = 25

BATTERY_LOW_PERCENT = 30.0
BATTERY_CRITICAL_PERCENT = 15.0
TEMPERATURE_COLD_F = 61.0
TEMPERATURE_HOT_F = 85.0
HUMIDITY_DRY_PERCENT = 45.0


def setting(name, default=None):
    value = os.getenv(name)
    return default if value is None else value


def boolean_setting(name, default=False):
    value = setting(name, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


WIFI_SSID = setting("CIRCUITPY_WIFI_SSID")
WIFI_PASSWORD = setting("CIRCUITPY_WIFI_PASSWORD")
DEVICE_ID = setting("PLANT_DEVICE_ID", "plant-001")
TELEMETRY_URL = setting("PLANT_TELEMETRY_URL")
API_KEY = setting("PLANT_API_KEY")
CALIBRATION_MODE = boolean_setting("PLANT_CALIBRATION_MODE", True)

if not all((WIFI_SSID, WIFI_PASSWORD, DEVICE_ID, TELEMETRY_URL, API_KEY)):
    raise RuntimeError("Complete the required values in settings.toml")
if not TELEMETRY_URL.startswith("https://"):
    raise RuntimeError("PLANT_TELEMETRY_URL must use HTTPS")


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def scan_i2c(i2c):
    while not i2c.try_lock():
        pass
    try:
        return i2c.scan()
    finally:
        i2c.unlock()


def iso_utc():
    value = time.localtime()
    return (
        "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}Z"
        .format(value.tm_year, value.tm_mon, value.tm_mday,
                value.tm_hour, value.tm_min, value.tm_sec)
    )


def conditions(readings):
    active = []
    if readings["temperature_f"] > TEMPERATURE_HOT_F:
        active.append("too_hot")
    if readings["temperature_f"] < TEMPERATURE_COLD_F:
        active.append("too_cold")
    if readings["humidity"] < HUMIDITY_DRY_PERCENT:
        active.append("air_too_dry")
    if readings["battery_percent"] <= BATTERY_CRITICAL_PERCENT:
        active.append("battery_critical")
    elif readings["battery_percent"] <= BATTERY_LOW_PERCENT:
        active.append("battery_low")
    # Soil conditions intentionally remain absent until in-pot calibration.
    return active


def changed_enough(current, previous):
    if previous is None:
        return True
    limits = (
        ("temperature_f", TEMPERATURE_DELTA_F),
        ("humidity", HUMIDITY_DELTA_PERCENT),
        ("battery_percent", BATTERY_DELTA_PERCENT),
        ("soil_raw", SOIL_RAW_DELTA),
    )
    return any(abs(current[key] - previous[key]) >= delta
               for key, delta in limits)


print("Talk to My Plant telemetry", FIRMWARE_VERSION)
print("Reset reason:", microcontroller.cpu.reset_reason)
print("Calibration logging:", CALIBRATION_MODE)

i2c = board.STEMMA_I2C()
found = scan_i2c(i2c)
expected = (0x36, SOIL_SENSOR_ADDRESS, BME280_ADDRESS)
missing = [address for address in expected if address not in found]
if missing:
    raise RuntimeError("Missing required I2C device(s): " +
                       ", ".join("0x{:02X}".format(value) for value in missing))

bme280 = adafruit_bme280.Adafruit_BME280_I2C(i2c, address=BME280_ADDRESS)
soil_sensor = Seesaw(i2c, addr=SOIL_SENSOR_ADDRESS)
battery_monitor = MAX17048(i2c)

pool = adafruit_connection_manager.get_radio_socketpool(wifi.radio)
ssl_context = adafruit_connection_manager.get_radio_ssl_context(wifi.radio)
http = adafruit_requests.Session(pool, ssl_context)

clock_ready = False
last_ntp_sync = -NTP_REFRESH_SECONDS
last_sent_readings = None
last_sent_conditions = None
last_sent_at = -CHECKIN_SECONDS
observed_conditions = None
condition_started_at = None
confirmation_delivered = False


def ensure_network(now):
    global clock_ready, last_ntp_sync
    if not wifi.radio.connected:
        print("Connecting to Wi-Fi")
        wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
        print("Wi-Fi connected; RSSI", wifi.radio.ap_info.rssi, "dBm")
    if not clock_ready or now - last_ntp_sync >= NTP_REFRESH_SECONDS:
        ntp = adafruit_ntp.NTP(pool, tz_offset=0, cache_seconds=3600)
        rtc.RTC().datetime = ntp.datetime
        clock_ready = True
        last_ntp_sync = now
        print("UTC clock synchronized")


def read_sensors():
    battery_raw = battery_monitor.cell_percent
    return {
        "soil_raw": soil_sensor.moisture_read(),
        "temperature_f": bme280.temperature * 9.0 / 5.0 + 32.0,
        "humidity": bme280.relative_humidity,
        "pressure_hpa": bme280.pressure,
        "battery_percent": clamp(battery_raw, 0.0, 100.0),
        "battery_voltage": battery_monitor.cell_voltage,
    }


def report_kind(now, readings, active):
    active_tuple = tuple(active)
    condition_change = last_sent_conditions is None or active_tuple != last_sent_conditions
    confirmation_due = (
        bool(active_tuple) and not confirmation_delivered and
        condition_started_at is not None and now - condition_started_at >= CONFIRM_SECONDS
    )
    calibration_due = CALIBRATION_MODE and now - last_sent_at >= CALIBRATION_LOG_SECONDS
    if (last_sent_readings is None or condition_change or confirmation_due or
            calibration_due or changed_enough(readings, last_sent_readings)):
        return "event", confirmation_due
    if now - last_sent_at >= CHECKIN_SECONDS:
        return "checkin", False
    return None, False


while True:
    loop_started = time.monotonic()
    try:
        readings = read_sensors()
        active = conditions(readings)
        active_tuple = tuple(active)
        if active_tuple != observed_conditions:
            observed_conditions = active_tuple
            condition_started_at = loop_started
            confirmation_delivered = False

        kind, confirms_problem = report_kind(loop_started, readings, active)
        if kind is not None:
            ensure_network(loop_started)
            payload = {
                "schema_version": "1.2",
                "device_id": DEVICE_ID,
                "source": "hardware",
                "recorded_at": iso_utc(),
                "report_kind": kind,
                "conditions": active,
                "readings": readings,
            }
            response = None
            try:
                response = http.post(
                    TELEMETRY_URL,
                    headers={"Authorization": "Bearer " + API_KEY},
                    json=payload,
                )
                if response.status_code < 200 or response.status_code >= 300:
                    raise RuntimeError("telemetry HTTP " + str(response.status_code))
            finally:
                if response is not None:
                    response.close()

            last_sent_readings = readings
            last_sent_conditions = active_tuple
            last_sent_at = loop_started
            if confirms_problem:
                confirmation_delivered = True
            print("Telemetry delivered:", kind, payload["recorded_at"],
                  "soil raw", readings["soil_raw"], "battery",
                  round(readings["battery_percent"], 1))
            gc.collect()
    except Exception as error:
        # Never print the URL, credentials, request headers, or response body.
        print("Telemetry cycle failed:", type(error).__name__, str(error)[:120])

    elapsed = time.monotonic() - loop_started
    time.sleep(max(1, SAMPLE_INTERVAL_SECONDS - elapsed))
