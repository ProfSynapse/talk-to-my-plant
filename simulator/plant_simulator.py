#!/usr/bin/env python3
"""Generate realistic plant telemetry without requiring physical hardware."""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SCENARIOS = ("normal", "dry-out", "low-battery", "heat-wave", "noisy")


@dataclass
class PlantState:
    soil_moisture: float = 52.0
    temperature_f: float = 72.0
    humidity: float = 48.0
    pressure_hpa: float = 1013.0
    battery_percent: float = 92.0
    battery_voltage: float = 4.12

    def clamp(self) -> None:
        self.soil_moisture = min(100.0, max(0.0, self.soil_moisture))
        self.humidity = min(100.0, max(0.0, self.humidity))
        self.battery_percent = min(100.0, max(0.0, self.battery_percent))
        self.battery_voltage = min(4.20, max(3.20, self.battery_voltage))


def evolve(state: PlantState, scenario: str, rng: random.Random) -> PlantState:
    """Advance the simulated plant by one reading."""
    soil_delta = -0.12
    temperature_delta = rng.uniform(-0.15, 0.15)
    humidity_delta = rng.uniform(-0.25, 0.25)
    battery_delta = -0.03

    if scenario == "dry-out":
        soil_delta = -2.25
    elif scenario == "low-battery":
        battery_delta = -3.0
    elif scenario == "heat-wave":
        temperature_delta = 1.15
        humidity_delta = -0.8
    elif scenario == "noisy":
        soil_delta += rng.uniform(-4.0, 4.0)
        temperature_delta += rng.uniform(-2.0, 2.0)
        humidity_delta += rng.uniform(-5.0, 5.0)

    state.soil_moisture += soil_delta + rng.uniform(-0.15, 0.15)
    state.temperature_f += temperature_delta
    state.humidity += humidity_delta
    state.pressure_hpa += rng.uniform(-0.25, 0.25)
    state.battery_percent += battery_delta
    state.battery_voltage = 3.2 + state.battery_percent / 100.0
    state.clamp()
    return state


def classify(state: PlantState) -> list[str]:
    """Return deterministic conditions; conversational code can phrase them later."""
    conditions: list[str] = []
    if state.soil_moisture < 25:
        conditions.append("needs_water")
    if state.temperature_f > 85:
        conditions.append("too_hot")
    if state.humidity < 30:
        conditions.append("air_too_dry")
    if state.battery_percent <= 15:
        conditions.append("battery_critical")
    elif state.battery_percent <= 30:
        conditions.append("battery_low")
    return conditions or ["comfortable"]


def make_payload(device_id: str, state: PlantState) -> dict[str, object]:
    values = {key: round(value, 2) for key, value in asdict(state).items()}
    return {
        "schema_version": "1.0",
        "device_id": device_id,
        "recorded_at": datetime.now(UTC).isoformat(),
        "readings": values,
        "conditions": classify(state),
        "source": "simulator",
    }


def generate_readings(
    device_id: str, scenario: str, seed: int | None = None
) -> Iterator[dict[str, object]]:
    rng = random.Random(seed)
    state = PlantState()
    while True:
        yield make_payload(device_id, evolve(state, scenario, rng))


def post_payload(url: str, payload: dict[str, object], api_key: str | None) -> int:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        return response.status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--device-id",
        default=os.getenv("PLANT_DEVICE_ID", "plant-001"),
    )
    parser.add_argument("--endpoint", default=os.getenv("TELEMETRY_URL"))
    parser.add_argument("--api-key", default=os.getenv("PLANT_API_KEY"))
    parser.add_argument("--scenario", choices=SCENARIOS, default="normal")
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--count", type=int, default=0, help="0 sends forever")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.dry_run and not args.endpoint:
        raise SystemExit("Set TELEMETRY_URL/--endpoint, or pass --dry-run")

    readings = generate_readings(args.device_id, args.scenario, args.seed)
    sent = 0
    try:
        for payload in readings:
            if args.dry_run:
                print(json.dumps(payload, indent=2))
            else:
                try:
                    status = post_payload(args.endpoint, payload, args.api_key)
                    print(f"sent {payload['recorded_at']} status={status}")
                except (HTTPError, URLError, TimeoutError) as error:
                    print(f"send failed: {error}")

            sent += 1
            if args.count and sent >= args.count:
                break
            time.sleep(max(0.0, args.interval))
    except KeyboardInterrupt:
        print("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
