import io
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from ai_analysis import AiAnalysisError, AiResponseError, call_deepseek


class DeepSeekTransportTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-provider-only"}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def messages(self, stage):
        return [{"role": "system", "content": "Return JSON only."},
                {"role": "user", "content": json.dumps({"stage": stage})}]

    def response(self, content='{"ok":true}', finish_reason="stop"):
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": content},
                                                    "finish_reason": finish_reason}]}).encode())

    def test_selection_budget_reserves_space_for_thinking_and_complete_json(self):
        with patch("ai_analysis.urlopen", return_value=self.response()) as request:
            self.assertEqual(call_deepseek(self.messages("number_selection")), {"ok": True})
        args, kwargs = request.call_args
        payload = json.loads(args[0].data)
        self.assertEqual(payload["thinking"], {"type": "enabled"})
        self.assertEqual(payload["reasoning_effort"], "low")
        self.assertEqual(payload["max_tokens"], 16000)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(kwargs["timeout"], 180)
        self.assertEqual(args[0].get_header("Authorization"), "Bearer test-provider-only")

    def test_analysis_keeps_non_thinking_json_defaults(self):
        with patch("ai_analysis.urlopen", return_value=self.response()) as request:
            call_deepseek(self.messages("analysis_profile"))
        payload = json.loads(request.call_args.args[0].data)
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertNotIn("reasoning_effort", payload)
        self.assertEqual(payload["max_tokens"], 4000)
        self.assertEqual(request.call_args.kwargs["timeout"], 90)

    def test_longer_explicit_timeouts_remain_supported(self):
        with patch("ai_analysis.urlopen", return_value=self.response()) as request:
            call_deepseek(self.messages("number_selection"), timeout=240)
        self.assertEqual(request.call_args.kwargs["timeout"], 240)

    def test_timeouts_are_actionable_and_not_misreported_as_wrong_keys(self):
        for error in [TimeoutError("private internal detail"), URLError(TimeoutError("private detail"))]:
            with self.subTest(error=type(error).__name__), patch("ai_analysis.urlopen", side_effect=error):
                with self.assertRaisesRegex(AiAnalysisError, "响应超时.*无需重新输入密钥") as raised:
                    call_deepseek(self.messages("number_selection"))
                self.assertNotIn("private", str(raised.exception))

    def test_network_and_invalid_envelope_errors_are_separate(self):
        with patch("ai_analysis.urlopen", side_effect=URLError("private address")):
            with self.assertRaisesRegex(AiAnalysisError, "检查服务端网络") as raised:
                call_deepseek(self.messages("analysis_profile"))
            self.assertNotIn("private", str(raised.exception))
        for raw in [b"<html>gateway error</html>", b"\xff"]:
            with self.subTest(raw=raw), patch("ai_analysis.urlopen", return_value=io.BytesIO(raw)):
                with self.assertRaisesRegex(AiAnalysisError, "不是有效 JSON"):
                    call_deepseek(self.messages("analysis_profile"))

    def test_http_error_status_is_preserved_without_provider_body_or_key(self):
        error = HTTPError("https://api.deepseek.com/chat/completions", 401,
                          "test-provider-only", {}, io.BytesIO(b"private response"))
        with patch("ai_analysis.urlopen", side_effect=error):
            with self.assertRaisesRegex(AiAnalysisError, "HTTP 401") as raised:
                call_deepseek(self.messages("analysis_profile"))
        self.assertTrue(error.closed)
        self.assertNotIn("test-provider-only", str(raised.exception))
        self.assertNotIn("private", str(raised.exception))

    def test_truncated_selection_still_fails_instead_of_silently_using_partial_numbers(self):
        with patch("ai_analysis.urlopen", return_value=self.response('{"red":[1,2', "length")):
            with self.assertRaisesRegex(AiResponseError, "输出被截断"):
                call_deepseek(self.messages("number_selection"))

    def test_missing_provider_key_does_not_make_a_request(self):
        os.environ.pop("DEEPSEEK_API_KEY")
        with patch("ai_analysis.urlopen") as request:
            with self.assertRaisesRegex(AiAnalysisError, "未配置 DEEPSEEK_API_KEY"):
                call_deepseek(self.messages("analysis_profile"))
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
