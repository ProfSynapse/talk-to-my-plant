"""One-time Wi-Fi connection test for the Feather."""

import os

import wifi


ssid = os.getenv("CIRCUITPY_WIFI_SSID")
password = os.getenv("CIRCUITPY_WIFI_PASSWORD")

if not ssid or not password:
    raise RuntimeError("Add CIRCUITPY_WIFI_SSID and CIRCUITPY_WIFI_PASSWORD to settings.toml")

print("Connecting to Wi-Fi:", ssid)
wifi.radio.connect(ssid, password)
print("Connected")
print("IPv4 address:", wifi.radio.ipv4_address)

if wifi.radio.ap_info is not None:
    print("Signal strength:", wifi.radio.ap_info.rssi, "dBm")
