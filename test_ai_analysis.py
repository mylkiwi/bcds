import json
import unittest

from ai_analysis import (
    AiAnalysisError,
    AiResponseError,
    build_analysis_snapshot,
    build_messages,
    build_selection_messages,
    generate_ai_recommendation,
    validate_analysis_profile,
    validate_recommendation,
)


def sample_rows(count=70):
    rows = []
    for index in range(count):
        start = index % 28 + 1
        red = sorted({((start + offset * 5 - 1) % 33) + 1 for offset in range(6)})
        while len(red) < 6:
            red.append(max(red) + 1)
        rows.append(
            {
                "issue": str(2026001 + index),
                "date": "2026-01-01",
                "red": sorted(red[:6]),
                "blue": index % 16 + 1,
            }
        )
    return rows


def broad_profile(red_count=7):
    return {
        "odd_range": [0, red_count],
        "small_range": [0, red_count],
        "zone_minimums": [0, 0, 0],
        "sum_range": [sum(range(1, red_count + 1)), sum(range(34 - red_count, 34))],
        "max_consecutive_run": red_count,
    }


def valid_analysis_response(profile=None):
    evidence_ids = [
        "statistics.scope_issues",
        "shape.common_odd",
        "shape.common_small",
        "shape.common_zone",
        "shape.sum_middle_band",
        "trend.consecutive_draw_rate",
        "backtest.red_hot_top8.30",
    ]
    return {
        "summary": "基于历史统计、走势与回测的研究摘要",
        "selection_rules": ["规则来自本次历史报告", "形态只作动态取舍"],
        "dynamic_profile": profile or broad_profile(),
        "profile_evidence": [
            {"id": evidence_id, "reason": "引用服务端报告作为本期口径依据"}
            for evidence_id in evidence_ids
        ],
        "backtest_conclusion": "样本结果接近随机期望",
        "risk_note": "每个合法组合概率相同，不保证中奖",
    }


def valid_selection_response(red=None, blue=None):
    red = red or [3, 8, 14, 16, 20, 27, 33]
    blue = blue or [5, 13]
    return {
        "structure_rationale": "最终号码满足第一阶段冻结的形态口径",
        "red": red,
        "blue": blue,
        "red_reasons": [{"number": number, "reason": "历史覆盖取舍"} for number in red],
        "blue_reasons": [{"number": number, "reason": "历史覆盖取舍"} for number in blue],
    }


def message_stage(messages):
    return json.loads(messages[1]["content"])["stage"]


class AiAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.rows = sample_rows()
        self.snapshot = build_analysis_snapshot(self.rows, 30)

    def freeze(self, response=None, red_count=7):
        return validate_analysis_profile(
            response or valid_analysis_response(broad_profile(red_count)),
            self.snapshot,
            red_count=red_count,
        )

    def test_stage1_prompt_has_no_candidate_output(self):
        messages = build_messages(
            self.snapshot,
            red_count=7,
            blue_count=2,
            shape_filter=True,
            avoid_popular=True,
        )
        payload = json.loads(messages[1]["content"])
        schema = payload["constraints"]["required_output_schema"]

        self.assertEqual(payload["stage"], "analysis_profile")
        self.assertNotIn("red", schema)
        self.assertNotIn("blue", schema)
        self.assertNotIn("structure_rationale", schema)
        self.assertNotIn("required_output_example", payload["constraints"])
        self.assertIn("严禁选号", messages[0]["content"])
        self.assertTrue(payload["evidence_catalog"])

    def test_stage2_receives_frozen_profile_and_cannot_output_it(self):
        frozen = self.freeze()
        messages = build_selection_messages(
            self.snapshot,
            frozen,
            red_count=7,
            blue_count=2,
        )
        payload = json.loads(messages[1]["content"])
        schema = payload["constraints"]["required_output_schema"]

        self.assertEqual(payload["stage"], "number_selection")
        self.assertEqual(payload["frozen_analysis"]["dynamic_profile"], frozen["dynamic_profile"])
        self.assertEqual(payload["server_validation_checklist"]["odd_count_range"], [0, 7])
        self.assertNotIn("dynamic_profile", schema)
        self.assertEqual(set(schema), {"structure_rationale", "red", "blue", "red_reasons", "blue_reasons"})

    def test_snapshot_uses_requested_scope_and_rolling_history(self):
        snapshot = build_analysis_snapshot(self.rows, 20)
        self.assertEqual(snapshot["data"]["scope_issues"], 20)
        self.assertEqual(len(snapshot["red_statistics"]), 33)
        self.assertEqual(len(snapshot["blue_statistics"]), 16)
        self.assertEqual(len(snapshot["trend"]["draws"]), 20)
        self.assertEqual(snapshot["shape_history"]["selected_scope"]["window"], 20)
        self.assertTrue(any(item["samples"] == 40 for item in snapshot["backtests"] if item["window"] == 30))

    def test_valid_selection_is_enriched_with_frozen_analysis_and_real_statistics(self):
        frozen = self.freeze()
        result = validate_recommendation(
            valid_selection_response(),
            self.snapshot,
            frozen,
            red_count=7,
            blue_count=2,
        )
        self.assertEqual(result["red"], [3, 8, 14, 16, 20, 27, 33])
        self.assertEqual(result["dynamic_profile"], frozen["dynamic_profile"])
        self.assertEqual(result["profile_evidence"], frozen["profile_evidence"])
        self.assertIn("frequency", result["red_reasons"][0])
        self.assertEqual(result["structure"]["zones"], "2:3:2")
        self.assertIn("model_structure_rationale", result)

    def test_generate_calls_analysis_before_selection(self):
        calls = []

        def requester(messages):
            stage = message_stage(messages)
            calls.append(stage)
            if stage == "analysis_profile":
                return valid_analysis_response()
            self.assertEqual(stage, "number_selection")
            payload = json.loads(messages[1]["content"])
            self.assertEqual(payload["frozen_analysis"]["dynamic_profile"], broad_profile())
            return valid_selection_response()

        result = generate_ai_recommendation(self.rows, requester=requester)
        self.assertEqual(calls, ["analysis_profile", "number_selection"])
        self.assertTrue(result["pipeline"]["analysis_frozen_before_selection"])
        self.assertEqual(result["recommendation"]["blue"], [5, 13])

    def test_extreme_legal_shape_is_not_blocked_by_fixed_server_filter(self):
        responses = iter(
            [
                valid_analysis_response(),
                valid_selection_response(red=[1, 3, 5, 7, 9, 11, 13]),
            ]
        )
        result = generate_ai_recommendation(self.rows, requester=lambda _messages: next(responses))
        self.assertEqual(result["recommendation"]["structure"]["odd_even"], "7:0")
        self.assertIn("7红池实际奇偶7:0", result["recommendation"]["structure_rationale"])

    def test_stage1_failure_never_enters_stage2(self):
        calls = []
        invalid = valid_analysis_response()
        invalid["selection_rules"] = []

        def requester(messages):
            calls.append(message_stage(messages))
            return invalid

        with self.assertRaisesRegex(AiAnalysisError, "动态规则"):
            generate_ai_recommendation(self.rows, requester=requester)
        self.assertEqual(calls, ["analysis_profile", "analysis_profile"])

    def test_stage2_retries_twice_without_rerunning_stage1(self):
        constrained = {
            "odd_range": [2, 4],
            "small_range": [2, 5],
            "zone_minimums": [1, 1, 1],
            "sum_range": [70, 150],
            "max_consecutive_run": 2,
        }
        responses = iter(
            [
                valid_analysis_response(constrained),
                valid_selection_response(red=[2, 4, 6, 8, 10, 12, 14]),
                valid_selection_response(red=[2, 4, 6, 8, 10, 12, 16]),
                valid_selection_response(),
            ]
        )
        calls = []

        def requester(messages):
            calls.append(message_stage(messages))
            return next(responses)

        result = generate_ai_recommendation(self.rows, requester=requester)
        self.assertEqual(
            calls,
            ["analysis_profile", "number_selection", "number_selection", "number_selection"],
        )
        self.assertEqual(result["recommendation"]["dynamic_profile"], constrained)

    def test_stage2_cannot_return_or_override_dynamic_profile(self):
        frozen = self.freeze()
        selection = valid_selection_response()
        selection["dynamic_profile"] = broad_profile()
        with self.assertRaisesRegex(AiAnalysisError, "已冻结"):
            validate_recommendation(
                selection,
                self.snapshot,
                frozen,
                red_count=7,
                blue_count=2,
            )

    def test_numbers_must_match_frozen_profile(self):
        constrained = {
            "odd_range": [2, 4],
            "small_range": [2, 5],
            "zone_minimums": [1, 1, 1],
            "sum_range": [70, 150],
            "max_consecutive_run": 2,
        }
        frozen = self.freeze(valid_analysis_response(constrained))
        with self.assertRaisesRegex(AiAnalysisError, "本期动态口径"):
            validate_recommendation(
                valid_selection_response(red=[2, 4, 6, 8, 10, 12, 14]),
                self.snapshot,
                frozen,
                red_count=7,
                blue_count=2,
            )

    def test_invalid_and_unsatisfiable_profiles_are_rejected(self):
        invalid = valid_analysis_response()
        invalid["dynamic_profile"]["odd_range"] = [5, 2]
        impossible = valid_analysis_response()
        impossible["dynamic_profile"]["small_range"] = [0, 0]
        impossible["dynamic_profile"]["zone_minimums"] = [1, 0, 0]

        with self.assertRaisesRegex(AiAnalysisError, "范围无效"):
            validate_analysis_profile(invalid, self.snapshot, red_count=7)
        with self.assertRaisesRegex(AiAnalysisError, "无可满足"):
            validate_analysis_profile(impossible, self.snapshot, red_count=7)

    def test_stage1_candidate_fields_and_unverifiable_evidence_are_rejected(self):
        candidate = valid_analysis_response()
        candidate["red"] = [1, 2, 3, 4, 5, 6, 7]
        unverified = valid_analysis_response()
        unverified["profile_evidence"][0]["id"] = "invented.metric"

        with self.assertRaisesRegex(AiAnalysisError, "不得返回候选号码"):
            validate_analysis_profile(candidate, self.snapshot, red_count=7)
        with self.assertRaisesRegex(AiAnalysisError, "无法与服务端报告核对"):
            validate_analysis_profile(unverified, self.snapshot, red_count=7)

    def test_request_error_in_stage1_is_not_retried_as_validation_error(self):
        calls = 0

        def requester(_messages):
            nonlocal calls
            calls += 1
            raise AiAnalysisError("DeepSeek API 返回 HTTP 401")

        with self.assertRaisesRegex(AiAnalysisError, "HTTP 401"):
            generate_ai_recommendation(self.rows, requester=requester)
        self.assertEqual(calls, 1)

    def test_invalid_json_retries_only_current_stage(self):
        calls = []

        def requester(messages):
            stage = message_stage(messages)
            calls.append(stage)
            if calls == ["analysis_profile"]:
                raise AiResponseError("DeepSeek API 未返回有效 JSON 内容")
            if stage == "analysis_profile":
                return valid_analysis_response()
            return valid_selection_response()

        result = generate_ai_recommendation(self.rows, requester=requester)
        self.assertEqual(result["recommendation"]["red"], [3, 8, 14, 16, 20, 27, 33])
        self.assertEqual(calls, ["analysis_profile", "analysis_profile", "number_selection"])

    def test_boolean_and_decimal_numbers_are_rejected(self):
        frozen = self.freeze()
        for invalid in (True, 1.9):
            selection = valid_selection_response()
            selection["red"] = [invalid, 3, 8, 14, 20, 27, 33]
            with self.subTest(invalid=invalid), self.assertRaises(AiAnalysisError):
                validate_recommendation(
                    selection,
                    self.snapshot,
                    frozen,
                    red_count=7,
                    blue_count=2,
                )


if __name__ == "__main__":
    unittest.main()
