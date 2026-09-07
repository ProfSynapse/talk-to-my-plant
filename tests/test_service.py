import hashlib
import hmac
import json
import os
import time
import unittest
import uuid
from datetime import timedelta
from urllib.parse import urlencode

import httpx
from fastapi.testclient import TestClient

from plant_service.app import create_app
from plant_service.models import Chat, Telemetry
from plant_service.service import PlantService, Conflict, utcnow
from simulator.reporting import ReportingPolicy


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL required for Postgres integration tests")
class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests = []
        def mock(request):
            cls.requests.append(request)
            if request.url.host == "openrouter.ai":
                return httpx.Response(200, json={"model":"test-model", "choices":[{"message":{"content":"My remembered reply"}}]})
            return httpx.Response(200, text="ok")
        cls.service = PlantService(os.environ["TEST_DATABASE_URL"], memory_messages=3,
                                  openrouter_key="test-key",http=httpx.Client(transport=httpx.MockTransport(mock)))
        cls.service.initialize()

    @classmethod
    def tearDownClass(cls):
        cls.service.close()

    def setUp(self):
        self.device_id = "test-" + uuid.uuid4().hex
        self.now = utcnow()

    def payload(self, offset=0, soil=52, battery=92, kind="event"):
        return Telemetry(device_id=self.device_id, source="simulator", recorded_at=self.now+timedelta(seconds=offset),
            report_kind=kind, readings={"soil_moisture":soil,"temperature_f":72,"humidity":48,
            "pressure_hpa":1013,"battery_percent":battery,"battery_voltage":4.12})

    def ingest(self, **kwargs):
        p = self.payload(**kwargs)
        return self.service.ingest(p, now=p.recorded_at)

    def test_persistent_alert_deduplicates_and_recovers_with_hysteresis(self):
        self.ingest(offset=-240, soil=20)
        self.assertEqual(self.service.status(self.device_id,"simulator")["active_alerts"], [])
        self.ingest(offset=-120, soil=21)
        self.ingest(offset=-60, soil=27)
        self.assertEqual(len(self.service.status(self.device_id,"simulator")["active_alerts"]),1)
        self.ingest(offset=0,soil=35)
        self.assertEqual(self.service.status(self.device_id,"simulator")["active_alerts"], [])

    def test_duplicate_and_old_reports_cannot_replace_state(self):
        self.ingest()
        self.assertFalse(self.ingest()["logged"])
        self.ingest(offset=-100, soil=4)
        snapshot = self.service.status(self.device_id,"simulator")
        self.assertEqual(snapshot["device"]["latest"]["soil_moisture"],52)
        self.assertEqual(len(snapshot["recent_readings"]),2)

    def test_checkin_updates_liveness_without_history_noise(self):
        self.ingest(offset=-180)
        self.ingest(kind="checkin")
        snapshot = self.service.status(self.device_id,"simulator")
        self.assertEqual(len(snapshot["recent_readings"]),1)
        self.assertEqual(snapshot["device"]["observed_at"],self.now)

    def test_offline_only_once_and_recovery_is_silent(self):
        self.ingest()
        self.service.check_offline(self.now+timedelta(hours=4))
        self.service.check_offline(self.now+timedelta(hours=5))
        alerts = self.service.status(self.device_id,"simulator")["active_alerts"]
        self.assertEqual([a["kind"] for a in alerts],["device_offline"])
        self.ingest(offset=1)
        self.assertEqual(self.service.status(self.device_id,"simulator")["active_alerts"],[])

    def test_memory_is_bounded_scoped_and_requests_idempotent(self):
        conversation = uuid.uuid4().hex
        self.ingest()
        for i in range(4):
            msg = Chat(request_id=uuid.uuid4().hex,conversation_id=conversation,device_id=self.device_id,source="simulator",text=f"message-{i}")
            self.service.chat(msg)
        sent = json.loads(self.requests[-1].content)["messages"]
        memory = sent[2:-1]
        self.assertEqual(len(memory),3)
        self.assertEqual(memory[-1]["content"],"My remembered reply")
        self.assertIn("recent_readings",sent[1]["content"])
        before = len(self.requests)
        self.assertTrue(self.service.chat(msg)["cached"])
        self.assertEqual(len(self.requests),before)
        with self.assertRaises(Conflict):
            self.service.chat(msg.model_copy(update={"text":"different"}))
        other = msg.model_copy(update={"request_id":uuid.uuid4().hex,"conversation_id":"other-"+conversation})
        self.service.chat(other)
        self.assertEqual(len(json.loads(self.requests[-1].content)["messages"]),3)

    def test_simulated_alerts_never_send_by_default(self):
        self.ingest(offset=-180,soil=10)
        self.ingest(soil=10)
        before = len(self.requests)
        self.service.deliver_alert("https://hooks.slack.com/services/test")
        self.assertEqual(len(self.requests),before)

    def test_http_auth_validation_and_slack_signature(self):
        owner = "o"*48
        settings = {"PLANT_API_KEY":owner,"DEVICE_API_KEY":"d"*48,"DEVICE_ID":"plant-001",
                    "SLACK_SIGNING_SECRET":"secret","SLACK_TEAM_ID":"T1","SLACK_ALLOWED_USER_IDS":"U1"}
        with TestClient(create_app(self.service,settings=settings,run_worker=False)) as client:
            self.assertEqual(client.get("/healthz").status_code,200)
            self.assertEqual(client.get("/api/plants/plant-001/status").status_code,401)
            data = self.payload().model_dump(mode="json")
            self.assertEqual(client.post("/api/telemetry",json=data,headers={"Authorization":"Bearer "+"d"*48}).status_code,401)
            headers = {"Authorization":"Bearer "+owner}
            self.assertEqual(client.post("/api/telemetry",json=data,headers=headers).status_code,200)
            data["readings"]["soil_moisture"] = 101
            self.assertEqual(client.post("/api/telemetry",json=data,headers=headers).status_code,422)
            body = urlencode({"team_id":"T1","user_id":"U1","channel_id":"C1","text":"demo how are you?",
                              "response_url":"https://hooks.slack.com/commands/test"}).encode()
            ts = str(int(time.time()))
            signature = "v0="+hmac.new(b"secret",b"v0:"+ts.encode()+b":"+body,hashlib.sha256).hexdigest()
            slack_headers = {"x-slack-request-timestamp":ts,"x-slack-signature":signature,"content-type":"application/x-www-form-urlencoded"}
            self.assertEqual(client.post("/slack/commands",content=body,headers=slack_headers).status_code,200)
            self.assertEqual(client.post("/slack/commands",content=body,headers=slack_headers).status_code,200)
            with self.service.pool.connection() as db:
                row = db.execute("SELECT count(*) AS n FROM slack_jobs WHERE id=%s",(hashlib.sha256(ts.encode()+b":"+body).hexdigest(),)).fetchone()
                self.assertEqual(row["n"],1)
            slack_headers["x-slack-signature"] = "bad"
            self.assertEqual(client.post("/slack/commands",content=body,headers=slack_headers).status_code,401)


class ReportingTests(unittest.TestCase):
    def test_quiet_checkin_and_problem_confirmation(self):
        policy = ReportingPolicy()
        p = {"conditions":["comfortable"],"readings":{"soil_moisture":50,"temperature_f":72,"humidity":48,"battery_percent":90}}
        self.assertEqual(policy.select(p,0)["report_kind"],"event")
        self.assertIsNone(policy.select(p,30))
        self.assertEqual(policy.select(p,3600)["report_kind"],"checkin")
        p["conditions"] = ["needs_water"]
        p["readings"]["soil_moisture"] = 20
        self.assertEqual(policy.select(p,3610)["report_kind"],"event")
        self.assertIsNone(policy.select(p,3640))
        self.assertEqual(policy.select(p,3730)["report_kind"],"event")
        self.assertIsNone(policy.select(p,3760))
