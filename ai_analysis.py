#!/usr/bin/env python3
"""Build deterministic SSQ research data and request an AI recommendation."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from itertools import combinations
import json
import math
import os
import re
from statistics import mean, median
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


RED_MAX = 33
BLUE_MAX = 16
RED_DRAW_COUNT = 6
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"


class AiAnalysisError(RuntimeError):
    """A safe, user-facing AI analysis error."""


class AiResponseError(AiAnalysisError):
    """The upstream request succeeded but the model response was unusable."""


def normalize_history(rows: list[dict]) -> list[dict]:
    normalized = []
    seen = set()
    for row in rows:
        issue = str(row.get("issue", "")).strip()
        red = sorted(int(value) for value in row.get("red", []))
        blue = int(row.get("blue", 0))
        if not re.fullmatch(r"20\d{5}", issue) or issue in seen:
            continue
        if len(red) != RED_DRAW_COUNT or len(set(red)) != RED_DRAW_COUNT:
            continue
        if any(value < 1 or value > RED_MAX for value in red) or not 1 <= blue <= BLUE_MAX:
            continue
        seen.add(issue)
        normalized.append({"issue": issue, "date": str(row.get("date", "")), "red": red, "blue": blue})
    return sorted(normalized, key=lambda row: int(row["issue"]))


def resolve_scope(scope, available: int) -> int:
    if str(scope).lower() == "all":
        return available
    try:
        value = int(scope)
    except (TypeError, ValueError):
        value = min(100, available)
    return max(1, min(value, available))


def frequency(rows: list[dict], kind: str, max_value: int) -> dict[int, int]:
    counts = {value: 0 for value in range(1, max_value + 1)}
    for row in rows:
        values = row["red"] if kind == "red" else [row["blue"]]
        for value in values:
            counts[value] += 1
    return counts


def omissions(rows: list[dict], kind: str, max_value: int) -> dict[int, int]:
    result = {}
    for value in range(1, max_value + 1):
        gap = 0
        for row in reversed(rows):
            hit = value in row["red"] if kind == "red" else value == row["blue"]
            if hit:
                break
            gap += 1
        result[value] = gap
    return result


def number_statistics(rows: list[dict], kind: str) -> list[dict]:
    max_value = RED_MAX if kind == "red" else BLUE_MAX
    windows = (5, 10, 20, 30, 50)
    full = frequency(rows, kind, max_value)
    omit = omissions(rows, kind, max_value)
    window_counts = {size: frequency(rows[-size:], kind, max_value) for size in windows}
    return [
        {
            "number": value,
            "frequency": full[value],
            "recent5": window_counts[5][value],
            "recent10": window_counts[10][value],
            "recent20": window_counts[20][value],
            "recent30": window_counts[30][value],
            "recent50": window_counts[50][value],
            "omission": omit[value],
        }
        for value in range(1, max_value + 1)
    ]


def zone_counts(red: list[int]) -> list[int]:
    return [
        sum(value <= 11 for value in red),
        sum(12 <= value <= 22 for value in red),
        sum(value >= 23 for value in red),
    ]


def max_consecutive_run(red: list[int]) -> int:
    if not red:
        return 0
    current = longest = 1
    for previous, value in zip(red, red[1:]):
        if value == previous + 1:
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    return longest


def shape_metrics(red: list[int]) -> dict:
    odd = sum(value % 2 for value in red)
    small = sum(value <= 16 for value in red)
    tails = Counter(value % 10 for value in red)
    return {
        "odd_even": f"{odd}:{len(red) - odd}",
        "small_large": f"{small}:{len(red) - small}",
        "zones": ":".join(str(value) for value in zone_counts(red)),
        "sum": sum(red),
        "span": max(red) - min(red),
        "max_consecutive": max_consecutive_run(red),
        "max_same_tail": max(tails.values(), default=0),
    }


def trend_summary(rows: list[dict]) -> dict:
    recent = rows[-20:]
    shapes = [shape_metrics(row["red"]) for row in recent]
    consecutive = sum(item["max_consecutive"] >= 2 for item in shapes)
    return {
        "window": len(recent),
        "average_sum": round(mean(item["sum"] for item in shapes), 2) if shapes else 0,
        "sum_range": [min((item["sum"] for item in shapes), default=0), max((item["sum"] for item in shapes), default=0)],
        "consecutive_draw_rate": round(consecutive / len(shapes), 4) if shapes else 0,
        "draws": [
            {
                "issue": row["issue"],
                "red": row["red"],
                "blue": row["blue"],
                "sum": shape_metrics(row["red"])["sum"],
                "zones": shape_metrics(row["red"])["zones"],
            }
            for row in recent
        ],
    }


def shape_distribution(rows: list[dict]) -> dict:
    shapes = [shape_metrics(row["red"]) for row in rows]
    if not shapes:
        return {
            "window": 0,
            "odd_counts": [],
            "small_counts": [],
            "top_zone_patterns": [],
            "sum_band": {"min": 0, "p25": 0, "median": 0, "p75": 0, "max": 0},
            "consecutive_draw_rate": 0,
        }

    def distribution(values: list[int]) -> list[dict]:
        counts = Counter(values)
        return [
            {"value": value, "count": count, "rate": round(count / len(values), 4)}
            for value, count in sorted(counts.items())
        ]

    def percentile(values: list[int], ratio: float) -> int:
        ordered = sorted(values)
        index = round((len(ordered) - 1) * ratio)
        return ordered[index]

    odd_counts = [int(item["odd_even"].split(":", 1)[0]) for item in shapes]
    small_counts = [int(item["small_large"].split(":", 1)[0]) for item in shapes]
    zone_counts_by_pattern = Counter(item["zones"] for item in shapes)
    sums = [item["sum"] for item in shapes]
    return {
        "window": len(shapes),
        "odd_counts": distribution(odd_counts),
        "small_counts": distribution(small_counts),
        "top_zone_patterns": [
            {"pattern": pattern, "count": count, "rate": round(count / len(shapes), 4)}
            for pattern, count in sorted(
                zone_counts_by_pattern.items(), key=lambda item: (-item[1], item[0])
            )[:6]
        ],
        "sum_band": {
            "min": min(sums),
            "p25": percentile(sums, 0.25),
            "median": percentile(sums, 0.5),
            "p75": percentile(sums, 0.75),
            "max": max(sums),
        },
        "consecutive_draw_rate": round(
            sum(item["max_consecutive"] >= 2 for item in shapes) / len(shapes), 4
        ),
    }


def factual_structure_rationale(red: list[int], snapshot: dict) -> str:
    structure = shape_metrics(red)
    history = snapshot["shape_history"]["selected_scope"]

    def most_common(items: list[dict], value_key: str) -> str:
        if not items:
            return "-"
        item = max(items, key=lambda row: int(row.get("count", 0)))
        return str(item.get(value_key, "-"))

    common_odd = most_common(history["odd_counts"], "value")
    common_small = most_common(history["small_counts"], "value")
    common_zone = most_common(history["top_zone_patterns"], "pattern")
    sum_band = history["sum_band"]
    historical = (
        f"历史{history['window']}期单期开奖（6红）最常见奇数{common_odd}个、小号{common_small}个、"
        f"三区{common_zone}，和值中间50%为{sum_band['p25']}-{sum_band['p75']}。"
    )
    actual = (
        f"本组{len(red)}红池实际奇偶{structure['odd_even']}、大小{structure['small_large']}、"
        f"三区{structure['zones']}、和值{structure['sum']}、最长连号{structure['max_consecutive']}。"
    )
    if len(red) == RED_DRAW_COUNT:
        return actual + historical

    expanded = [shape_metrics(list(values)) for values in combinations(red, RED_DRAW_COUNT)]
    odd_values = [int(item["odd_even"].split(":", 1)[0]) for item in expanded]
    small_values = [int(item["small_large"].split(":", 1)[0]) for item in expanded]
    sums = [item["sum"] for item in expanded]
    zone_patterns = Counter(item["zones"] for item in expanded)
    zone_text = "、".join(
        f"{pattern}（{count}注）" for pattern, count in zone_patterns.most_common(3)
    )
    consecutive_lines = sum(item["max_consecutive"] >= 2 for item in expanded)
    expanded_text = (
        f"展开{len(expanded)}注6红后，奇数个数{min(odd_values)}-{max(odd_values)}、"
        f"小号个数{min(small_values)}-{max(small_values)}、和值{min(sums)}-{max(sums)}，"
        f"主要三区为{zone_text}，含连号{consecutive_lines}注。"
    )
    return actual + expanded_text + historical


def ranked_numbers(values: dict[int, int], count: int, descending: bool) -> list[int]:
    return [
        number
        for number, _ in sorted(
            values.items(), key=lambda item: ((-item[1] if descending else item[1]), item[0])
        )[:count]
    ]


def percentile90(values: list[int]) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(len(ordered) * 0.9) - 1)
    return float(ordered[index])


def summarize_backtest(name: str, window: int, hits: list[int], expected: float) -> dict:
    average = mean(hits) if hits else 0
    return {
        "name": name,
        "window": window,
        "samples": len(hits),
        "average_hits": round(average, 4),
        "median_hits": float(median(hits)) if hits else 0,
        "p90_hits": percentile90(hits),
        "random_expectation": round(expected, 4),
        "delta_from_random": round(average - expected, 4),
    }


def rolling_backtests(rows: list[dict]) -> list[dict]:
    reports = []
    for window in (30, 50):
        results = {"hot": [], "omission": [], "cold": [], "repeat": [], "blue_hot": []}
        for index in range(window, len(rows)):
            prior = rows[index - window:index]
            actual = rows[index]
            red_freq = frequency(prior, "red", RED_MAX)
            red_omit = omissions(prior, "red", RED_MAX)
            blue_freq = frequency(prior, "blue", BLUE_MAX)
            pools = {
                "hot": ranked_numbers(red_freq, 8, True),
                "omission": ranked_numbers(red_omit, 8, True),
                "cold": ranked_numbers(red_freq, 8, False),
                "repeat": prior[-1]["red"],
                "blue_hot": ranked_numbers(blue_freq, 4, True),
            }
            for name in ("hot", "omission", "cold", "repeat"):
                results[name].append(len(set(actual["red"]) & set(pools[name])))
            results["blue_hot"].append(int(actual["blue"] in pools["blue_hot"]))

        reports.extend(
            [
                summarize_backtest("red_hot_top8", window, results["hot"], RED_DRAW_COUNT * 8 / RED_MAX),
                summarize_backtest("red_omission_top8", window, results["omission"], RED_DRAW_COUNT * 8 / RED_MAX),
                summarize_backtest("red_cold_top8", window, results["cold"], RED_DRAW_COUNT * 8 / RED_MAX),
                summarize_backtest("previous_draw_repeat", window, results["repeat"], RED_DRAW_COUNT * RED_DRAW_COUNT / RED_MAX),
                summarize_backtest("blue_hot_top4", window, results["blue_hot"], 4 / BLUE_MAX),
            ]
        )
    return reports


def build_analysis_snapshot(rows: list[dict], scope="all") -> dict:
    normalized = normalize_history(rows)
    if not normalized:
        raise AiAnalysisError("没有可用于 AI 分析的开奖数据")
    scope_size = resolve_scope(scope, len(normalized))
    selected = normalized[-scope_size:]
    return {
        "data": {
            "available_issues": len(normalized),
            "scope_issues": len(selected),
            "first_issue": selected[0]["issue"],
            "latest_issue": selected[-1]["issue"],
        },
        "latest_draw": selected[-1],
        "red_statistics": number_statistics(selected, "red"),
        "blue_statistics": number_statistics(selected, "blue"),
        "trend": trend_summary(selected),
        "shape_history": {
            "selected_scope": shape_distribution(selected),
            "recent20": shape_distribution(selected[-20:]),
        },
        "backtests": rolling_backtests(normalized),
    }


def _coerce_number_list(value, *, count: int, minimum: int, maximum: int, field: str) -> list[int]:
    if not isinstance(value, list):
        raise AiAnalysisError(f"AI 返回的{field}格式错误")
    numbers = []
    for item in value:
        if type(item) is int:
            number = item
        elif isinstance(item, str) and re.fullmatch(r"\d{1,2}", item.strip()):
            number = int(item)
        else:
            raise AiAnalysisError(f"AI 返回的{field}不是整数")
        numbers.append(number)
    numbers.sort()
    if len(numbers) != count or len(set(numbers)) != count:
        raise AiAnalysisError(f"AI 返回的{field}数量或重复校验失败")
    if any(number < minimum or number > maximum for number in numbers):
        raise AiAnalysisError(f"AI 返回的{field}超出范围")
    return numbers


def _text_list(value, *, limit: int, length: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:length] for item in value if str(item).strip()][:limit]


def _dynamic_profile(value, *, red_count: int) -> dict:
    if not isinstance(value, dict):
        raise AiAnalysisError("AI 未返回机器可校验的动态形态口径")

    def integer(item, field: str) -> int:
        if type(item) is int:
            return item
        if isinstance(item, str) and re.fullmatch(r"\d{1,3}", item.strip()):
            return int(item)
        raise AiAnalysisError(f"AI 动态口径的{field}不是整数")

    def pair(field: str, minimum: int, maximum: int) -> list[int]:
        raw = value.get(field)
        if not isinstance(raw, list) or len(raw) != 2:
            raise AiAnalysisError(f"AI 动态口径的{field}格式错误")
        result = [integer(item, field) for item in raw]
        if result[0] > result[1] or result[0] < minimum or result[1] > maximum:
            raise AiAnalysisError(f"AI 动态口径的{field}范围无效")
        return result

    odd_range = pair("odd_range", 0, red_count)
    small_range = pair("small_range", 0, red_count)
    legal_sum_min = sum(range(1, red_count + 1))
    legal_sum_max = sum(range(RED_MAX - red_count + 1, RED_MAX + 1))
    sum_range = pair("sum_range", legal_sum_min, legal_sum_max)
    raw_zones = value.get("zone_minimums")
    if not isinstance(raw_zones, list) or len(raw_zones) != 3:
        raise AiAnalysisError("AI 动态口径的zone_minimums格式错误")
    zone_minimums = [integer(item, "zone_minimums") for item in raw_zones]
    if any(item < 0 or item > red_count for item in zone_minimums) or sum(zone_minimums) > red_count:
        raise AiAnalysisError("AI 动态口径的zone_minimums范围无效")
    max_consecutive_run = integer(value.get("max_consecutive_run"), "max_consecutive_run")
    if not 1 <= max_consecutive_run <= red_count:
        raise AiAnalysisError("AI 动态口径的max_consecutive_run范围无效")
    return {
        "odd_range": odd_range,
        "small_range": small_range,
        "zone_minimums": zone_minimums,
        "sum_range": sum_range,
        "max_consecutive_run": max_consecutive_run,
    }


PROFILE_FIELDS = {
    "odd_range",
    "small_range",
    "zone_minimums",
    "sum_range",
    "max_consecutive_run",
}
EVIDENCE_SOURCES = {"statistics", "trend", "shape_history", "backtest"}


def _most_common_value(items: list[dict], field: str):
    if not items:
        return None
    return max(items, key=lambda item: int(item.get("count", 0))).get(field)


def build_profile_evidence_catalog(snapshot: dict) -> list[dict]:
    shape = snapshot["shape_history"]["selected_scope"]
    trend = snapshot["trend"]
    red_frequencies = [item["frequency"] for item in snapshot["red_statistics"]]
    blue_frequencies = [item["frequency"] for item in snapshot["blue_statistics"]]
    catalog = [
        {
            "id": "statistics.scope_issues",
            "source": "statistics",
            "label": "本次统计期数",
            "value": snapshot["data"]["scope_issues"],
            "supports": ["overall"],
        },
        {
            "id": "statistics.red_frequency_range",
            "source": "statistics",
            "label": "红球历史频次范围",
            "value": [min(red_frequencies), max(red_frequencies)],
            "supports": ["overall"],
        },
        {
            "id": "statistics.blue_frequency_range",
            "source": "statistics",
            "label": "蓝球历史频次范围",
            "value": [min(blue_frequencies), max(blue_frequencies)],
            "supports": ["overall"],
        },
        {
            "id": "shape.common_odd",
            "source": "shape_history",
            "label": "历史最常见奇数个数",
            "value": _most_common_value(shape["odd_counts"], "value"),
            "supports": ["odd_range"],
        },
        {
            "id": "shape.common_small",
            "source": "shape_history",
            "label": "历史最常见小号个数",
            "value": _most_common_value(shape["small_counts"], "value"),
            "supports": ["small_range"],
        },
        {
            "id": "shape.common_zone",
            "source": "shape_history",
            "label": "历史最常见三区形态",
            "value": _most_common_value(shape["top_zone_patterns"], "pattern"),
            "supports": ["zone_minimums"],
        },
        {
            "id": "shape.sum_middle_band",
            "source": "shape_history",
            "label": "历史和值中间50%区间",
            "value": [shape["sum_band"]["p25"], shape["sum_band"]["p75"]],
            "supports": ["sum_range"],
        },
        {
            "id": "trend.average_sum",
            "source": "trend",
            "label": "最近走势平均和值",
            "value": trend["average_sum"],
            "supports": ["sum_range"],
        },
        {
            "id": "trend.consecutive_draw_rate",
            "source": "trend",
            "label": "最近走势含连号期数比例",
            "value": trend["consecutive_draw_rate"],
            "supports": ["max_consecutive_run"],
        },
    ]
    catalog.extend(
        {
            "id": f"backtest.{item['name']}.{item['window']}",
            "source": "backtest",
            "label": f"{item['window']}期窗口 {item['name']} 相对随机期望差",
            "value": item["delta_from_random"],
            "supports": ["overall"],
        }
        for item in snapshot["backtests"]
    )
    return catalog


def _profile_is_feasible(profile: dict, *, red_count: int) -> bool:
    odd_low, odd_high = profile["odd_range"]
    small_low, small_high = profile["small_range"]
    sum_low, sum_high = profile["sum_range"]
    zone_mins = profile["zone_minimums"]
    max_run = profile["max_consecutive_run"]
    states = {(0, 0, 0, 0, 0, 0, 0, 0, 0)}
    available_odds = [
        sum(number % 2 for number in range(processed + 1, RED_MAX + 1))
        for processed in range(RED_MAX + 1)
    ]

    def viable(state: tuple[int, ...], processed: int) -> bool:
        count, odd, small, zone1, zone2, zone3, total, _, _ = state
        remaining = RED_MAX - processed
        need = red_count - count
        if need < 0 or need > remaining:
            return False

        available_odd = available_odds[processed]
        min_more_odd = max(0, need - (remaining - available_odd))
        max_more_odd = min(need, available_odd)
        if odd + max_more_odd < odd_low or odd + min_more_odd > odd_high:
            return False

        available_small = max(0, 16 - processed)
        min_more_small = max(0, need - (remaining - available_small))
        max_more_small = min(need, available_small)
        if small + max_more_small < small_low or small + min_more_small > small_high:
            return False

        zone_available = [
            max(0, 11 - processed),
            max(0, 22 - max(processed, 11)),
            max(0, 33 - max(processed, 22)),
        ]
        if any(
            actual + min(need, available) < minimum
            for actual, available, minimum in zip(
                (zone1, zone2, zone3), zone_available, zone_mins
            )
        ):
            return False

        if need:
            minimum_more = need * (2 * (processed + 1) + need - 1) // 2
            maximum_more = need * (2 * RED_MAX - need + 1) // 2
        else:
            minimum_more = maximum_more = 0
        return total + minimum_more <= sum_high and total + maximum_more >= sum_low

    for number in range(1, RED_MAX + 1):
        next_states = set()
        zone_index = 0 if number <= 11 else 1 if number <= 22 else 2
        for state in states:
            skipped = (*state[:7], 0, 0)
            if viable(skipped, number):
                next_states.add(skipped)

            count, odd, small, zone1, zone2, zone3, total, previous_selected, run = state
            if count >= red_count:
                continue
            new_odd = odd + number % 2
            new_small = small + int(number <= 16)
            new_total = total + number
            new_run = run + 1 if previous_selected else 1
            if new_odd > odd_high or new_small > small_high or new_total > sum_high or new_run > max_run:
                continue
            zones = [zone1, zone2, zone3]
            zones[zone_index] = min(zone_mins[zone_index], zones[zone_index] + 1)
            selected = (
                count + 1,
                new_odd,
                new_small,
                zones[0],
                zones[1],
                zones[2],
                new_total,
                1,
                new_run,
            )
            if viable(selected, number):
                next_states.add(selected)
        states = next_states
        if not states:
            return False

    return any(
        count == red_count
        and odd_low <= odd <= odd_high
        and small_low <= small <= small_high
        and (zone1, zone2, zone3) == tuple(zone_mins)
        and sum_low <= total <= sum_high
        for count, odd, small, zone1, zone2, zone3, total, _, _ in states
    )


def _validated_profile_evidence(value, snapshot: dict) -> list[dict]:
    if not isinstance(value, list):
        raise AiAnalysisError("AI 未返回结构化的历史依据")
    catalog = {item["id"]: item for item in build_profile_evidence_catalog(snapshot)}
    normalized = []
    seen = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise AiAnalysisError("AI 历史依据格式错误")
        evidence_id = str(raw.get("id", "")).strip()
        reason = str(raw.get("reason", "")).strip()[:240]
        if evidence_id not in catalog or evidence_id in seen or not reason:
            raise AiAnalysisError("AI 历史依据无法与服务端报告核对")
        seen.add(evidence_id)
        item = dict(catalog[evidence_id])
        item["reason"] = reason
        normalized.append(item)

    sources = {item["source"] for item in normalized}
    supported = {field for item in normalized for field in item["supports"]}
    if not EVIDENCE_SOURCES <= sources:
        raise AiAnalysisError("AI 历史依据必须覆盖统计、走势、形态和回测")
    if not PROFILE_FIELDS <= supported:
        raise AiAnalysisError("AI 历史依据未覆盖全部动态形态口径")
    return normalized


def validate_analysis_profile(value: dict, snapshot: dict, *, red_count: int) -> dict:
    if not isinstance(value, dict):
        raise AiAnalysisError("AI 第一阶段返回内容不是 JSON 对象")
    forbidden = {"red", "blue", "red_reasons", "blue_reasons", "structure_rationale"} & value.keys()
    if forbidden:
        raise AiAnalysisError("AI 第一阶段不得返回候选号码或选号理由")

    summary = str(value.get("summary", "")).strip()[:600]
    selection_rules = _text_list(value.get("selection_rules"), limit=6, length=240)
    dynamic_profile = _dynamic_profile(value.get("dynamic_profile"), red_count=red_count)
    backtest_conclusion = str(value.get("backtest_conclusion", "")).strip()[:600]
    risk_note = str(value.get("risk_note", "")).strip()[:400]
    profile_evidence = _validated_profile_evidence(value.get("profile_evidence"), snapshot)

    if not summary:
        raise AiAnalysisError("AI 未返回历史分析摘要")
    if len(selection_rules) < 2:
        raise AiAnalysisError("AI 未返回至少两条本期动态规则")
    if not backtest_conclusion:
        raise AiAnalysisError("AI 未返回滚动回测结论")
    if not risk_note:
        raise AiAnalysisError("AI 未返回随机概率风险边界")
    if not _profile_is_feasible(dynamic_profile, red_count=red_count):
        raise AiAnalysisError("AI 生成的动态口径无可满足的红球组合")

    return {
        "summary": summary,
        "selection_rules": selection_rules,
        "dynamic_profile": dynamic_profile,
        "profile_evidence": profile_evidence,
        "backtest_conclusion": backtest_conclusion,
        "risk_note": risk_note,
    }


def _reason_map(value) -> dict[int, str]:
    if not isinstance(value, list):
        return {}
    result = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("number"))
        except (TypeError, ValueError):
            continue
        reason = str(item.get("reason", "")).strip()
        if reason:
            result[number] = reason[:240]
    return result


def validate_recommendation(
    value: dict,
    snapshot: dict,
    frozen_analysis: dict,
    *,
    red_count: int,
    blue_count: int,
) -> dict:
    if not isinstance(value, dict):
        raise AiAnalysisError("AI 第二阶段返回内容不是 JSON 对象")
    frozen_fields = {
        "summary",
        "selection_rules",
        "dynamic_profile",
        "profile_evidence",
        "backtest_conclusion",
        "risk_note",
    }
    if frozen_fields & value.keys():
        raise AiAnalysisError("AI 第二阶段不得返回或改写已冻结的分析规则")

    red = _coerce_number_list(value.get("red"), count=red_count, minimum=1, maximum=RED_MAX, field="红球")
    blue = _coerce_number_list(value.get("blue"), count=blue_count, minimum=1, maximum=BLUE_MAX, field="蓝球")
    structure = shape_metrics(red)
    dynamic_profile = frozen_analysis["dynamic_profile"]
    odd = sum(number % 2 for number in red)
    small = sum(number <= 16 for number in red)
    zones = zone_counts(red)
    profile_violations = []
    if not dynamic_profile["odd_range"][0] <= odd <= dynamic_profile["odd_range"][1]:
        profile_violations.append(f"奇数{odd}不在{dynamic_profile['odd_range']}")
    if not dynamic_profile["small_range"][0] <= small <= dynamic_profile["small_range"][1]:
        profile_violations.append(f"小号{small}不在{dynamic_profile['small_range']}")
    if any(actual < minimum for actual, minimum in zip(zones, dynamic_profile["zone_minimums"])):
        profile_violations.append(f"三区{zones}低于下限{dynamic_profile['zone_minimums']}")
    if not dynamic_profile["sum_range"][0] <= structure["sum"] <= dynamic_profile["sum_range"][1]:
        profile_violations.append(f"和值{structure['sum']}不在{dynamic_profile['sum_range']}")
    if structure["max_consecutive"] > dynamic_profile["max_consecutive_run"]:
        profile_violations.append(
            f"最长连号{structure['max_consecutive']}超过{dynamic_profile['max_consecutive_run']}"
        )
    if profile_violations:
        raise AiAnalysisError(f"AI 号码不符合其本期动态口径：{'；'.join(profile_violations)}")

    red_stats = {item["number"]: item for item in snapshot["red_statistics"]}
    blue_stats = {item["number"]: item for item in snapshot["blue_statistics"]}
    red_reasons = _reason_map(value.get("red_reasons"))
    blue_reasons = _reason_map(value.get("blue_reasons"))
    model_structure_rationale = str(value.get("structure_rationale", "")).strip()[:600]
    missing_red_reasons = [number for number in red if number not in red_reasons]
    missing_blue_reasons = [number for number in blue if number not in blue_reasons]

    if not model_structure_rationale:
        raise AiAnalysisError("AI 未返回本期形态取舍")
    if missing_red_reasons or missing_blue_reasons:
        raise AiAnalysisError("AI 未返回全部推荐号码的逐号理由")

    def explain(number: int, stats: dict, reasons: dict[int, str]) -> dict:
        item = stats[number]
        return {
            "number": number,
            "reason": reasons.get(number, "用于组合覆盖与结构分散，不代表该号码更容易开出。"),
            "frequency": item["frequency"],
            "recent20": item["recent20"],
            "omission": item["omission"],
        }

    return {
        "summary": frozen_analysis["summary"],
        "selection_rules": frozen_analysis["selection_rules"],
        "dynamic_profile": dynamic_profile,
        "profile_evidence": frozen_analysis["profile_evidence"],
        "model_structure_rationale": model_structure_rationale,
        "structure_rationale": factual_structure_rationale(red, snapshot),
        "red": red,
        "blue": blue,
        "red_reasons": [explain(number, red_stats, red_reasons) for number in red],
        "blue_reasons": [explain(number, blue_stats, blue_reasons) for number in blue],
        "structure": structure,
        "backtest_conclusion": frozen_analysis["backtest_conclusion"],
        "risk_note": frozen_analysis["risk_note"],
    }


def build_messages(snapshot: dict, *, red_count: int, blue_count: int, shape_filter: bool, avoid_popular: bool) -> list[dict]:
    output_schema = {
        "summary": "非空字符串：基于所给数据的历史分析摘要",
        "selection_rules": "数组：2-6条由本次报告动态生成的规则字符串",
        "dynamic_profile": {
            "odd_range": f"数组：本期{red_count}红池允许的奇数个数最小值和最大值",
            "small_range": f"数组：本期{red_count}红池允许的01-16个数最小值和最大值",
            "zone_minimums": "数组：本期红池在01-11、12-22、23-33三区各自的最少个数",
            "sum_range": f"数组：本期{red_count}红池和值最小值和最大值",
            "max_consecutive_run": f"整数：本期{red_count}红池允许的最长连号",
        },
        "profile_evidence": "数组：7-12个{id必须来自evidence_catalog,reason非空字符串}对象，覆盖统计、走势、形态、回测及全部动态口径",
        "backtest_conclusion": "非空字符串：比较回测值与随机期望，不夸大样本偏差",
        "risk_note": "非空字符串：说明每个合法组合概率相同且不保证中奖",
    }
    system = (
        "你是双色球历史研究助手。你只能使用用户消息里的真实 JSON 数据，不能补造开奖、频次、遗漏或回测结果。"
        "双色球是独立随机开奖，每个合法单式组合概率相同；历史标签只用于组合结构和覆盖分散，不能称为预测优势。"
        "先比较近期与长期统计、历史形态分布、最近20期走势及30/50期滚动回测，再自行归纳本期动态选号规则。"
        "这是第一阶段，只生成分析报告和 dynamic_profile，严禁选号，严禁返回 red、blue、逐号理由或任何候选号码。"
        "除号码数量、范围和不重复外，不得预设固定奇偶、大小、三区、和值或连号阈值。"
        "如果 constraints.shape_analysis_requested 为 true，应结合 research_data.shape_history 做软性取舍；"
        "极端形态也是合法组合，是否约束必须由本次报告决定。"
        "profile_evidence 只能引用 evidence_catalog 中的 id，服务端会用原始数值复核；不要自行抄写或编造统计数值。"
        "禁止用该出、回补、延续、有望、看好或提高中奖概率等措辞暗示未来更容易开出；只能描述历史覆盖取舍。"
        "summary、selection_rules、dynamic_profile、profile_evidence、backtest_conclusion和risk_note必须完整返回。"
        "只输出合法 JSON，不要 Markdown，不要思维过程。"
    )
    constraints = {
        "red_count": red_count,
        "red_range": [1, RED_MAX],
        "blue_count": blue_count,
        "blue_range": [1, BLUE_MAX],
        "red_unique": True,
        "blue_unique": True,
        "shape_analysis_requested": shape_filter,
        "structure_policy": "根据历史形态分布动态判断，不使用固定比例或硬阈值",
        "dynamic_profile_applies_to_full_red_pool": red_count,
        "avoid_popular_is_only_split_risk_hint": avoid_popular,
        "consecutive_numbers_are_allowed": True,
        "required_output_schema": output_schema,
    }
    user = {
        "stage": "analysis_profile",
        "task": "分析历史统计、走势、形态分布和滚动回测，只生成本期动态规则，不生成号码",
        "constraints": constraints,
        "evidence_catalog": build_profile_evidence_catalog(snapshot),
        "research_data": snapshot,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False, separators=(",", ":"))},
    ]


def build_selection_messages(
    snapshot: dict,
    frozen_analysis: dict,
    *,
    red_count: int,
    blue_count: int,
    avoid_popular: bool = False,
) -> list[dict]:
    output_schema = {
        "structure_rationale": "非空字符串：说明号码如何满足已冻结的动态口径",
        "red": f"数组：恰好{red_count}个1-33不重复整数",
        "blue": f"数组：恰好{blue_count}个1-16不重复整数",
        "red_reasons": "数组：red中每个号码各一个{number整数,reason非空字符串}对象",
        "blue_reasons": "数组：blue中每个号码各一个{number整数,reason非空字符串}对象",
    }
    system = (
        "你是双色球历史研究助手。这是第二阶段，服务端已冻结第一阶段的分析和动态口径。"
        "你只能在 frozen_analysis.dynamic_profile 内选号，不得返回、重申或修改 summary、selection_rules、dynamic_profile、profile_evidence、backtest_conclusion 或 risk_note。"
        "红蓝球理由只能使用给定的真实统计做定性取舍，不得补造数字，不得暗示提高中奖概率。"
        "输出前必须逐个核对红球奇数个数、01-16个数、三区数量、和值和最长连号，确保全部符合 server_validation_checklist；校验失败时必须更换号码。"
        "只输出 required_output_schema 中的字段和合法 JSON，不要 Markdown，不要思维过程。"
    )
    user = {
        "stage": "number_selection",
        "task": "按已冻结的动态口径生成推荐号码和完整逐号理由",
        "constraints": {
            "red_count": red_count,
            "red_range": [1, RED_MAX],
            "blue_count": blue_count,
            "blue_range": [1, BLUE_MAX],
            "red_unique": True,
            "blue_unique": True,
            "avoid_popular_is_only_split_risk_hint": avoid_popular,
            "required_output_schema": output_schema,
        },
        "frozen_analysis": frozen_analysis,
        "server_validation_checklist": {
            "odd_count_range": frozen_analysis["dynamic_profile"]["odd_range"],
            "small_01_16_count_range": frozen_analysis["dynamic_profile"]["small_range"],
            "zone_01_11_12_22_23_33_minimums": frozen_analysis["dynamic_profile"]["zone_minimums"],
            "red_sum_range": frozen_analysis["dynamic_profile"]["sum_range"],
            "maximum_consecutive_run": frozen_analysis["dynamic_profile"]["max_consecutive_run"],
        },
        "number_research": {
            "latest_draw": snapshot["latest_draw"],
            "red_statistics": snapshot["red_statistics"],
            "blue_statistics": snapshot["blue_statistics"],
        },
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False, separators=(",", ":"))},
    ]


def parse_model_json_content(content) -> dict:
    if isinstance(content, dict):
        return content
    if not isinstance(content, str) or not content.strip():
        raise AiResponseError("DeepSeek API 未返回有效 JSON 内容")

    text = content.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline >= 0:
            text = text[first_newline + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].rstrip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        object_start = text.find("{")
        if object_start < 0:
            raise AiResponseError("DeepSeek API 未返回有效 JSON 内容")
        try:
            value, _ = json.JSONDecoder().raw_decode(text[object_start:])
        except json.JSONDecodeError as exc:
            raise AiResponseError("DeepSeek API 未返回有效 JSON 内容") from exc
    if not isinstance(value, dict):
        raise AiResponseError("DeepSeek API 未返回 JSON 对象")
    return value


def call_deepseek(messages: list[dict], *, timeout: int = 60) -> dict:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise AiAnalysisError("服务端未配置 DEEPSEEK_API_KEY")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    model = os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    try:
        request_stage = json.loads(messages[1]["content"]).get("stage", "")
    except (IndexError, KeyError, TypeError, json.JSONDecodeError):
        request_stage = ""
    payload = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "enabled" if request_stage == "number_selection" else "disabled"},
        "temperature": 0.25,
        "max_tokens": 6000 if request_stage == "number_selection" else 3200,
        "stream": False,
        "user_id": "ssq-research",
    }
    request = Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    request_timeout = max(timeout, 90) if request_stage == "number_selection" else timeout
    try:
        with urlopen(request, timeout=request_timeout) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise AiAnalysisError(f"DeepSeek API 返回 HTTP {exc.code}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AiAnalysisError("DeepSeek API 请求失败或返回格式异常") from exc
    try:
        choice = raw["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AiResponseError("DeepSeek API 未返回有效 JSON 内容") from exc
    try:
        return parse_model_json_content(content)
    except AiResponseError as exc:
        if choice.get("finish_reason") == "length":
            raise AiResponseError("DeepSeek API JSON 输出被截断") from exc
        raise


def _request_stage(
    requester: Callable[[list[dict]], dict],
    messages: list[dict],
    validator: Callable[[dict], dict],
    *,
    stage_name: str,
    max_attempts: int = 2,
) -> dict:
    current_messages = messages
    last_error = None
    for attempt in range(max_attempts):
        try:
            raw = requester(current_messages)
        except AiResponseError as exc:
            last_error = exc
            if attempt < max_attempts - 1:
                current_messages = current_messages + [
                    {
                        "role": "user",
                        "content": f"{stage_name}上次没有返回有效 JSON。请按原约束重新输出完整 JSON 对象。",
                    }
                ]
                continue
            raise
        try:
            return validator(raw)
        except AiAnalysisError as exc:
            last_error = exc
            if attempt < max_attempts - 1:
                current_messages = current_messages + [
                    {"role": "assistant", "content": json.dumps(raw, ensure_ascii=False)},
                    {
                        "role": "user",
                        "content": f"{stage_name}上次 JSON 未通过服务端校验：{exc}。请严格按原约束重新输出完整 JSON。",
                    },
                ]
    raise last_error or AiAnalysisError(f"{stage_name}校验失败")


def generate_ai_recommendation(
    rows: list[dict],
    *,
    scope="all",
    red_count: int = 7,
    blue_count: int = 2,
    shape_filter: bool = True,
    avoid_popular: bool = True,
    requester: Callable[[list[dict]], dict] = call_deepseek,
) -> dict:
    if not 6 <= red_count <= 12 or not 1 <= blue_count <= 6:
        raise AiAnalysisError("AI 推荐数量应为 6-12 个红球、1-6 个蓝球")
    snapshot = build_analysis_snapshot(rows, scope)
    analysis_messages = build_messages(
        snapshot,
        red_count=red_count,
        blue_count=blue_count,
        shape_filter=shape_filter,
        avoid_popular=avoid_popular,
    )
    frozen_analysis = _request_stage(
        requester,
        analysis_messages,
        lambda raw: validate_analysis_profile(raw, snapshot, red_count=red_count),
        stage_name="AI 分析阶段",
    )
    selection_messages = build_selection_messages(
        snapshot,
        frozen_analysis,
        red_count=red_count,
        blue_count=blue_count,
        avoid_popular=avoid_popular,
    )
    recommendation = _request_stage(
        requester,
        selection_messages,
        lambda raw: validate_recommendation(
            raw,
            snapshot,
            frozen_analysis,
            red_count=red_count,
            blue_count=blue_count,
        ),
        stage_name="AI 选号阶段",
        max_attempts=3,
    )

    return {
        "recommendation": recommendation,
        "research": {
            "data": snapshot["data"],
            "latest_draw": snapshot["latest_draw"],
            "trend": {key: value for key, value in snapshot["trend"].items() if key != "draws"},
            "shape_history": snapshot["shape_history"],
            "backtests": snapshot["backtests"],
        },
        "pipeline": {"mode": "two_stage", "analysis_frozen_before_selection": True},
        "model": os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": "历史统计、走势图和回测不能预测随机开奖；推荐只用于研究和组合结构参考。",
    }
