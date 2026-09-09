import json
import os
import tempfile
import threading
import unittest
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import purchase_api
from run_local import configure_local_environment


class LocalAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.env = patch.dict(os.environ, {
            "SSQ_ADMIN_TOKEN": "test-independent-admin",
            "DEEPSEEK_API_KEY": "test-provider-key",
            "SSQ_LOCAL_AUTO_AUTH": "1",
            "DEEPSEEK_MIN_INTERVAL": "0",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        for name, filename in [("PURCHASES_PATH", "purchases.json"),
                               ("RESULTS_PATH", "results.json"),
                               ("HISTORY_PATH", "history.json"),
                               ("AI_DATABASE_PATH", "ssq.sqlite3")]:
            patcher = patch.object(purchase_api, name, root / filename)
            patcher.start()
            self.addCleanup(patcher.stop)
        purchase_api.HISTORY_PATH.write_text("[]")
        self.server = purchase_api.ThreadingHTTPServer(("127.0.0.1", 0), purchase_api.ApiHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path="/api/access", *, method="GET", headers=None, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        request_headers = {"Content-Type": "application/json", "X-SSQ-Local": "1",
                           "Origin": self.base, "Sec-Fetch-Site": "same-origin"}
        request_headers.update(headers or {})
        req = Request(self.base + path, headers=request_headers, data=data, method=method)
        try:
            response = urlopen(req, timeout=3)
        except HTTPError as exc:
            response = exc
        with response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}, response.headers

    def test_no_input_access_reports_two_separate_keys_without_values(self):
        code, body, headers = self.request()
        self.assertEqual(code, 200)
        self.assertEqual(body, {"mode": "local", "keys": {"ai": True, "purchase": True},
                                "configured_key_count": 2, "independent_keys": True})
        self.assertNotIn("test-independent-admin", json.dumps(body))
        self.assertNotIn("test-provider-key", json.dumps(body))
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

    def test_marker_is_required_and_wrong_origin_is_rejected(self):
        for headers in [{"X-SSQ-Local": ""}, {"Origin": "https://attacker.example"},
                        {"Origin": "null"}, {"Origin": "http://127.0.0.1:1234"},
                        {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"},
                        {"Host": "attacker.example"}, {"Host": "127.0.0.1:1234"},
                        {"X-Forwarded-Host": "ssq.example"}, {"X-Forwarded-For": "127.0.0.1"},
                        {"Forwarded": "for=127.0.0.1"}]:
            with self.subTest(headers=headers):
                self.assertEqual(self.request(headers=headers)[0], 401)

    def test_cross_origin_preflight_cannot_opt_in_to_local_access(self):
        code, _, headers = self.request(method="OPTIONS", headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Headers": "X-SSQ-Local,Content-Type",
            "Access-Control-Request-Method": "POST",
        })
        self.assertEqual(code, 204)
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))
        self.assertIsNone(headers.get("Access-Control-Allow-Headers"))

    def test_production_still_requires_management_credential(self):
        with patch.dict(os.environ, {"SSQ_LOCAL_AUTO_AUTH": "0"}):
            self.assertEqual(self.request()[0], 401)
            self.assertEqual(self.request(headers={"Authorization": "Bearer test-provider-key"})[0], 401)
            code, body, _ = self.request(headers={"Authorization": "Bearer test-independent-admin"})
            self.assertEqual(code, 200)
            self.assertEqual(body["mode"], "token")
            self.assertEqual(self.request(headers={"X-Admin-Token": "test-independent-admin"})[0], 200)
        with patch.dict(os.environ):
            os.environ.pop("SSQ_LOCAL_AUTO_AUTH", None)
            self.assertEqual(self.request()[0], 401)

    def test_public_listen_address_or_remote_peer_never_gets_automatic_access(self):
        handler = object.__new__(purchase_api.ApiHandler)
        handler.headers = Message()
        handler.headers["X-SSQ-Local"] = "1"
        handler.headers["Host"] = "127.0.0.1:8000"
        handler.client_address = ("127.0.0.1", 1234)
        handler.server = SimpleNamespace(server_address=("0.0.0.0", 8000), server_port=8000)
        self.assertFalse(handler.local_authorized())
        handler.server.server_address = ("127.0.0.1", 8000)
        handler.client_address = ("192.0.2.1", 1234)
        self.assertFalse(handler.local_authorized())
        handler.client_address = ("127.0.0.1", 1234)
        self.assertTrue(handler.local_authorized())

    def test_purchase_flow_without_key_entry_uses_only_temporary_data(self):
        payload = {"issue": "2026100", "type": "complex", "red": [1, 4, 9, 15, 22, 27, 33],
                   "blue": [3, 12], "note": "default test"}
        with patch.object(purchase_api, "push_purchase_bark", return_value={"sent": False}):
            code, body, _ = self.request("/api/purchases", method="POST", payload=payload)
        self.assertEqual(code, 200)
        item_id = body["item"]["id"]
        self.assertEqual(self.request("/api/state")[1]["purchases"][0]["id"], item_id)
        self.assertEqual(self.request(f"/api/purchases/{item_id}", method="DELETE")[0], 200)
        self.assertEqual(self.request("/api/state")[1]["purchases"], [])

    def test_mutations_from_other_sites_do_not_reach_handlers(self):
        with patch.object(purchase_api.ApiHandler, "save_purchase") as save, \
             patch.object(purchase_api.ApiHandler, "ai_recommendation") as ai, \
             patch.object(purchase_api.ApiHandler, "delete_purchase") as delete, \
             patch.object(purchase_api, "run_check") as check:
            for path, method in [("/api/purchases", "POST"), ("/api/ai/tasks", "POST"),
                                 ("/api/check-now", "POST"), ("/api/purchases/test", "DELETE")]:
                self.assertEqual(self.request(path, method=method, payload={},
                                              headers={"Origin": "https://attacker.example"})[0], 401)
            for action in [save, ai, delete, check]:
                action.assert_not_called()

    def test_missing_ai_key_is_reported_without_disabling_purchase_panel(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            code, body, _ = self.request()
            self.assertEqual(code, 200)
            self.assertEqual(body["keys"], {"ai": False, "purchase": True})
            self.assertEqual(body["configured_key_count"], 1)
            self.assertEqual(self.request("/api/state")[0], 200)
            self.assertEqual(self.request("/api/ai/tasks", method="POST", payload={})[0], 503)

    def test_secrets_and_private_files_are_not_static_resources(self):
        for path in ["/.env", "/run_local.py", "/data/purchases.json", "/data/ssq.sqlite3"]:
            self.assertEqual(self.request(path)[0], 404)


class LocalConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.env_path = self.root / ".env"
        patcher = patch.dict(os.environ, {}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_reused_key_is_split_without_changing_provider_or_other_settings(self):
        original = "# keep this\nDEEPSEEK_API_KEY=provider-value\nSSQ_ADMIN_TOKEN=provider-value\nBARK_SOUND=minuet\n"
        self.env_path.write_text(original)
        os.environ.update(SSQ_ADMIN_TOKEN="provider-value", DEEPSEEK_API_KEY="provider-value")
        configure_local_environment(self.root)
        admin = os.environ["SSQ_ADMIN_TOKEN"]
        self.assertNotEqual(admin, "provider-value")
        self.assertGreaterEqual(len(admin), 40)
        self.assertIn("DEEPSEEK_API_KEY=provider-value\n", self.env_path.read_text())
        self.assertIn("# keep this\n", self.env_path.read_text())
        self.assertIn("BARK_SOUND=minuet\n", self.env_path.read_text())
        self.assertIn(f"SSQ_ADMIN_TOKEN={admin}\n", self.env_path.read_text())
        self.assertEqual(self.env_path.stat().st_mode & 0o777, 0o600)
        configure_local_environment(self.root)
        self.assertEqual(os.environ["SSQ_ADMIN_TOKEN"], admin)
        self.assertEqual(list(self.root.glob(".env.*")), [])

    def test_existing_distinct_keys_are_preserved(self):
        original = "DEEPSEEK_API_KEY=provider\nSSQ_ADMIN_TOKEN=admin\n"
        self.env_path.write_text(original)
        os.environ.update(SSQ_ADMIN_TOKEN="admin", DEEPSEEK_API_KEY="provider")
        configure_local_environment(self.root)
        self.assertEqual(self.env_path.read_text(), original)
        self.assertEqual(os.environ["SSQ_ADMIN_TOKEN"], "admin")

    def test_missing_management_key_is_generated_and_local_defaults_are_ready(self):
        configure_local_environment(self.root)
        self.assertTrue(os.environ["SSQ_ADMIN_TOKEN"])
        self.assertEqual(os.environ["SSQ_LOCAL_AUTO_AUTH"], "1")
        self.assertEqual(os.environ["SSQ_API_HOST"], "127.0.0.1")
        self.assertEqual(os.environ["SSQ_API_PORT"], "8000")
        self.assertTrue(self.env_path.exists())

    def test_placeholder_management_key_is_generated(self):
        os.environ["SSQ_ADMIN_TOKEN"] = "replace-with-a-strong-admin-token"
        configure_local_environment(self.root)
        self.assertNotEqual(os.environ["SSQ_ADMIN_TOKEN"], "replace-with-a-strong-admin-token")

    def test_local_auto_mode_refuses_public_binding_before_altering_keys(self):
        os.environ["SSQ_API_HOST"] = "0.0.0.0"
        with self.assertRaisesRegex(ValueError, "本机地址"):
            configure_local_environment(self.root)
        self.assertFalse(self.env_path.exists())


if __name__ == "__main__":
    unittest.main()
