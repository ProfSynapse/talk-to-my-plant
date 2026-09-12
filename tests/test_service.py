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
from plant_service.rules import conditions
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
                content = json.dumps({"response":"My remembered reply",
                                      "memory":"User spoke; plant replied."})
                return httpx.Response(200, json={"model":"test-model", "choices":[{"message":{"content":content}}]})
            return httpx.Response(200, text="ok")
        cls.service = PlantService(os.environ["TEST_DATABASE_URL"], memory_recent_turns=1,
                                  memory_compact_days=7, memory_compact_turns=2,
                                  openrouter_key="test-key",
                                  primary_model="primary-test-model",
                                  fallback_model="fallback-test-model",
                                  http=httpx.Client(transport=httpx.MockTransport(mock)))
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
        request_body = json.loads(self.requests[-1].content)
        self.assertEqual(
            request_body["models"],
            ["primary-test-model", "fallback-test-model"],
        )
        self.assertEqual(request_body["provider"], {"require_parameters": True})
        self.assertEqual(request_body["max_tokens"], 1200)
        self.assertLessEqual(
            self.service.estimate_tokens(request_body["messages"]) +
            request_body["max_tokens"],
            self.service.memory_context_tokens,
        )
        schema = request_body["response_format"]["json_schema"]["schema"]
        self.assertEqual(schema["required"], ["response", "memory"])
        sent = request_body["messages"]
        compact = json.loads(sent[2]["content"].split("\n", 1)[1])
        self.assertEqual(len(compact["entries"]), 2)
        self.assertEqual(compact["entries"][-1]["memory"], "User spoke; plant replied.")
        recent = sent[3:-1]
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[-1]["content"], "My remembered reply")
        state = json.loads(sent[1]["content"].split("\n", 1)[1])
        self.assertNotIn("recent_readings", state)
        self.assertIn("trends_24h", state)
        before = len(self.requests)
        cached = self.service.chat(msg)
        self.assertTrue(cached["cached"])
        self.assertEqual(cached["response"], "My remembered reply")
        self.assertEqual(cached["memory"], "User spoke; plant replied.")
        self.assertEqual(len(self.requests),before)
        with self.assertRaises(Conflict):
            self.service.chat(msg.model_copy(update={"text":"different"}))
        other = msg.model_copy(update={"request_id":uuid.uuid4().hex,"conversation_id":"other-"+conversation})
        self.service.chat(other)
        self.assertEqual(len(json.loads(self.requests[-1].content)["messages"]),3)

    def test_hardware_care_profile_and_species_thresholds(self):
        profile = self.service.status("plant-001", "hardware")["care_profile"]
        self.assertEqual(len(profile["occupants"]), 5)
        self.assertEqual(profile["moisture_zones"][0]["id"], "foliage_substrate")
        self.assertEqual(profile["moisture_zones"][0]["telemetry_field"], "soil_moisture")
        self.assertIsNone(profile["moisture_zones"][0]["calibrated_sensor_targets"])
        self.assertEqual(self.service.soil_thresholds(
                         "plant-001", "hardware", placement="bench_air"),
                         (None, None))
        self.assertNotIn("needs_water", conditions(
            {"soil_moisture": 5, "temperature_f": 72, "humidity": 60,
             "battery_percent": 90}, soil_alert_below=None,
            soil_recover_above=None))
        self.assertIn("too_cold", conditions({"soil_moisture":50, "temperature_f":60,
            "humidity":60, "battery_percent":90}))
        self.assertIn("air_too_dry", conditions({"soil_moisture":50, "temperature_f":72,
            "humidity":44, "battery_percent":90}))
        self.service.chat(Chat(request_id=uuid.uuid4().hex,
            conversation_id=uuid.uuid4().hex, device_id="plant-001",
            source="hardware", text="Which plants live here?"))
        request_body = json.loads(self.requests[-1].content)
        state = json.loads(request_body["messages"][1]["content"].split("\n", 1)[1])
        self.assertEqual(len(state["care_profile"]["occupants"]), 5)

    def test_uncalibrated_hardware_logs_raw_soil_without_water_alert(self):
        message = Telemetry(
            schema_version="1.2", device_id=self.device_id, source="hardware",
            sensor_placement="bench_air",
            recorded_at=self.now, report_kind="event",
            readings={"soil_raw": 711, "temperature_f": 72, "humidity": 60,
                      "pressure_hpa": 1013, "battery_percent": 90,
                      "battery_voltage": 4.12})
        result = self.service.ingest(message, now=self.now)
        self.assertTrue(result["logged"])
        snapshot = self.service.status(self.device_id, "hardware")
        self.assertEqual(snapshot["device"]["latest"]["soil_raw"], 711)
        self.assertEqual(snapshot["device"]["sensor_placement"], "bench_air")
        self.assertIsNone(snapshot["device"]["latest"]["soil_moisture"])
        self.assertNotIn("needs_water", snapshot["device"]["conditions"])
        self.assertIn("probe placement bench_air; raw capacitance 711",
                      self.service.fallback(snapshot))

    def test_simulated_alerts_never_send_by_default(self):
        self.ingest(offset=-180,soil=10)
        self.ingest(soil=10)
        before = len(self.requests)
        self.service.deliver_alert("https://hooks.slack.com/services/test")
        self.assertEqual(len(self.requests),before)

    def test_http_auth_validation_and_slack_signature(self):
        owner = "o"*48
        settings = {"PLANT_API_KEY":owner,"DEVICE_API_KEY":"d"*48,"DEVICE_ID":"plant-001",
                    "SLACK_SIGNING_SECRET":"secret","SLACK_TEAM_ID":"T1","SLACK_ALLOWED_CHANNEL_IDS":"C1"}
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
            response = client.post("/slack/commands",content=body,headers=slack_headers)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()["response_type"],"in_channel")
            self.assertEqual(client.post("/slack/commands",content=body,headers=slack_headers).status_code,200)
            with self.service.pool.connection() as db:
                row = db.execute("SELECT count(*) AS n, min(conversation_id) AS conversation_id FROM slack_jobs WHERE id=%s",(hashlib.sha256(ts.encode()+b":"+body).hexdigest(),)).fetchone()
                self.assertEqual(row["n"],1)
                self.assertEqual(row["conversation_id"],"slack:T1:C1:simulator")
            other_user_body = urlencode({"team_id":"T1","user_id":"U2","channel_id":"C1","text":"demo hello",
                                         "response_url":"https://hooks.slack.com/commands/test"}).encode()
            other_user_signature = "v0="+hmac.new(b"secret",b"v0:"+ts.encode()+b":"+other_user_body,hashlib.sha256).hexdigest()
            other_user_headers = {**slack_headers,"x-slack-signature":other_user_signature}
            self.assertEqual(client.post("/slack/commands",content=other_user_body,headers=other_user_headers).status_code,200)
            wrong_channel_body = urlencode({"team_id":"T1","user_id":"U2","channel_id":"C2","text":"demo hello",
                                            "response_url":"https://hooks.slack.com/commands/test"}).encode()
            wrong_channel_signature = "v0="+hmac.new(b"secret",b"v0:"+ts.encode()+b":"+wrong_channel_body,hashlib.sha256).hexdigest()
            wrong_channel_headers = {**slack_headers,"x-slack-signature":wrong_channel_signature}
            self.assertEqual(client.post("/slack/commands",content=wrong_channel_body,headers=wrong_channel_headers).status_code,403)
            self.service.process_slack_job()
            self.assertEqual(json.loads(self.requests[-1].content)["response_type"],"in_channel")
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
