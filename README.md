# Talk to My Plant

An experimental IoT plant companion: sensor readings become useful alerts and
natural-language conversations grounded in the plant's actual condition.

The project is intentionally split at the telemetry boundary. The software can
be built against simulated readings today, then use the real Adafruit hardware
later without changing the backend, alerts, or chat integrations.

## Hosted service

[Live service](https://plant-api-production-68c9.up.railway.app) ·
[Railway project](https://railway.com/project/b000ee9a-4988-4818-b020-f947c91439b5)

The API and Postgres run on Railway. A separate `demo-plant` supplies clearly
labeled simulated readings. Set your OpenRouter key and install the Slack app
using [the connection guide](docs/SLACK.md) to enable model replies and delivery.

Postgres stores sensor logs, care events, alert state, and conversation memory.
Each reply sees the last 20 messages by default plus recent sensor/care context.
Change `MEMORY_MESSAGES`, `OPENROUTER_PRIMARY_MODEL`, or
`OPENROUTER_FALLBACK_MODEL` in Railway to tune that behavior. OpenRouter tries
the two configured models in order and reports which one answered.
This version makes one OpenRouter call per reply; it needs no agent loop or MCP.

## Start without hardware

The standalone simulator requires Python 3.11+ and no third-party packages.

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
export TELEMETRY_URL="https://plant-api-production-68c9.up.railway.app/api/telemetry"
export PLANT_API_KEY="your-simulator-token"
python3 simulator/plant_simulator.py --device-id demo-plant --event-driven
```

The simulator sends meaningful changes, a confirmation of persistent problems,
and an hourly silent check-in. The server sends Slack alerts only for sustained
problems or missed check-ins. Simulated alerts are suppressed by default.

## Architecture

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
    Slack / OpenRouter
```

- **Railway:** durable API, history, plant state, rules, and conversational context.
- **Postgres:** sensor history, recent-message memory, care records, and durable jobs.
- **OpenRouter:** your choice of model, with sensor and conversation context supplied.
- **Slack:** `/plant` conversation and webhook notifications for problems.
- **Monitoring:** rules run quietly; no scheduled LLM calls or healthy-status messages.
- **Shared contract:** [`contracts/telemetry.schema.json`](contracts/telemetry.schema.json)

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and
[`docs/HARDWARE.md`](docs/HARDWARE.md) for the working plan.

## Run the service locally

Requires Python 3.12+ and Postgres. Create a virtual environment, install
`requirements.txt`, and set the variables shown in `.env.example` (the service
reads environment variables; it does not automatically load `.env` files).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# Set DATABASE_URL and a random PLANT_API_KEY of at least 32 characters.
.venv/bin/uvicorn plant_service.app:app --port 8080
```

Owner endpoints require `Authorization: Bearer <PLANT_API_KEY>`:

| Endpoint | Purpose |
|---|---|
| `POST /api/telemetry` | Device event or check-in; scoped device tokens also accepted |
| `GET /api/plants/{device_id}/status?source=hardware` | Current state, recent logs, alerts, and care history |
| `POST /api/chat` | Reply using stored memory and readings |
| `POST /api/care` | Log a user-reported care event |
| `GET /api/integrations` | Connection configuration and monitor health |
| `GET /api/openapi.json` | Full API schema |

Chat body example:

```json
{
  "request_id": "unique-message-id",
  "conversation_id": "my-conversation",
  "device_id": "demo-plant",
  "source": "simulator",
  "text": "How are you doing?"
}
```

Reuse a request ID only to retry the same message. Conversation IDs isolate
memory. Without an OpenRouter key, responses explicitly use factual status only.

Run tests with `TEST_DATABASE_URL` pointing to a disposable Postgres database:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Database tests skip when that variable is absent. GitHub Actions provisions
Postgres and runs the complete suite. Deploy with `railway up --service plant-api`;
keep the service running continuously for the background monitor.

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
- [x] Build and deploy the telemetry API and Postgres
- [x] Add deterministic plant-state and alert rules
- [x] Add durable conversation memory and configurable OpenRouter replies
- [x] Implement Slack commands, notifications, and installation manifest
- [ ] Connect personal OpenRouter and Slack credentials
- [ ] Write Feather CircuitPython firmware
- [ ] Calibrate the real soil sensor
- [ ] Add SMS and voice only if they improve the experience

## License

MIT
