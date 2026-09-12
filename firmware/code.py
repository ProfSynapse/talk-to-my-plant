"""Bench diagnostics for the Talk to My Plant hardware chain."""

import sys
import time

import board
import microcontroller
from adafruit_bme280 import basic as adafruit_bme280
from adafruit_max1704x import MAX17048
from adafruit_seesaw.seesaw import Seesaw


FIRMWARE_VERSION = "0.1.0-bench"
SAMPLE_INTERVAL_SECONDS = 10

BME280_ADDRESS = 0x77
SOIL_SENSOR_ADDRESS = 0x76

BATTERY_LOW_PERCENT = 30.0
BATTERY_CRITICAL_PERCENT = 15.0


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def battery_condition(percent):
    if percent <= BATTERY_CRITICAL_PERCENT:
        return "critical"
    if percent <= BATTERY_LOW_PERCENT:
        return "low"
    return "ok"


def scan_i2c(i2c):
    while not i2c.try_lock():
        pass

    try:
        return i2c.scan()
    finally:
        i2c.unlock()


print("Talk to My Plant — full sensor diagnostics")
print("Firmware:", FIRMWARE_VERSION)
print("CircuitPython:", sys.implementation.version)
print("Board:", board.board_id)
print("Reset reason:", microcontroller.cpu.reset_reason)

i2c = board.STEMMA_I2C()
addresses = scan_i2c(i2c)
print("I2C addresses:", ", ".join(f"0x{address:02X}" for address in addresses))

bme280 = adafruit_bme280.Adafruit_BME280_I2C(i2c, address=BME280_ADDRESS)
soil_sensor = Seesaw(i2c, addr=SOIL_SENSOR_ADDRESS)
battery_monitor = MAX17048(i2c)

while True:
    try:
        battery_percent_raw = battery_monitor.cell_percent
        battery_percent = clamp(battery_percent_raw, 0.0, 100.0)

        print("Uptime: {:.0f} seconds".format(time.monotonic()))
        print(
            "BME280: "
            f"{bme280.temperature:.2f} C, "
            f"{bme280.relative_humidity:.2f}% RH, "
            f"{bme280.pressure:.2f} hPa"
        )
        print(
            "Soil sensor: "
            f"raw moisture {soil_sensor.moisture_read()}, "
            f"{soil_sensor.get_temp():.2f} C"
        )
        print(
            "Battery monitor: "
            f"{battery_monitor.cell_voltage:.3f} V, "
            f"{battery_percent:.1f}% reported "
            f"({battery_percent_raw:.1f}% raw), "
            f"{battery_monitor.charge_rate:.2f}%/hour, "
            f"status {battery_condition(battery_percent)}"
        )
        print("---")
    except Exception as error:
        print("Sensor read error:", repr(error))

    time.sleep(SAMPLE_INTERVAL_SECONDS)
