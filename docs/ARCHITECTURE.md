# Initial architecture

## Principle

The backend consumes one versioned telemetry contract regardless of whether a
reading came from the simulator or the physical Feather. Hardware access stays
behind a device-side adapter.

## Components

1. The simulator or Feather sends an HTTPS telemetry payload.
2. A Railway API authenticates the device, validates the payload, and stores it
   in Postgres.
3. Deterministic rules derive plant conditions from readings, trends, and recent
   care events. Hysteresis and suppression prevent repeated noisy alerts.
4. n8n delivers actionable events to Slack first; SMS and email can be added
   without changing the device.
5. A conversational service answers questions using stored readings and care
   history. An LLM controls phrasing/personality, never the factual plant state.

## Suggested first vertical slice

- `POST /api/telemetry`
- One Postgres readings table
- Soil-low and battery-low rules
- One Slack notification destination
- `GET /api/plants/plant-001/status`
- A reply to “How are you?” grounded in the most recent reading

## Open decisions

- TypeScript versus Python for the Railway service
- Slack app versus n8n Slack node for the first conversational interface
- Plant species and calibrated wet/dry sensor values
- USB-powered with battery backup versus battery-first operation
