"""Public AI and private purchase boundaries; all state is isolated and AI is mocked."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import purchase_api as api


class PurchaseSessionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for name, filename in [("PURCHASES_PATH", "purchases.json"), ("RESULTS_PATH", "results.json"),
                               ("HISTORY_PATH", "history.json"), ("AI_DATABASE_PATH", "private.sqlite3")]:
            patcher = patch.object(api, name, root / filename)
            patcher.start()
            self.addCleanup(patcher.stop)
        api.HISTORY_PATH.write_text("[]")
        api.PURCHASES_PATH.write_text('[{"id":"private-record"}]')
        api.RESULTS_PATH.write_text('[]')
        self.env = patch.dict(os.environ, {"SSQ_LOCAL_AUTO_AUTH": "0", "SSQ_ADMIN_TOKEN": "test-purchase-key",
                                          "DEEPSEEK_API_KEY": "test-ai-key", "DEEPSEEK_MIN_INTERVAL": "0",
                                          "DEEPSEEK_DAILY_LIMIT": "50"})
        self.env.start()
        self.addCleanup(self.env.stop)
        api.LOGIN_FAILURE_TIMES.clear()
        api.AI_REQUEST_TIMES.clear()
        api.AI_JOBS.clear()
        self.server = api.ThreadingHTTPServer(("127.0.0.1", 0), api.ApiHandler)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=2)
        # Never leave a mocked worker running into another fixture's database.
        acquired = api.AI_REQUEST_LOCK.acquire(timeout=3)
        if acquired:
            api.AI_REQUEST_LOCK.release()
        self.assertTrue(acquired)
        api.LOGIN_FAILURE_TIMES.clear()
        api.AI_REQUEST_TIMES.clear()
        api.AI_JOBS.clear()

    def request(self, path="/api/session", *, method="GET", payload=None, cookie="", headers=None):
        request_headers = {"Host": "ssq.example", "Origin": "https://ssq.example",
                           "Sec-Fetch-Site": "same-origin", "Content-Type": "application/json", "X-SSQ-Local": "1"}
        if cookie:
            request_headers["Cookie"] = cookie
        request_headers.update(headers or {})
        req = Request(self.base + path, method=method, headers=request_headers,
                      data=None if payload is None else json.dumps(payload).encode())
        try:
            response = urlopen(req, timeout=3)
        except HTTPError as exc:
            response = exc
        with response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}, response.headers

    def login(self):
        code, body, headers = self.request(method="POST", payload={"token": "test-purchase-key"})
        self.assertEqual(code, 200)
        self.assertTrue(body["purchase_authorized"])
        return headers["Set-Cookie"].split(";", 1)[0]

    def test_public_status_only_discloses_configuration_booleans(self):
        code, body, headers = self.request()
        self.assertEqual(code, 200)
        self.assertFalse(body["purchase_authorized"])
        self.assertEqual(body["mode"], "locked")
        self.assertEqual(body["configured_key_count"], 2)
        self.assertTrue(body["independent_keys"])
        for secret in ("test-purchase-key", "test-ai-key", "private-record"):
            self.assertNotIn(secret, json.dumps(body))
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

    def test_all_purchase_operations_and_ai_deletion_remain_private(self):
        with patch.object(api.ApiHandler, "save_purchase") as save, \
             patch.object(api.ApiHandler, "delete_purchase") as delete, \
             patch.object(api, "run_check") as check:
            for path, method in [("/api/purchases", "GET"), ("/api/state", "GET"), ("/api/check-results", "GET"),
                                 ("/api/purchases", "POST"), ("/api/purchases/private-record", "DELETE"),
                                 ("/api/check-now", "POST"), ("/api/ai/recommendations/report", "DELETE")]:
                code, body, _ = self.request(path, method=method, payload={} if method == "POST" else None)
                self.assertEqual(code, 401, (path, method))
                self.assertNotIn("private-record", json.dumps(body))
            for handler in (save, delete, check):
                handler.assert_not_called()

    def test_anonymous_ai_generation_and_report_reads_never_require_purchase_key(self):
        # A missing purchase key is independent from public AI, including the compatibility API.
        with patch.dict(os.environ, {"SSQ_ADMIN_TOKEN": ""}), \
             patch.object(api, "generate_ai_recommendation", return_value={"recommendation": {"summary": "mock"}}) as model:
            self.assertEqual(self.request("/api/ai/status")[0], 200)
            self.assertEqual(self.request("/api/ai/recommendations")[0], 200)
            code, task, _ = self.request("/api/ai/tasks", method="POST", payload={"client_request_id": "anon-client-request-000123"})
            self.assertEqual(code, 202)
            for _ in range(100):
                code, status, _ = self.request(task["status_url"])
                self.assertEqual(code, 200)
                if status["status"] != "running":
                    break
                time.sleep(.01)
            self.assertEqual(status["status"], "succeeded")
            report = self.request("/api/ai/recommendations")[1]["items"][0]
            self.assertEqual(self.request("/api/ai/recommendations/" + report["id"])[0], 200)
            self.assertIsNotNone(self.request("/api/ai/recommendations/latest")[1]["item"])
            self.assertEqual(self.request("/api/ai/recommendation", method="POST", payload={})[0], 200)
            self.assertEqual(model.call_count, 2)
            with patch.dict(os.environ, {"DEEPSEEK_DAILY_LIMIT": "1"}):
                self.assertEqual(self.request("/api/ai/tasks", method="POST", payload={})[0], 429)
            self.assertEqual(self.request("/api/state")[0], 401)

    def test_unlock_uses_secure_cookie_and_stores_only_hashes(self):
        self.assertEqual(self.request(method="POST", payload={"token": "test-ai-key"})[0], 401)
        code, body, headers = self.request(method="POST", payload={"token": "test-purchase-key"},
                                          headers={"X-Forwarded-Proto": "http"})
        self.assertEqual(code, 200)
        cookie = headers["Set-Cookie"]
        for flag in ("__Host-ssq_purchase=", "HttpOnly", "Secure", "SameSite=Strict", "Path=/", "Max-Age=2592000"):
            self.assertIn(flag, cookie)
        self.assertNotIn("Domain=", cookie)
        value = cookie.split(";", 1)[0]
        self.assertEqual(self.request(cookie=value)[1]["mode"], "session")
        self.assertEqual(self.request("/api/state", cookie=value)[1]["purchases"][0]["id"], "private-record")
        self.assertEqual(self.request("/api/state", cookie=value + "x")[0], 401)
        with sqlite3.connect(api.AI_DATABASE_PATH) as db:
            row = db.execute("SELECT * FROM purchase_sessions").fetchone()
        self.assertEqual(len(row[0]), 64)
        self.assertEqual(len(row[1]), 64)
        self.assertNotIn(value.split("=", 1)[1], str(row))
        self.assertNotIn("test-purchase-key", str(row))
        self.assertNotIn("test-purchase-key", json.dumps(body))

    def test_expiry_rotation_and_logout_revoke_authorization(self):
        cookie = self.login()
        with patch.object(api.time, "time", return_value=time.time() + api.PURCHASE_SESSION_TTL + 1):
            self.assertEqual(self.request("/api/state", cookie=cookie)[0], 401)
        with patch.dict(os.environ, {"SSQ_ADMIN_TOKEN": "rotated-admin"}):
            self.assertEqual(self.request("/api/state", cookie=cookie)[0], 401)
        code, _, headers = self.request(method="DELETE", cookie=cookie)
        self.assertEqual(code, 200)
        self.assertIn("Max-Age=0", headers["Set-Cookie"])
        self.assertEqual(self.request("/api/state", cookie=cookie)[0], 401)
        self.assertEqual(self.request("/api/ai/status", cookie=cookie)[0], 200)

    def test_session_survives_server_restart_and_relogin_replaces_only_current_session(self):
        first = self.login()
        other = self.login()
        self.server.shutdown()
        self.worker.join(timeout=2)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.assertEqual(self.request("/api/state", cookie=first)[0], 200)
        code, _, headers = self.request(method="POST", cookie=first, payload={"token": "test-purchase-key"})
        self.assertEqual(code, 200)
        replacement = headers["Set-Cookie"].split(";", 1)[0]
        self.assertEqual(self.request("/api/state", cookie=first)[0], 401)
        self.assertEqual(self.request("/api/state", cookie=replacement)[0], 200)
        self.assertEqual(self.request("/api/state", cookie=other)[0], 200)

    def test_cross_origin_and_same_site_writes_are_rejected_even_with_cookie(self):
        cookie = self.login()
        for headers in ({"Origin": "https://attacker.example"}, {"Origin": "null"},
                        {"Sec-Fetch-Site": "same-site"}, {"Sec-Fetch-Site": "cross-site"}):
            for path, method in [("/api/session", "POST"), ("/api/session", "DELETE"),
                                 ("/api/ai/tasks", "POST"), ("/api/purchases", "POST"), ("/api/check-now", "POST")]:
                code, _, response_headers = self.request(path, method=method, payload={}, cookie=cookie, headers=headers)
                self.assertEqual(code, 403)
                self.assertIsNone(response_headers.get("Access-Control-Allow-Origin"))
            self.assertEqual(self.request("/api/state", cookie=cookie, headers=headers)[0], 401)
        self.assertEqual(self.request(method="POST", payload={"token": "test-purchase-key"},
                                      headers={"Origin": "http://ssq.example"})[0], 400)
        self.assertEqual(self.request("/api/ai/tasks", method="POST", payload={},
                                      headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(len(api.AI_REQUEST_TIMES), 0)

    def test_login_validation_and_brute_force_limit(self):
        for payload in ([], None, {"token": []}, {"token": "x" * 4097}):
            self.assertEqual(self.request(method="POST", payload=payload)[0], 400)
        for _ in range(api.LOGIN_MAX_FAILURES):
            self.assertEqual(self.request(method="POST", payload={"token": "wrong"})[0], 401)
        self.assertEqual(self.request(method="POST", payload={"token": "test-purchase-key"})[0], 429)
        self.assertEqual(self.request("/api/ai/status")[0], 200)
        with patch.object(api.time, "time", return_value=time.time() + api.LOGIN_WINDOW_SECONDS + 1):
            self.login()


if __name__ == "__main__":
    unittest.main()
