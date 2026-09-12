#!/usr/bin/env python3
"""Capture a durable serial soak log and an always-written JSON summary."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import serial


PATTERNS = {
    "bme": re.compile(r"BME280: ([\d.]+) C, ([\d.]+)% RH, ([\d.]+) hPa"),
    "soil": re.compile(r"Soil sensor: raw moisture (\d+), ([\d.]+) C"),
    "battery": re.compile(r"Battery monitor: ([\d.]+) V, ([\d.]+)% reported"),
}


def utc_now():
    return datetime.now(UTC).isoformat()


def parse_line(line):
    match = PATTERNS["bme"].search(line)
    if match:
        return {"kind": "bme", "temperature_c": float(match.group(1)),
                "humidity_percent": float(match.group(2)),
                "pressure_hpa": float(match.group(3))}
    match = PATTERNS["soil"].search(line)
    if match:
        return {"kind": "soil", "soil_raw": int(match.group(1)),
                "soil_temperature_c": float(match.group(2))}
    match = PATTERNS["battery"].search(line)
    if match:
        return {"kind": "battery", "battery_voltage": float(match.group(1)),
                "battery_percent": float(match.group(2))}
    if "error" in line.lower() or "traceback" in line.lower():
        return {"kind": "error", "message": line}
    return {"kind": "serial"}


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--duration", type=int, default=3600)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main():
    args = arguments()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    events_path = args.output_dir / (run_id + ".jsonl")
    summary_path = args.output_dir / (run_id + "-summary.json")
    values = {name: [] for name in (
        "temperature_c", "humidity_percent", "pressure_hpa", "soil_raw",
        "soil_temperature_c", "battery_voltage", "battery_percent")}
    errors = []
    started_wall = time.time()
    deadline = time.monotonic() + args.duration
    interrupted = False

    with events_path.open("a", encoding="utf-8", buffering=1) as events:
        def persist(event):
            events.write(json.dumps(event, separators=(",", ":")) + "\n")
            events.flush()
            os.fsync(events.fileno())

        persist({"kind": "run_start", "host_received_at": utc_now(),
                 "port": args.port, "duration_seconds": args.duration})
        try:
            with serial.Serial(args.port, 115200, timeout=1) as connection:
                while time.monotonic() < deadline:
                    line = connection.readline().decode(
                        "utf-8", errors="replace").strip()
                    if not line:
                        continue
                    parsed = parse_line(line)
                    event = {"host_received_at": utc_now(), "line": line, **parsed}
                    persist(event)
                    for name in values:
                        if name in parsed:
                            values[name].append(parsed[name])
                    if parsed["kind"] == "error":
                        errors.append(line)
        except KeyboardInterrupt:
            interrupted = True
        except Exception as error:
            errors.append(type(error).__name__ + ": " + str(error))
            persist({"kind": "capture_error", "host_received_at": utc_now(),
                     "error_type": type(error).__name__, "message": str(error)})

        duration = round(time.time() - started_wall, 1)
        complete_samples = min(len(items) for items in values.values())
        summary = {
            "run_id": run_id,
            "started_at": datetime.fromtimestamp(started_wall, UTC).isoformat(),
            "finished_at": utc_now(),
            "requested_duration_seconds": args.duration,
            "observed_duration_seconds": duration,
            "status": ("interrupted" if interrupted else
                       "passed" if duration >= args.duration and complete_samples > 0
                       and not errors else "failed"),
            "complete_samples": complete_samples,
            "metrics": {name: {"count": len(items),
                               "minimum": min(items) if items else None,
                               "maximum": max(items) if items else None}
                        for name, items in values.items()},
            "errors": errors,
            "events_file": str(events_path),
        }
        persist({"kind": "run_end", "host_received_at": utc_now(),
                 "summary": summary})

    temporary = summary_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, summary_path)
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
