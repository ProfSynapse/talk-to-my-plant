"""Smoke test a deployment using only the isolated demo plant. Never sends Slack."""
import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--base-url", default="https://plant-api-production-68c9.up.railway.app")
parser.add_argument("--env-file")
args = parser.parse_args()
cfg = dict(os.environ)
if args.env_file:
    for line in Path(args.env_file).read_text().splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            cfg[key] = value

with httpx.Client(base_url=args.base_url, timeout=45) as client:
    response = client.get("/healthz")
    assert response.status_code == 200, response.status_code
    print("Public health: Postgres connected")
    assert client.get("/api/plants/demo-plant/status?source=simulator").status_code == 401
    owner = {"Authorization": "Bearer " + cfg["PLANT_API_KEY"]}
    simulator = {"Authorization": "Bearer " + cfg["SIMULATOR_API_KEY"]}
    payload = {"schema_version":"1.1","device_id":"demo-plant","source":"simulator",
               "recorded_at":datetime.now(timezone.utc).isoformat(),"report_kind":"event",
               "readings":{"soil_moisture":52,"temperature_f":72,"humidity":48,"pressure_hpa":1013,
                           "battery_percent":92,"battery_voltage":4.12}}
    response = client.post("/api/telemetry",headers=simulator,json=payload)
    response.raise_for_status()
    assert response.json()["logged"]
    assert not client.post("/api/telemetry",headers=simulator,json=payload).json()["logged"]
    print("Telemetry: accepted, persisted, duplicate suppressed")
    response = client.get("/api/plants/demo-plant/status?source=simulator",headers=owner)
    response.raise_for_status()
    assert response.json()["device"]["source"] == "simulator"
    assert response.json()["recent_readings"]
    assert client.get("/api/plants/demo-plant/status?source=simulator",headers=simulator).status_code == 401
    assert client.get("/api/plants/plant-001/status",headers=owner).json()["device"] is None
    print("Data access: owner only; real hardware still has no fabricated data")
    chat = {"request_id":"smoke-"+uuid.uuid4().hex,"conversation_id":"deployment-smoke",
            "device_id":"demo-plant","source":"simulator","text":"How are you doing?"}
    response = client.post("/api/chat",headers=owner,json=chat)
    response.raise_for_status()
    result = response.json()
    assert result["reply"]
    assert client.post("/api/chat",headers=owner,json=chat).json()["cached"]
    print("Conversation: reply stored, retry reused; model="+result["model"])
    response = client.get("/api/integrations",headers=owner)
    response.raise_for_status()
    print("Integrations:",json.dumps(response.json()))
