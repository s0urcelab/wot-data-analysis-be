import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

# Avoid touching the service database or starting the scheduler during imports.
with tempfile.TemporaryDirectory() as startup_directory:
    with patch.dict(os.environ, {"ENABLE_SCHEDULER": "false", "DATABASE_PATH": str(Path(startup_directory) / "startup.sqlite3")}):
        import app as backend

from db import get_db


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = backend.create_app({"TESTING": True, "ENABLE_SCHEDULER": False,
                                       "DATABASE_PATH": str(Path(self.directory.name) / "test.sqlite3")})
        self.client = self.app.test_client()
        with self.app.app_context():
            connection = get_db()
            for tank_id in range(1, 26):
                connection.execute(
                    "INSERT INTO tanks(tank_id,nation,type,tier,name,premium,collector_vehicle,listed,"
                    "mastery_65,mastery_85,mastery_95,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (tank_id, "china" if tank_id % 2 else "usa", "heavyTank", 8, f"Tank {tank_id}",
                     tank_id % 2, int(tank_id == 1), int(tank_id != 25),
                     100 + tank_id, 200 + tank_id, 300 + tank_id, 1700000000, 1700000100),
                )
            for run_id, day, status in [(1, "2026-10-01", "complete"), (2, "2026-10-02", "complete"),
                                        (3, "2026-10-03", "failed")]:
                connection.execute("INSERT INTO collection_runs(run_id,snapshot_day,started_at,finished_at,status) VALUES(?,?,?,?,?)",
                                   (run_id, day, 1700000100, 1700000200 + run_id, status))
                connection.execute("INSERT INTO mastery_observations(run_id,tank_id,mastery_65,mastery_85,mastery_95) VALUES(?,?,?,?,?)",
                                   (run_id, 1, 100 + run_id, 200 + run_id, 300 + run_id))

    def get(self, path, **params):
        response = self.client.get(path, query_string=params)
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def post(self, path, body):
        response = self.client.post(path, json=body)
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_list_pagination_fields_and_prefix(self):
        for prefix in ("", "/api"):
            with self.subTest(prefix=prefix):
                payload = self.get(prefix + "/tankList", page=2, size=20)
                self.assertEqual(payload["errCode"], 0)
                self.assertEqual(payload["data"]["total"], 24)
                self.assertEqual([item["_id"] for item in payload["data"]["list"]], [4, 3, 2, 1])
                item = payload["data"]["list"][-1]
                self.assertEqual(item["premium"], 1)
                self.assertEqual(item["collector_vehicle"], 1)
                self.assertNotIn("id", item)
                self.assertNotIn("is_premium", item)
        for size in (20, 40, 100):
            self.assertEqual(len(self.get("/tankList", size=size)["data"]["list"]), min(size, 24))

    def test_filter_and_ant_design_sort(self):
        payload = self.get("/tankList", nation="china", type="heavyTank", tier=8, premium=1,
                           collector_vehicle=0, sort="mastery_95", order="ascend")
        self.assertEqual([item["_id"] for item in payload["data"]["list"]], list(range(3, 24, 2)))
        payload = self.get("/tankList", premium=0, sort="_id", order="descend")
        self.assertEqual(payload["data"]["list"][0]["_id"], 24)

    def test_invalid_list_parameters_keep_frontend_shape(self):
        for params in ({"page": 0}, {"size": 10}, {"tier": "bad"}, {"premium": 2}, {"sort": "name;DROP TABLE tanks"}):
            with self.subTest(params=params):
                payload = self.get("/tankList", **params)
                self.assertNotEqual(payload["errCode"], 0)
                self.assertTrue(payload["msg"])
                self.assertEqual(payload["data"], {"list": [], "total": 0})
        self.assertEqual(self.get("/tankList")["data"]["total"], 24)

    def test_official_player_vehicles_and_empty_results(self):
        rows = {"parameters": ["vehicle_cd", "markOfMastery", "marksOnGun"], "data": [[1, 4, 3], [2, 2, 1]]}
        for envelope in ({"data": rows}, {"data": {"data": rows}}):
            with self.subTest(envelope=envelope):
                response = Mock()
                response.json.return_value = envelope
                with patch.object(backend.requests, "post", return_value=response) as upstream:
                    payload = self.get("/api/tankList", player_id=123, sort="_id", order="ascend")
                    self.assertEqual(payload["data"]["total"], 2)
                    self.assertEqual(payload["data"]["list"][0]["pl"], {"mastery": 4, "moe": 3})
                    self.assertEqual(upstream.call_args.kwargs["json"]["spa_id"], 123)
        with patch.object(backend, "_player_vehicles", return_value={}):
            self.assertEqual(self.get("/tankList", player_id=123)["data"], {"list": [], "total": 0})
        with patch.object(backend, "_player_vehicles", side_effect=requests.Timeout()):
            self.assertNotEqual(self.get("/tankList", player_id=123)["errCode"], 0)

    def test_metadata_player_aliases_and_numeric_efficiency(self):
        for prefix in ("", "/api"):
            data = self.get(prefix + "/preData")["data"]
            self.assertEqual(data["nations"], ["china", "usa"])
            self.assertEqual(data["tiers"], list(range(1, 12)))
            self.assertEqual(len(data["types"]), 5)
            self.assertIsNone(data["player"])
            self.assertTrue(data["lastUpdate"].endswith("Z"))
            self.assertNotIn("last_updated", data)
        response = {"battles_count": 12345, "wins_ratio": 55.2, "global_rating": 9999,
                    "efficiency": "1,234", "efficiency_delta": "+12.5"}
        with patch.object(backend, "_player_summary", return_value=response) as summary:
            data = self.get("/preData", pid=123, pn="Player name")["data"]
            summary.assert_called_once_with(123, "Player name")
            self.assertEqual(data["player"], {"battTotal": 12345, "winRate": 55.2, "wgr": 9999,
                                              "eff": 1234, "effDelta": 12.5})
        with patch.object(backend, "_player_summary", side_effect=requests.Timeout()):
            self.assertIsNone(self.get("/preData", pid=123, pn="Player")["data"]["player"])

    def test_metadata_without_completed_history(self):
        with self.app.app_context():
            get_db().execute("DELETE FROM mastery_observations")
            get_db().execute("DELETE FROM collection_runs")
        self.assertIsNotNone(self.get("/preData")["data"]["lastUpdate"])
        with self.app.app_context():
            get_db().execute("DELETE FROM tanks")
        self.assertIsNone(self.get("/preData")["data"]["lastUpdate"])

    def test_history_order_and_failed_run_exclusion(self):
        for prefix in ("", "/api"):
            payload = self.get(prefix + "/history", id=1)
            self.assertEqual(payload["errCode"], 0)
            self.assertEqual([item["date"] for item in payload["data"]["list"]], ["2026-10-01", "2026-10-02"])
            self.assertEqual(payload["data"]["list"][1]["mastery_95"], 302)
        self.assertEqual(self.get("/history", id=999)["data"], {"list": []})
        for params in ({}, {"id": "bad"}, {"id": -1}):
            self.assertNotEqual(self.get("/history", **params)["errCode"], 0)

    def test_player_search_legacy_codes_and_prefix(self):
        account = {"account_id": 123, "account_name": "Player", "clan_tag": "ABC"}
        response = Mock()
        response.json.return_value = {"response": [account]}
        with patch.object(backend.requests, "get", return_value=response):
            for prefix in ("", "/api"):
                self.assertEqual(self.post(prefix + "/bindUser", {"nickname": "Player"}), {"errCode": 0, "data": [account]})
            response.json.return_value = {"response": []}
            self.assertEqual(self.post("/bindUser", {"nickname": "Player"})["errCode"], 20002)
        for body in ({"nickname": "abc"}, {}, [], {"nickname": 123}):
            self.assertEqual(self.post("/bindUser", body)["errCode"], 20001)
        with patch.object(backend.requests, "get", side_effect=requests.Timeout()):
            self.assertEqual(self.post("/bindUser", {"nickname": "Player"})["errCode"], 20003)

    def test_plugin_version_string_and_errors(self):
        response = Mock()
        response.json.return_value = {"paths": [{"path_type": "Dir", "name": "1.9.0"},
                                                {"path_type": "Dir", "name": "1.10.0"},
                                                {"path_type": "File", "name": "99.zip"}]}
        with patch.object(backend.requests, "get", return_value=response):
            for prefix in ("", "/api"):
                self.assertEqual(self.get(prefix + "/modVersion"), {"errCode": 0, "data": "1.10.0"})
        with patch.object(backend.requests, "get", side_effect=requests.Timeout()):
            payload = self.get("/modVersion")
            self.assertNotEqual(payload["errCode"], 0)
            self.assertEqual(payload["data"], "未知")

    def test_v1_routes_and_response_contracts_preserved(self):
        routes = {rule.rule for rule in self.app.url_map.iter_rules()}
        expected = {"/api/v1/health", "/api/v1/meta", "/api/v1/tanks", "/api/v1/tanks/<int:tank_id>/history",
                    "/api/v1/today-changes", "/api/v1/players/search", "/api/v1/players/<int:player_id>/summary",
                    "/api/v1/collections/run", "/api/v1/plugin/version"}
        self.assertTrue(expected.issubset(routes))
        self.assertEqual(self.get("/api/v1/health"), {"status": "ok"})
        payload = self.get("/api/v1/tanks")
        self.assertEqual(payload["pagination"]["total"], 24)
        self.assertIn("id", payload["items"][0])
        self.assertIsInstance(payload["items"][0]["is_premium"], bool)
        self.assertNotIn("errCode", payload)
        self.assertIn("last_updated", self.get("/api/v1/meta")["data"])
        self.assertEqual(len(self.get("/api/v1/tanks/1/history")["items"]), 2)
        self.assertEqual(self.get("/api/v1/today-changes", date="2026-10-02")["items"][0]["delta"], 1)
        response = self.client.get("/api/v1/tanks", query_string={"size": 10, "page_size": 10})
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())
        for path in ("/upload", "/download", "/commentList", "/addComment"):
            self.assertNotIn(path, routes)


if __name__ == "__main__":
    unittest.main()
