"""Production telemetry firmware for the Talk to My Plant Feather."""

import alarm
import digitalio
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


FIRMWARE_VERSION = "0.3.0-deep-sleep"
BME280_ADDRESS = 0x77
SOIL_SENSOR_ADDRESS = 0x76

DEFAULT_CALIBRATION_INTERVAL_SECONDS = 900
DEFAULT_NORMAL_INTERVAL_SECONDS = 3600

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


def integer_setting(name, default):
    value = int(setting(name, default))
    if value < 60:
        raise RuntimeError(name + " must be at least 60 seconds")
    return value


WIFI_SSID = setting("CIRCUITPY_WIFI_SSID")
WIFI_PASSWORD = setting("CIRCUITPY_WIFI_PASSWORD")
DEVICE_ID = setting("PLANT_DEVICE_ID", "plant-001")
SENSOR_PLACEMENT = setting("PLANT_SENSOR_PLACEMENT", "bench_air")
TELEMETRY_URL = setting("PLANT_TELEMETRY_URL")
API_KEY = setting("PLANT_API_KEY")
CALIBRATION_MODE = boolean_setting("PLANT_CALIBRATION_MODE", True)
DEEP_SLEEP_ENABLED = boolean_setting("PLANT_DEEP_SLEEP_ENABLED", True)
CALIBRATION_INTERVAL_SECONDS = integer_setting(
    "PLANT_CALIBRATION_INTERVAL_SECONDS",
    DEFAULT_CALIBRATION_INTERVAL_SECONDS,
)
NORMAL_INTERVAL_SECONDS = integer_setting(
    "PLANT_NORMAL_INTERVAL_SECONDS",
    DEFAULT_NORMAL_INTERVAL_SECONDS,
)
WAKE_INTERVAL_SECONDS = (
    CALIBRATION_INTERVAL_SECONDS if CALIBRATION_MODE
    else NORMAL_INTERVAL_SECONDS
)

if not all((WIFI_SSID, WIFI_PASSWORD, DEVICE_ID, TELEMETRY_URL, API_KEY)):
    raise RuntimeError("Complete the required values in settings.toml")
if not TELEMETRY_URL.startswith("https://"):
    raise RuntimeError("PLANT_TELEMETRY_URL must use HTTPS")
if SENSOR_PLACEMENT not in ("bench_air", "foliage_substrate", "orchid_bark"):
    raise RuntimeError("Invalid PLANT_SENSOR_PLACEMENT")


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


print("Talk to My Plant telemetry", FIRMWARE_VERSION)
print("Reset reason:", microcontroller.cpu.reset_reason)
print("Calibration logging:", CALIBRATION_MODE)
print("Sensor placement:", SENSOR_PLACEMENT)
print("Deep sleep:", DEEP_SLEEP_ENABLED, "for", WAKE_INTERVAL_SECONDS, "seconds")

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

def ensure_network():
    if not wifi.radio.connected:
        print("Connecting to Wi-Fi")
        wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
        print("Wi-Fi connected; RSSI", wifi.radio.ap_info.rssi, "dBm")
    # Deep sleep restarts code.py, so synchronize the clock once per wake.
    ntp = adafruit_ntp.NTP(pool, tz_offset=0, cache_seconds=3600)
    rtc.RTC().datetime = ntp.datetime
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


def deliver_once():
    readings = read_sensors()
    active = conditions(readings)
    ensure_network()
    payload = {
        "schema_version": "1.2",
        "device_id": DEVICE_ID,
        "source": "hardware",
        "sensor_placement": SENSOR_PLACEMENT,
        "recorded_at": iso_utc(),
        # Every scheduled observation is retained for trends and memory. Alerts
        # remain a separate server-side decision and do not notify when healthy.
        "report_kind": "event",
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
    print("Telemetry delivered:", payload["report_kind"], payload["recorded_at"],
          "soil raw", readings["soil_raw"], "battery",
          round(readings["battery_percent"], 1))
    gc.collect()


def deep_sleep(seconds):
    """Cut external rails and preserve their off state during deep sleep."""
    try:
        i2c.deinit()
    except Exception:
        pass
    try:
        wifi.radio.enabled = False
    except Exception:
        pass

    preserved = []
    for pin_name in ("I2C_POWER", "NEOPIXEL_POWER"):
        pin = getattr(board, pin_name, None)
        if pin is not None:
            power = digitalio.DigitalInOut(pin)
            power.switch_to_output(value=False)
            preserved.append(power)

    wake_alarm = alarm.time.TimeAlarm(
        monotonic_time=time.monotonic() + seconds
    )
    print("Sleeping for", seconds, "seconds")
    alarm.exit_and_deep_sleep_until_alarms(
        wake_alarm, preserve_dios=tuple(preserved)
    )


if DEEP_SLEEP_ENABLED:
    try:
        deliver_once()
    except Exception as error:
        # Never print the URL, credentials, request headers, or response body.
        print("Telemetry cycle failed:", type(error).__name__, str(error)[:120])
    finally:
        deep_sleep(WAKE_INTERVAL_SECONDS)
else:
    while True:
        try:
            deliver_once()
        except Exception as error:
            print("Telemetry cycle failed:", type(error).__name__, str(error)[:120])
        time.sleep(WAKE_INTERVAL_SECONDS)
