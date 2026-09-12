# Connect Slack and OpenRouter

The backend is hosted at https://plant-api-production-68c9.up.railway.app.
Configure secrets in the `plant-api` service's Railway Variables tab.

## OpenRouter

Set `OPENROUTER_API_KEY` to a key for this project. Set
`OPENROUTER_PRIMARY_MODEL` to the preferred OpenRouter model ID and
`OPENROUTER_FALLBACK_MODEL` to the backup model ID. If the primary model is
unavailable, rate-limited, or refuses the request, OpenRouter tries the fallback
within the same API request. Leave the primary blank only if you intentionally
want to use the OpenRouter account default. `OPENROUTER_MODEL` remains a
temporary backward-compatible alias for the primary model.
`MEMORY_RECENT_TURNS=3` controls the verbatim rolling window.
`MEMORY_COMPACT_DAYS=7`, `MEMORY_COMPACT_TURNS=200`, and
`MEMORY_CONTEXT_TOKENS=32000` bound the compact-memory layer and the entire
request. `OPENROUTER_MAX_OUTPUT_TOKENS=1200` is reserved from that ceiling before
history is selected. Postgres keeps the full text and compact memory; changing
prompt windows does not delete records.

## Slack app

1. Open https://api.slack.com/apps and create an app **from a manifest**.
2. Paste [`slack-manifest.json`](slack-manifest.json) and select your workspace.
3. Install the app. Slack requires the manifest's `bot_user` whenever a slash
   command is present. In **Basic Information**, copy its Signing Secret into
   Railway as `SLACK_SIGNING_SECRET`.
4. Set `SLACK_TEAM_ID` to your workspace ID and `SLACK_ALLOWED_CHANNEL_IDS` to
   the dedicated plant channel ID. Leave `SLACK_ALLOWED_USER_IDS` blank so every
   workspace member can talk to the plant in that channel. A comma-separated
   user allowlist remains available for private deployments.
5. In **Incoming Webhooks**, activate the feature if Slack has not already done
   so, then add a webhook for the channel where plant alerts should go. Slack
   may ask you to reinstall the app to add the `incoming-webhook` permission.
   Store the generated URL as `SLACK_WEBHOOK_URL` in Railway.

Never paste credentials into the public repository or issue tracker. You can set
them in the Railway UI, or use `railway variable set --service plant-api --stdin VARIABLE_NAME`
to supply a value through stdin.

Try these commands after the app is installed:

```text
/plant demo how are you?
/plant demo what did we just talk about?
/plant how are you?
/plant watered
```

`demo` selects the simulated plant. Without it, the command uses the real
`plant-001`, which has no readings until hardware is connected. The `watered`
command logs a user-reported care event; the model doesn't pretend it measured
that action. `/plant demo watered` works for testing without changing real care
records. The question and reply are public in the allowed channel, and all
members there share the same plant conversation memory. Alerts go to the
webhook's chosen channel and only fire for persistent problems or missing
check-ins.

Ordinary Slack DMs/mentions and voice are not implemented yet. The slash command
provides the first conversation interface with persistent memory.

Signed Slack requests are committed to a durable queue before acknowledgment.
The background worker calls OpenRouter and posts the answer to Slack's response
URL. Slack retries reuse the same queue item and chat turn. If the model key is
absent, the reply clearly says it is a status-only reply.
