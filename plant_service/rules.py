"""Pure rules shared by ingestion and tests. Values require plant calibration."""

def conditions(readings: dict, previous: list[str] = ()) -> list[str]:
    active = []
    # Separate recovery thresholds keep boundary noise from flapping alerts.
    if readings["soil_moisture"] < (32 if "needs_water" in previous else 25):
        active.append("needs_water")
    if readings["temperature_f"] > (82 if "too_hot" in previous else 85):
        active.append("too_hot")
    if readings["humidity"] < (35 if "air_too_dry" in previous else 30):
        active.append("air_too_dry")
    battery = readings["battery_percent"]
    if battery <= (20 if "battery_critical" in previous else 15):
        active.append("battery_critical")
    elif battery <= (35 if "battery_low" in previous else 30):
        active.append("battery_low")
    return active


ALERT_TEXT = {
    "needs_water": "My soil has stayed below the dry threshold. Please check it before watering.",
    "too_hot": "It has stayed unusually warm here. Could you check my spot?",
    "air_too_dry": "The air has stayed below my humidity threshold. Could you check my surroundings?",
    "battery_low": "My battery is getting low. Please plug me in when you can.",
    "battery_critical": "My battery is critically low. Please plug me in soon.",
    "device_offline": "I missed my scheduled check-ins. Please check my power and Wi-Fi.",
}
