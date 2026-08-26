import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import purchase_api
from ai_analysis import AiAnalysisError


class AiTaskApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_history_path = purchase_api.HISTORY_PATH
        purchase_api.HISTORY_PATH = Path(self.temp_dir.name) / "history.json"
        purchase_api.HISTORY_PATH.write_text("[]\n", encoding="utf-8")
        self.env_patch = patch.dict(
            os.environ,
            {
                "SSQ_ADMIN_TOKEN": "test-admin-token",
                "DEEPSEEK_API_KEY": "test-deepseek-key",
                "DEEPSEEK_MIN_INTERVAL": "0",
                "DEEPSEEK_DAILY_LIMIT": "100",
            },
        )
        self.env_patch.start()
        with purchase_api.AI_USAGE_LOCK:
            purchase_api.AI_REQUEST_TIMES.clear()
        with purchase_api.AI_JOB_LOCK:
            purchase_api.AI_JOBS.clear()
        self.server = purchase_api.ThreadingHTTPServer(("127.0.0.1", 0), purchase_api.ApiHandler)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=2)
        deadline = time.time() + 2
        while time.time() < deadline:
            if purchase_api.AI_REQUEST_LOCK.acquire(blocking=False):
                purchase_api.AI_REQUEST_LOCK.release()
                break
            time.sleep(0.01)
        with purchase_api.AI_JOB_LOCK:
            purchase_api.AI_JOBS.clear()
        with purchase_api.AI_USAGE_LOCK:
            purchase_api.AI_REQUEST_TIMES.clear()
        purchase_api.HISTORY_PATH = self.original_history_path
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def request(self, path, *, method="GET", payload=None, authorized=True):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if authorized:
            headers["Authorization"] = "Bearer test-admin-token"
        request = Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read().decode("utf-8"))

    def wait_for_status(self, status_url, expected, timeout=3):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            code, last = self.request(status_url)
            self.assertEqual(code, 200)
            if last["status"] == expected:
                return last
            time.sleep(0.02)
        self.fail(f"task did not reach {expected}: {last}")

    def test_async_task_returns_quickly_and_succeeds(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []
        expected = {"recommendation": {"red": [1, 2, 3, 4, 5, 6, 7], "blue": [8, 9]}}

        def fake_generator(rows, **options):
            calls.append((rows, options))
            entered.set()
            release.wait(timeout=2)
            return expected

        with patch.object(purchase_api, "generate_ai_recommendation", fake_generator):
            started = time.time()
            code, task = self.request(
                "/api/ai/tasks",
                method="POST",
                payload={
                    "scope": "100",
                    "red_count": 7,
                    "blue_count": 2,
                    "client_request_id": "client-request-0001",
                },
            )
            self.assertEqual(code, 202)
            self.assertLess(time.time() - started, 0.5)
            self.assertTrue(entered.wait(timeout=1))
            code, running = self.request(task["status_url"])
            self.assertEqual((code, running["status"]), (200, "running"))
            release.set()
            succeeded = self.wait_for_status(task["status_url"], "succeeded")

        self.assertEqual(succeeded["result"], expected)
        self.assertEqual(calls[0][1]["red_count"], 7)
        self.assertEqual(len(purchase_api.AI_REQUEST_TIMES), 1)

    def test_failed_task_releases_execution_slot(self):
        with patch.object(
            purchase_api,
            "generate_ai_recommendation",
            side_effect=AiAnalysisError("model output invalid"),
        ):
            code, task = self.request(
                "/api/ai/tasks",
                method="POST",
                payload={"client_request_id": "client-request-fail1"},
            )
            self.assertEqual(code, 202)
            failed = self.wait_for_status(task["status_url"], "failed")
        self.assertEqual(failed["error"]["code"], "ai_analysis_failed")
        self.assertEqual(failed["error"]["message"], "model output invalid")

        with patch.object(purchase_api, "generate_ai_recommendation", return_value={"ok": True}):
            code, second = self.request(
                "/api/ai/tasks",
                method="POST",
                payload={"client_request_id": "client-request-pass2"},
            )
            self.assertEqual(code, 202)
            self.assertEqual(self.wait_for_status(second["status_url"], "succeeded")["result"], {"ok": True})

    def test_active_task_is_idempotent_and_blocks_other_ai_requests(self):
        entered = threading.Event()
        release = threading.Event()

        def blocking_generator(_rows, **_options):
            entered.set()
            release.wait(timeout=2)
            return {"ok": True}

        payload = {"client_request_id": "client-request-same1"}
        with patch.object(purchase_api, "generate_ai_recommendation", blocking_generator):
            code, first = self.request("/api/ai/tasks", method="POST", payload=payload)
            self.assertEqual(code, 202)
            self.assertTrue(entered.wait(timeout=1))

            code, duplicate = self.request("/api/ai/tasks", method="POST", payload=payload)
            self.assertEqual(code, 202)
            self.assertEqual(duplicate["task_id"], first["task_id"])
            self.assertEqual(len(purchase_api.AI_REQUEST_TIMES), 1)

            code, busy = self.request(
                "/api/ai/tasks",
                method="POST",
                payload={"client_request_id": "client-request-other2"},
            )
            self.assertEqual(code, 429)
            self.assertIn("正在进行", busy["error"])
            code, _ = self.request("/api/ai/recommendation", method="POST", payload={})
            self.assertEqual(code, 429)
            release.set()
            self.wait_for_status(first["status_url"], "succeeded")

    def test_invalid_payload_and_unauthorized_requests_do_not_consume_quota(self):
        code, _ = self.request(
            "/api/ai/tasks",
            method="POST",
            payload={"red_count": "invalid", "client_request_id": "client-request-bad01"},
        )
        self.assertEqual(code, 400)
        code, _ = self.request("/api/ai/tasks", method="POST", payload={}, authorized=False)
        self.assertEqual(code, 401)
        self.assertEqual(purchase_api.AI_REQUEST_TIMES, [])

        with patch.object(purchase_api, "generate_ai_recommendation", return_value={"ok": True}):
            code, task = self.request(
                "/api/ai/tasks",
                method="POST",
                payload={"client_request_id": "client-request-good2"},
            )
            self.assertEqual(code, 202)
            code, _ = self.request(task["status_url"], authorized=False)
            self.assertEqual(code, 401)
            self.wait_for_status(task["status_url"], "succeeded")

    def test_synchronous_endpoint_remains_compatible(self):
        expected = {"pipeline": {"mode": "two_stage"}}
        with patch.object(purchase_api, "generate_ai_recommendation", return_value=expected):
            code, result = self.request("/api/ai/recommendation", method="POST", payload={})
        self.assertEqual((code, result), (200, expected))

    def test_cleanup_keeps_running_tasks_and_expires_terminal_tasks(self):
        now = time.time()
        with purchase_api.AI_JOB_LOCK:
            purchase_api.AI_JOBS.update(
                {
                    "running-task-id-00000001": {
                        "status": "running",
                        "created_at": "old",
                        "updated_at": "old",
                        "updated_epoch": now - 7200,
                    },
                    "finished-task-id-0000001": {
                        "status": "succeeded",
                        "created_at": "old",
                        "updated_at": "old",
                        "updated_epoch": now - 7200,
                        "result": {},
                    },
                }
            )
            purchase_api._cleanup_ai_jobs_locked(now)
            self.assertIn("running-task-id-00000001", purchase_api.AI_JOBS)
            self.assertNotIn("finished-task-id-0000001", purchase_api.AI_JOBS)


if __name__ == "__main__":
    unittest.main()
