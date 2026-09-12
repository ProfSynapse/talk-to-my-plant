import hashlib
import hmac
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlparse

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .models import Care, Chat, Telemetry
from .service import Conflict, PlantService
from .demo import Demo

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)  # Slack URLs contain secrets.
log = logging.getLogger("plant")


def valid_token(value, expected):
    return bool(expected) and hmac.compare_digest(value, "Bearer " + expected)


def slack_url(value):
    parsed = urlparse(value)
    return (parsed.scheme == "https" and parsed.hostname == "hooks.slack.com"
            and parsed.port in (None, 443) and not parsed.username and not parsed.password
            and parsed.path.startswith(("/commands/", "/services/")))


def create_app(service=None, *, settings=None, run_worker=True):
    cfg = dict(os.environ if settings is None else settings)
    stop = threading.Event()

    def owner(authorization: str = Header(default="")):
        if not valid_token(authorization, cfg.get("PLANT_API_KEY", "")):
            raise HTTPException(401, "Valid owner bearer token required", headers={"WWW-Authenticate":"Bearer"})

    @asynccontextmanager
    async def lifespan(app):
        if len(cfg.get("PLANT_API_KEY", "")) < 32:
            raise RuntimeError("PLANT_API_KEY must contain at least 32 characters")
        app.state.service = service or PlantService(cfg["DATABASE_URL"],
            memory_recent_turns=int(cfg.get("MEMORY_RECENT_TURNS", "3")),
            memory_compact_days=int(cfg.get("MEMORY_COMPACT_DAYS", "7")),
            memory_compact_turns=int(cfg.get("MEMORY_COMPACT_TURNS", "200")),
            memory_context_tokens=int(cfg.get("MEMORY_CONTEXT_TOKENS", "32000")),
            openrouter_max_output_tokens=int(cfg.get("OPENROUTER_MAX_OUTPUT_TOKENS", "1200")),
            confirm_seconds=int(cfg.get("ALERT_CONFIRM_SECONDS", "120")),
            offline_seconds=int(cfg.get("OFFLINE_AFTER_SECONDS", "10800")),
            openrouter_key=cfg.get("OPENROUTER_API_KEY", ""),
            primary_model=(cfg.get("OPENROUTER_PRIMARY_MODEL", "")
                           or cfg.get("OPENROUTER_MODEL", "")),
            fallback_model=cfg.get("OPENROUTER_FALLBACK_MODEL", ""))
        app.state.service.initialize()
        thread = None
        if run_worker:
            def work():
                last_check = 0
                last_demo = 0
                demo = Demo()
                while not stop.is_set():
                    try:
                        if cfg.get("DEMO_ENABLED") == "true" and time.time() - last_demo >= 300:
                            demo.tick(app.state.service, time.time())
                            last_demo = time.time()
                        if time.monotonic() - last_check >= 60:
                            app.state.service.check_offline()
                            last_check = time.monotonic()
                        webhook = cfg.get("SLACK_WEBHOOK_URL", "")
                        if webhook and slack_url(webhook):
                            app.state.service.deliver_alert(webhook, include_simulator=cfg.get("SLACK_INCLUDE_SIMULATOR") == "true")
                        app.state.service.process_slack_job()
                    except Exception:
                        # Never print exception objects containing credentials or response URLs.
                        log.error("Background work failed; retrying on next cycle")
                    stop.wait(2)
            thread = threading.Thread(target=work, name="plant-worker", daemon=True)
            thread.start()
        yield
        stop.set()
        if thread:
            thread.join(timeout=45)
        if service is None:
            app.state.service.close()

    app = FastAPI(title="Talk to My Plant", version="0.3.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def body_limit(request, call_next):
        try:
            length = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"detail":"Invalid content length"}, status_code=400)
        if length > 65536:
            return JSONResponse({"detail":"Request too large"}, status_code=413)
        if request.method == "POST":
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 65536:
                    return JSONResponse({"detail":"Request too large"}, status_code=413)
            request._body = bytes(body)
        return await call_next(request)

    @app.exception_handler(Conflict)
    async def conflict(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.get("/", response_class=HTMLResponse)
    def home():
        return """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Talk to My Plant</title><style>body{max-width:650px;margin:12vh auto;padding:24px;font:18px/1.6 system-ui;background:#f4f7ef;color:#233827}h1{font-size:40px}a{color:#236040}</style>
        <h1>🌱 Talk to My Plant</h1><p>The plant service is running.</p><p>Sensor history, conversation memory, and quiet monitoring live in Postgres. Private data requires a bearer token.</p>
        <p><a href="https://github.com/ProfSynapse/talk-to-my-plant">Source &amp; setup instructions</a> · <a href="/healthz">Service health</a></p></html>"""

    @app.get("/healthz")
    def health():
        try:
            with app.state.service.pool.connection() as db:
                db.execute("SELECT 1")
        except Exception:
            raise HTTPException(503, "Database unavailable")
        return {"status":"ok", "database":"connected"}

    @app.get("/api/openapi.json", dependencies=[Depends(owner)])
    def schema():
        return app.openapi()

    @app.post("/api/telemetry")
    def telemetry(message: Telemetry, authorization: str = Header(default="")):
        permitted = valid_token(authorization, cfg.get("PLANT_API_KEY", ""))
        if message.source == "hardware" and message.device_id == cfg.get("DEVICE_ID", "plant-001"):
            permitted |= valid_token(authorization, cfg.get("DEVICE_API_KEY", ""))
        if message.source == "simulator" and message.device_id == "demo-plant":
            permitted |= valid_token(authorization, cfg.get("SIMULATOR_API_KEY", ""))
        if not permitted:
            raise HTTPException(401, "Valid token scoped to this device/source required")
        return app.state.service.ingest(message)

    @app.get("/api/plants/{device_id}/status", dependencies=[Depends(owner)])
    def status(device_id: str, source: str = Query("hardware", pattern="^(hardware|simulator)$"), limit: int = Query(24, ge=1, le=100)):
        return app.state.service.status(device_id, source, limit)

    @app.post("/api/chat", dependencies=[Depends(owner)])
    def chat(message: Chat):
        return app.state.service.chat(message)

    @app.post("/api/care", dependencies=[Depends(owner)])
    def care(message: Care):
        with app.state.service.pool.connection() as db:
            row = db.execute("INSERT INTO care_events(device_id,source,note) VALUES(%s,%s,%s) RETURNING id,created_at",
                             (message.device_id,message.source,message.note)).fetchone()
        return row

    @app.get("/api/integrations", dependencies=[Depends(owner)])
    def integrations():
        with app.state.service.pool.connection() as db:
            monitor = db.execute("SELECT last_success FROM worker_health WHERE name='monitor'").fetchone()
            backlog = db.execute("SELECT count(*) AS count FROM slack_jobs WHERE delivered_at IS NULL").fetchone()
        primary_model = (cfg.get("OPENROUTER_PRIMARY_MODEL", "")
                         or cfg.get("OPENROUTER_MODEL", ""))
        return {"openrouter_configured":bool(cfg.get("OPENROUTER_API_KEY")),
            "model":primary_model or "OpenRouter account default",
            "primary_model":primary_model or "OpenRouter account default",
            "fallback_model":cfg.get("OPENROUTER_FALLBACK_MODEL") or None,
            "memory_recent_turns":app.state.service.memory_recent_turns,
            "memory_compact_days":app.state.service.memory_compact_days,
            "memory_compact_turns":app.state.service.memory_compact_turns,
            "memory_context_tokens":app.state.service.memory_context_tokens,
            "openrouter_max_output_tokens":app.state.service.openrouter_max_output_tokens,
            "slack_alerts_configured":bool(cfg.get("SLACK_WEBHOOK_URL")),
            "slack_commands_configured":all(cfg.get(k) for k in ("SLACK_SIGNING_SECRET","SLACK_TEAM_ID")),
            "monitor":monitor, "pending_slack_replies":backlog["count"]}

    @app.post("/slack/commands")
    async def slack_commands(request: Request):
        secret = cfg.get("SLACK_SIGNING_SECRET", "")
        if not secret:
            raise HTTPException(503, "Slack signing secret not configured")
        body = await request.body()
        timestamp = request.headers.get("x-slack-request-timestamp", "")
        if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > 300:
            raise HTTPException(401, "Expired Slack request")
        expected = "v0=" + hmac.new(secret.encode(), b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, request.headers.get("x-slack-signature", "")):
            raise HTTPException(401, "Invalid Slack signature")
        params = {k:v[0] for k,v in parse_qs(body.decode()).items()}
        if not cfg.get("SLACK_TEAM_ID") or params.get("team_id") != cfg["SLACK_TEAM_ID"]:
            raise HTTPException(403, "Workspace not allowed")
        user_id = params.get("user_id", "")
        allowed_users = {value.strip() for value in cfg.get("SLACK_ALLOWED_USER_IDS", "").split(",") if value.strip()}
        if not user_id or (allowed_users and "*" not in allowed_users and user_id not in allowed_users):
            raise HTTPException(403, "User not allowed")
        channel_id = params.get("channel_id", "")
        allowed_channels = {value.strip() for value in cfg.get("SLACK_ALLOWED_CHANNEL_IDS", "").split(",") if value.strip()}
        if not channel_id or (allowed_channels and "*" not in allowed_channels and channel_id not in allowed_channels):
            raise HTTPException(403, "Channel not allowed")
        response_url = params.get("response_url", "")
        if not slack_url(response_url):
            raise HTTPException(400, "Invalid Slack response URL")
        text = params.get("text", "How am I doing?").strip() or "How am I doing?"
        if len(text) > 4000:
            raise HTTPException(400, "Message too long")
        source, device_id = "hardware", cfg.get("DEVICE_ID", "plant-001")
        if text == "demo" or text.startswith("demo "):
            source, device_id = "simulator", "demo-plant"
            text = text[4:].strip() or "How am I doing?"
        # A channel shares one plant memory across all participating workspace members.
        conversation = ":".join(["slack", params["team_id"], channel_id, source])
        request_id = hashlib.sha256(timestamp.encode() + b":" + body).hexdigest()
        # Commit before acknowledging Slack; worker can resume after restart.
        with app.state.service.pool.connection() as db:
            db.execute("""INSERT INTO slack_jobs(id,conversation_id,device_id,source,text,response_url)
                          VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                       (request_id,conversation,device_id,source,text,response_url))
        return {"response_type":"in_channel", "text":"🌱 Checking my readings and memory…"}

    return app


app = create_app()
