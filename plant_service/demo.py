"""Clearly labeled, bounded demo values. Never impersonates physical hardware."""
import math
from datetime import datetime, timezone

from simulator.reporting import ReportingPolicy
from .models import Telemetry


class Demo:
    def __init__(self):
        self.policy = ReportingPolicy()

    def tick(self, service, now):
        wave = math.sin(now / 3600)
        payload = {"device_id":"demo-plant", "source":"simulator", "schema_version":"1.1",
            "recorded_at":datetime.now(timezone.utc).isoformat(), "conditions":["comfortable"],
            "readings":{"soil_moisture":round(52 + 8*wave,2), "temperature_f":round(72+2*wave,2),
                        "humidity":round(48+4*wave,2),"pressure_hpa":1013,"battery_percent":92,"battery_voltage":4.12}}
        report = self.policy.select(payload, now)
        if report:
            service.ingest(Telemetry(**report))
