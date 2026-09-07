# Talk to My Plant

An experimental IoT plant companion: sensor readings become useful alerts and
natural-language conversations grounded in the plant's actual condition.

The project is intentionally split at the telemetry boundary. The software can
be built against simulated readings today, then use the real Adafruit hardware
later without changing the backend, alerts, or chat integrations.

## Start without hardware

Requires Python 3.11+ and no third-party packages.

```bash
python3 simulator/plant_simulator.py --dry-run --count 5
```

Try an alert condition:

```bash
python3 simulator/plant_simulator.py \
  --dry-run \
  --scenario dry-out \
  --interval 1 \
  --count 20
```

To send readings to a deployed webhook:

```bash
export TELEMETRY_URL="https://example.com/api/telemetry"
export PLANT_API_KEY="replace-me"
python3 simulator/plant_simulator.py --scenario normal
```

## Initial architecture

```text
Simulator now / Feather later
            |
            | HTTPS telemetry
            v
     Railway API + Postgres
            |
       rules and state
            |
            v
    n8n integrations
      |           |
    Slack       SMS later
```

- **Railway:** durable API, history, plant state, rules, and conversational context.
- **n8n:** schedules and delivery to Slack, SMS, or email.
- **LLM:** gives the plant a voice, but does not decide whether it needs water.
- **Shared contract:** [`contracts/telemetry.schema.json`](contracts/telemetry.schema.json)

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and
[`docs/HARDWARE.md`](docs/HARDWARE.md) for the working plan.

## Parts list

The core electronics order is:

| Qty | Part | Product |
|---:|---|---|
| 1 | ESP32-S3 Feather, 4 MB Flash / 2 MB PSRAM | [Adafruit PID 5477](https://www.adafruit.com/product/5477) |
| 1 | STEMMA Soil Sensor, I2C capacitive | [Adafruit PID 4026](https://www.adafruit.com/product/4026) |
| 1 | BME280 temperature/humidity/pressure sensor | [Adafruit PID 2652](https://www.adafruit.com/product/2652) |
| 1 | LTC4316 I2C address translator | [Adafruit PID 5914](https://www.adafruit.com/product/5914) |
| 2 | STEMMA QT/Qwiic JST-SH cable, 100 mm | [Adafruit PID 4210](https://www.adafruit.com/product/4210) |
| 1 | JST-PH to JST-SH STEMMA adapter cable, 200 mm | [Adafruit PID 4424](https://www.adafruit.com/product/4424) |
| 1 | 3.7 V 2500 mAh LiPo battery | [Adafruit PID 328](https://www.adafruit.com/product/328) |

**The parts above do not include an enclosure.** The leading enclosure candidate
is the [Polycase ML-46F](https://www.polycase.com/ml-46f), purchased separately.
It will also need suitable mounting hardware, cable openings, and ventilation for
the BME280. A data-capable USB-C cable and 5 V USB adapter are required but do not
need to be purchased if already available.

## Planned milestones

- [x] Define the telemetry contract
- [x] Create a hardware-free plant simulator
- [ ] Build the telemetry API and database
- [ ] Add deterministic plant-state and alert rules
- [ ] Add Slack conversation and notifications
- [ ] Write Feather CircuitPython firmware
- [ ] Calibrate the real soil sensor
- [ ] Add SMS and voice only if they improve the experience

## License

MIT
