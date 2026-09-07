CREATE TABLE IF NOT EXISTS devices (
 device_id text NOT NULL, source text NOT NULL CHECK (source IN ('hardware','simulator')),
 last_seen timestamptz NOT NULL DEFAULT now(), observed_at timestamptz NOT NULL,
 latest jsonb NOT NULL, conditions jsonb NOT NULL DEFAULT '[]',
 PRIMARY KEY(device_id,source)
);
CREATE TABLE IF NOT EXISTS readings (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 device_id text NOT NULL, source text NOT NULL, recorded_at timestamptz NOT NULL,
 received_at timestamptz NOT NULL DEFAULT now(), payload jsonb NOT NULL,
 UNIQUE(device_id, source, recorded_at),
 FOREIGN KEY(device_id,source) REFERENCES devices(device_id,source)
);
CREATE INDEX IF NOT EXISTS readings_lookup ON readings(device_id,source,recorded_at DESC);
CREATE TABLE IF NOT EXISTS alert_state (
 device_id text NOT NULL, source text NOT NULL, kind text NOT NULL,
 pending_since timestamptz NOT NULL, last_observed timestamptz NOT NULL,
 observations integer NOT NULL DEFAULT 1, active boolean NOT NULL DEFAULT false,
 PRIMARY KEY(device_id,source,kind)
);
CREATE TABLE IF NOT EXISTS alerts (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 device_id text NOT NULL, source text NOT NULL, kind text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), resolved_at timestamptz,
 notified_at timestamptz, attempts integer NOT NULL DEFAULT 0,
 next_attempt timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS care_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 device_id text NOT NULL, source text NOT NULL, note text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS chat_turns (
 request_id text PRIMARY KEY, conversation_id text NOT NULL,
 device_id text NOT NULL, source text NOT NULL,
 user_text text NOT NULL, assistant_text text, model text,
 created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz
);
CREATE INDEX IF NOT EXISTS chat_memory ON chat_turns(conversation_id,device_id,source,created_at DESC);
CREATE TABLE IF NOT EXISTS slack_jobs (
 id text PRIMARY KEY, conversation_id text NOT NULL, device_id text NOT NULL,
 source text NOT NULL, text text NOT NULL, response_url text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), delivered_at timestamptz,
 attempts integer NOT NULL DEFAULT 0, next_attempt timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS worker_health (
 name text PRIMARY KEY, last_success timestamptz NOT NULL
);
