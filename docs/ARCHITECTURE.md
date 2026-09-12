# Architecture

One Python/FastAPI service on Railway and one Postgres database. The service
receives telemetry, assembles conversation context, calls OpenRouter, and runs a
small monitoring/delivery worker. No agent loop, MCP, Redis, or n8n is required.

## Memory

Postgres stores readings, current device state, alert transitions and delivery
attempts, care events, completed conversation turns, and queued Slack requests.
Every completed turn stores the original user text, the full user-facing model
response, and a model-generated compact memory of the whole exchange. Each model
call receives compact memories from the past `MEMORY_COMPACT_DAYS` (default 7,
bounded by turn and total token-budget caps) plus the last `MEMORY_RECENT_TURNS` complete
turns verbatim (default 3, even if the conversation has been idle longer than a
week). Full history remains in Postgres and is not deleted
when prompt windows change. Memory is scoped to plant, source, and conversation
ID. Slack slash-command memory is shared by workspace and channel so everyone
in the dedicated plant channel speaks with the same remembered plant persona.

Conversation memory is narrative and untrusted. It never determines current
plant health. The server separately builds a compact authoritative state object:
current readings and timestamps, source/staleness/status, active conditions and
alerts, 24-hour min/max/change aggregates, and the three latest user-reported
care events. For real hardware it also includes the versioned, sourced care
profile in `plant_service/profiles/plant-001.json`. Raw reading rows are not
copied into the model prompt.

The mixed arrangement has two explicit moisture zones. Maranta, Fittonia and
Ctenanthe share a foliage-substrate zone that should remain evenly moist and
well drained; the Phalaenopsis requires open bark that approaches dry between
waterings. The single soil probe represents only the foliage zone. Numerical
soil-index targets remain null until the installed probe is calibrated in that
specific location. Ambient targets are shared operational compromises derived
from cited species guidance, not claims that every occupant has identical needs.

The stable system prompt contains identity, behavioral rules, data authority,
and safety constraints. A second system message contains only the authoritative
plant-state JSON. If older compact memories exist, a third system message labels
them as untrusted narrative data. Recent verbatim turns retain their normal user
and assistant roles; the current user message remains a plain user message.

`MEMORY_CONTEXT_TOKENS` defaults to 32,000 for the complete request. The server
reserves `OPENROUTER_MAX_OUTPUT_TOKENS` (default 1,200) plus a safety margin,
estimates the fixed system/state/current-message cost conservatively, admits the
newest verbatim turns, and then fills the remainder with newest compact memories.
This is a cross-model estimate rather than tokenizer-specific accounting, so the
three-characters-per-token assumption intentionally errs on the safe side.

OpenRouter is called once per reply with assembled context and a strict JSON
schema requiring `response` and `memory`. Set
`OPENROUTER_MODEL` to a model ID; leave it blank to use the account default.
Without a key, chat returns an explicitly labeled factual status response.
There is no model call during telemetry ingestion or periodic monitoring.

## Event-driven reporting

Sample locally, then send an event when a condition changes or measurements
differ meaningfully from the last transmission. Send a confirmation after 120
seconds if a potential problem remains. The simulator's `--event-driven` flag
implements this now; Feather firmware remains to be written and calibrated.

Send an hourly silent check-in even if nothing changes. It includes current
readings so questions can be answered from recent data, but does not append
unchanged values to reading history. This makes loss of connectivity detectable.
Historical event logs are irregularly sampled; they cannot support unbiased
time averages without accounting for that sampling policy.

The worker checks liveness every minute, creating one offline alert after three
hours without a fresh report. Sensor alerts require two distinct observations
spanning 120 seconds; repeatedly inspecting one old reading never confirms an
alert. Recovery uses separate thresholds, resolves pending notifications, and
sends no message. One notification is queued per sustained problem episode.
Failed alerts retry with backoff up to ten attempts; Slack replies retry five
times. Delivery is at-least-once: failure after Slack accepted a request can
rarely duplicate a message. There are no reminders for unchanged problems.

The demo is `demo-plant` / `simulator`; hardware is `plant-001` / `hardware`.
Demo alerts are suppressed unless `SLACK_INCLUDE_SIMULATOR=true` is set.
The hosted demo uses bounded synthetic values and no model calls. Monitoring
starts only after a device first reports. No-data hardware is never called healthy.

## Access and deployment

Owner APIs use `PLANT_API_KEY`. Hardware credentials can ingest only the configured
hardware ID; simulator credentials only ingest the demo. Neither device token
can read history or memory. Slack requests require HMAC signature verification,
a recent timestamp, and the configured workspace. An optional channel allowlist
keeps commands in the dedicated plant channel; an optional user allowlist can
further restrict deployments that are not intended to be communal.

Schema creation is idempotent under an advisory lock at startup. Database locks
coordinate alert creation, chat turns, and durable jobs across restarts. Start
with one service replica; keep Railway Serverless sleep disabled so the worker
continues running. `/healthz` checks Postgres; authenticated `/api/integrations`
reports the last successful monitoring cycle and connection configuration.

## Later

- MCP adapter if an external assistant needs to query the plant.
- Vercel AI SDK if streaming or model-driven tools become necessary.
- Slack mentions/DM events; the current interface is `/plant` commands.
- Species profiles, calibration, and data-retention policies.
- Hardware firmware, Wi-Fi retry/buffering, and battery testing.

Soil moisture is a relative calibrated index, not volumetric water content.
Thresholds are provisional and need plant-specific tuning.

Sources: [OpenRouter API](https://openrouter.ai/docs/api_reference/overview),
[Slack commands](https://docs.slack.dev/interactivity/implementing-slash-commands/),
[MCP versions](https://ts.sdk.modelcontextprotocol.io/v2/protocol-versions).
