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
BET_MODES = {"single", "complex", "dantuo"}
STRATEGY_POLICIES = {
    "official": "官方机选口径：不把历史冷热或遗漏作为选号优势，只允许按需做票面形态筛选",
    "fair": "概率机选口径：保持均匀抽样思路，历史数据只用于检查极端形态",
    "balanced": "综合研究：同时比较长期统计、近期走势、历史形态和滚动回测",
    "hot": "热号方向：必须先用滚动回测核对，证据不足时应弱化或否定该方向",
    "omission": "遗漏方向：必须先用滚动回测核对，不得把久未出现解释为更可能回补",
    "cold": "冷号方向：必须先用滚动回测核对，证据不足时应弱化或否定该方向",
    "mixed": "冷热混合：把冷热标签仅作为分散覆盖的候选维度",
    "random": "纯随机口径：历史研究只用于解释，不对号码分配预测权重",
}


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
    result = {
        "odd_even": f"{odd}:{len(red) - odd}",
        "small_large": f"{small}:{len(red) - small}",
        "zones": ":".join(str(value) for value in zone_counts(red)),
        "sum": sum(red),
        "span": max(red) - min(red),
        "max_consecutive": max_consecutive_run(red),
        "max_same_tail": max(tails.values(), default=0),
    }
    return result


def expanded_red_tickets(
    red: list[int],
    *,
    bet_mode: str,
    dan: list[int] | None = None,
    tuo: list[int] | None = None,
) -> list[list[int]]:
    """Expand a ticket format into the distinct six-red combinations it buys."""
    if bet_mode == "dantuo":
        fixed = sorted(dan or [])
        candidates = sorted(tuo or [])
        choose_count = RED_DRAW_COUNT - len(fixed)
        if not 1 <= len(fixed) <= 5 or choose_count < 1 or len(candidates) < choose_count:
            return []
        return [sorted(fixed + list(values)) for values in combinations(candidates, choose_count)]
    if len(red) == RED_DRAW_COUNT:
        return [sorted(red)]
    return [list(values) for values in combinations(sorted(red), RED_DRAW_COUNT)]


def red_ticket_count_for_mode(
    *, bet_mode: str, red_count: int, dan_count: int = 0, tuo_count: int = 0
) -> int:
    if bet_mode == "dantuo":
        choose_count = RED_DRAW_COUNT - dan_count
        return math.comb(tuo_count, choose_count) if 0 <= choose_count <= tuo_count else 0
    return math.comb(red_count, RED_DRAW_COUNT) if red_count >= RED_DRAW_COUNT else 0


def ticket_structure_summary(tickets: list[list[int]]) -> dict:
    structures = [shape_metrics(ticket) for ticket in tickets]
    if not structures:
        return {
            "red_ticket_count": 0,
            "odd_range": [0, 0],
            "small_range": [0, 0],
            "sum_range": [0, 0],
            "max_consecutive": 0,
            "consecutive_ticket_count": 0,
            "zone_patterns": [],
        }
    odd_values = [int(item["odd_even"].split(":", 1)[0]) for item in structures]
    small_values = [int(item["small_large"].split(":", 1)[0]) for item in structures]
    sums = [item["sum"] for item in structures]
    zone_patterns = Counter(item["zones"] for item in structures)
    return {
        "red_ticket_count": len(structures),
        "odd_range": [min(odd_values), max(odd_values)],
        "small_range": [min(small_values), max(small_values)],
        "sum_range": [min(sums), max(sums)],
        "max_consecutive": max(item["max_consecutive"] for item in structures),
        "consecutive_ticket_count": sum(item["max_consecutive"] >= 2 for item in structures),
        "zone_patterns": [
            {"pattern": pattern, "count": count}
            for pattern, count in zone_patterns.most_common()
        ],
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


def factual_structure_rationale(
    red: list[int],
    snapshot: dict,
    *,
    bet_mode: str,
    dan: list[int] | None = None,
    tuo: list[int] | None = None,
) -> str:
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
    tickets = expanded_red_tickets(red, bet_mode=bet_mode, dan=dan, tuo=tuo)
    if len(tickets) == 1:
        return actual + historical

    ticket_summary = ticket_structure_summary(tickets)
    zone_text = "、".join(
        f"{item['pattern']}（{item['count']}组）"
        for item in ticket_summary["zone_patterns"][:3]
    )
    mode_text = (
        f"按{len(dan or [])}胆{len(tuo or [])}拖实际展开"
        if bet_mode == "dantuo"
        else "按复式实际展开"
    )
    expanded_text = (
        f"{mode_text}{ticket_summary['red_ticket_count']}组6红组合后，"
        f"奇数个数{ticket_summary['odd_range'][0]}-{ticket_summary['odd_range'][1]}、"
        f"小号个数{ticket_summary['small_range'][0]}-{ticket_summary['small_range'][1]}、"
        f"和值{ticket_summary['sum_range'][0]}-{ticket_summary['sum_range'][1]}，"
        f"主要三区为{zone_text}，含连号{ticket_summary['consecutive_ticket_count']}组。"
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


DYNAMIC_RULE_FIELDS = {
    "odd_count": "odd_range",
    "small_count": "small_range",
    "zone_minimums": "zone_minimums",
    "sum": "sum_range",
    "max_consecutive_run": "max_consecutive_run",
}
PROFILE_FIELDS = set(DYNAMIC_RULE_FIELDS.values())
EVIDENCE_SOURCES = {"statistics", "trend", "shape_history", "backtest"}


def _rule_integer(item, field: str) -> int:
    if type(item) is int:
        return item
    if isinstance(item, str) and re.fullmatch(r"\d{1,3}", item.strip()):
        return int(item)
    raise AiAnalysisError(f"AI 动态规则的{field}不是整数")


def _broad_dynamic_profile(red_count: int = RED_DRAW_COUNT) -> dict:
    return {
        "odd_range": [0, red_count],
        "small_range": [0, red_count],
        "zone_minimums": [0, 0, 0],
        "sum_range": [sum(range(1, red_count + 1)), sum(range(RED_MAX - red_count + 1, RED_MAX + 1))],
        "max_consecutive_run": red_count,
        "active_fields": [],
    }


def _normalize_dynamic_rules(value, snapshot: dict) -> tuple[list[dict], dict]:
    if not isinstance(value, list) or len(value) > len(DYNAMIC_RULE_FIELDS):
        raise AiAnalysisError("AI 动态规则格式错误")

    catalog = {item["id"]: item for item in build_profile_evidence_catalog(snapshot)}
    red_count = RED_DRAW_COUNT
    profile = _broad_dynamic_profile()
    normalized = []
    seen_fields = set()

    for raw in value:
        if not isinstance(raw, dict):
            raise AiAnalysisError("AI 动态规则格式错误")
        field = str(raw.get("field", "")).strip()
        profile_field = DYNAMIC_RULE_FIELDS.get(field)
        if not profile_field or field in seen_fields:
            raise AiAnalysisError("AI 动态规则类型无效或重复")
        seen_fields.add(field)

        description = str(raw.get("description", "")).strip()[:240]
        evidence_ids = _text_list(raw.get("evidence_ids"), limit=4, length=80)
        if not description or not evidence_ids or len(evidence_ids) != len(set(evidence_ids)):
            raise AiAnalysisError("AI 动态规则缺少说明或历史依据")
        evidence = [catalog.get(evidence_id) for evidence_id in evidence_ids]
        if any(item is None for item in evidence):
            raise AiAnalysisError("AI 动态规则引用了不存在的历史依据")
        if not any(profile_field in item["supports"] for item in evidence if item):
            raise AiAnalysisError("AI 动态规则没有对应的可核对依据")

        rule = {"field": field, "description": description, "evidence_ids": evidence_ids}
        if field in {"odd_count", "small_count", "sum"}:
            minimum = _rule_integer(raw.get("min"), f"{field}.min")
            maximum = _rule_integer(raw.get("max"), f"{field}.max")
            legal_min, legal_max = (0, red_count)
            if field == "sum":
                legal_min, legal_max = profile["sum_range"]
            if minimum > maximum or minimum < legal_min or maximum > legal_max:
                raise AiAnalysisError(f"AI 动态规则的{field}范围无效")
            rule.update({"min": minimum, "max": maximum})
            profile[profile_field] = [minimum, maximum]
        elif field == "zone_minimums":
            values = raw.get("values")
            if not isinstance(values, list) or len(values) != 3:
                raise AiAnalysisError("AI 动态规则的zone_minimums格式错误")
            values = [_rule_integer(item, "zone_minimums") for item in values]
            if any(item < 0 or item > red_count for item in values) or sum(values) > red_count:
                raise AiAnalysisError("AI 动态规则的zone_minimums范围无效")
            rule["values"] = values
            profile[profile_field] = values
        else:
            maximum = _rule_integer(raw.get("max"), "max_consecutive_run.max")
            if not 1 <= maximum <= red_count:
                raise AiAnalysisError("AI 动态规则的max_consecutive_run范围无效")
            rule["max"] = maximum
            profile[profile_field] = maximum

        normalized.append(rule)

    profile["active_fields"] = [DYNAMIC_RULE_FIELDS[item["field"]] for item in normalized]
    return normalized, profile


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
    if not profile.get("active_fields"):
        return True
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


def _validated_profile_evidence(value, snapshot: dict, *, required_fields: set[str]) -> list[dict]:
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
    if not required_fields <= supported:
        raise AiAnalysisError("AI 历史依据未覆盖本次启用的动态规则")
    return normalized


def validate_analysis_profile(
    value: dict,
    snapshot: dict,
    *,
    red_count: int,
    shape_filter: bool = True,
) -> dict:
    if not isinstance(value, dict):
        raise AiAnalysisError("AI 第一阶段返回内容不是 JSON 对象")
    forbidden = {"red", "dan", "tuo", "blue", "red_reasons", "blue_reasons", "structure_rationale"} & value.keys()
    if forbidden:
        raise AiAnalysisError("AI 第一阶段不得返回候选号码或选号理由")

    summary = str(value.get("summary", "")).strip()[:600]
    selection_rules = _text_list(value.get("selection_rules"), limit=6, length=240)
    dynamic_rules, dynamic_profile = _normalize_dynamic_rules(
        value.get("dynamic_rules"),
        snapshot,
    )
    strategy_assessment = str(value.get("strategy_assessment", "")).strip()[:600]
    backtest_conclusion = str(value.get("backtest_conclusion", "")).strip()[:600]
    risk_note = str(value.get("risk_note", "")).strip()[:400]
    profile_evidence = _validated_profile_evidence(
        value.get("profile_evidence"),
        snapshot,
        required_fields=set(dynamic_profile["active_fields"]),
    )

    if not summary:
        raise AiAnalysisError("AI 未返回历史分析摘要")
    if not selection_rules:
        raise AiAnalysisError("AI 未返回本期选号策略")
    if shape_filter and not dynamic_rules:
        raise AiAnalysisError("开启形态过滤时 AI 至少要选择一条可校验动态规则")
    if not strategy_assessment:
        raise AiAnalysisError("AI 未核对页面选择的策略方向")
    if not backtest_conclusion:
        raise AiAnalysisError("AI 未返回滚动回测结论")
    if not risk_note:
        raise AiAnalysisError("AI 未返回随机概率风险边界")
    if not _profile_is_feasible(dynamic_profile, red_count=RED_DRAW_COUNT):
        raise AiAnalysisError("AI 生成的动态口径无可满足的6红单注组合")

    return {
        "summary": summary,
        "selection_rules": selection_rules,
        "dynamic_rules": dynamic_rules,
        "dynamic_profile": dynamic_profile,
        "profile_evidence": profile_evidence,
        "strategy_assessment": strategy_assessment,
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


PREDICTIVE_REASON_TERMS = (
    "该出",
    "回补",
    "延续",
    "有望",
    "看好",
    "更可能",
    "提高中奖",
    "必中",
    "必出",
    "稳胆",
)


def _validate_reason_language(reasons: dict[int, str], *, field: str) -> None:
    for number, reason in reasons.items():
        matched = next((term for term in PREDICTIVE_REASON_TERMS if term in reason), "")
        if matched:
            raise AiAnalysisError(f"AI {field}{number:02d}理由包含预测性措辞“{matched}”")


def _ticket_profile_violations(tickets: list[list[int]], profile: dict) -> list[str]:
    if not tickets:
        return ["没有可展开的合法6红组合"]
    structures = [shape_metrics(ticket) for ticket in tickets]
    active_fields = set(profile.get("active_fields", PROFILE_FIELDS))
    violations = []

    odd_values = [int(item["odd_even"].split(":", 1)[0]) for item in structures]
    if "odd_range" in active_fields:
        invalid = [value for value in odd_values if not profile["odd_range"][0] <= value <= profile["odd_range"][1]]
        if invalid:
            violations.append(
                f"单注奇数范围{min(odd_values)}-{max(odd_values)}不全在{profile['odd_range']}"
            )

    small_values = [int(item["small_large"].split(":", 1)[0]) for item in structures]
    if "small_range" in active_fields:
        invalid = [value for value in small_values if not profile["small_range"][0] <= value <= profile["small_range"][1]]
        if invalid:
            violations.append(
                f"单注小号范围{min(small_values)}-{max(small_values)}不全在{profile['small_range']}"
            )

    if "zone_minimums" in active_fields:
        invalid_count = sum(
            any(actual < minimum for actual, minimum in zip(zone_counts(ticket), profile["zone_minimums"]))
            for ticket in tickets
        )
        if invalid_count:
            violations.append(
                f"{invalid_count}/{len(tickets)}组6红的三区低于下限{profile['zone_minimums']}"
            )

    sums = [item["sum"] for item in structures]
    if "sum_range" in active_fields:
        invalid = [value for value in sums if not profile["sum_range"][0] <= value <= profile["sum_range"][1]]
        if invalid:
            violations.append(
                f"单注和值范围{min(sums)}-{max(sums)}不全在{profile['sum_range']}"
            )

    max_run = max(item["max_consecutive"] for item in structures)
    if "max_consecutive_run" in active_fields and max_run > profile["max_consecutive_run"]:
        invalid_count = sum(
            item["max_consecutive"] > profile["max_consecutive_run"] for item in structures
        )
        violations.append(
            f"{invalid_count}/{len(tickets)}组6红最长连号超过{profile['max_consecutive_run']}"
        )
    return violations


def validate_recommendation(
    value: dict,
    snapshot: dict,
    frozen_analysis: dict,
    *,
    red_count: int,
    blue_count: int,
    bet_mode: str = "complex",
    strategy: str = "balanced",
    dan_count: int = 0,
    tuo_count: int = 0,
) -> dict:
    if not isinstance(value, dict):
        raise AiAnalysisError("AI 第二阶段返回内容不是 JSON 对象")
    frozen_fields = {
        "summary",
        "selection_rules",
        "dynamic_rules",
        "dynamic_profile",
        "profile_evidence",
        "strategy_assessment",
        "backtest_conclusion",
        "risk_note",
    }
    if frozen_fields & value.keys():
        raise AiAnalysisError("AI 第二阶段不得返回或改写已冻结的分析规则")

    dan = []
    tuo = []
    if bet_mode == "dantuo":
        dan = _coerce_number_list(value.get("dan"), count=dan_count, minimum=1, maximum=RED_MAX, field="胆码")
        tuo = _coerce_number_list(value.get("tuo"), count=tuo_count, minimum=1, maximum=RED_MAX, field="拖码")
        if set(dan) & set(tuo):
            raise AiAnalysisError("AI 返回的胆码和拖码重复")
        red = sorted(dan + tuo)
    else:
        red = _coerce_number_list(value.get("red"), count=red_count, minimum=1, maximum=RED_MAX, field="红球")
    blue = _coerce_number_list(value.get("blue"), count=blue_count, minimum=1, maximum=BLUE_MAX, field="蓝球")
    structure = shape_metrics(red)
    tickets = expanded_red_tickets(red, bet_mode=bet_mode, dan=dan, tuo=tuo)
    ticket_structure = ticket_structure_summary(tickets)
    dynamic_profile = frozen_analysis["dynamic_profile"]
    profile_violations = _ticket_profile_violations(tickets, dynamic_profile)
    if profile_violations:
        raise AiAnalysisError(f"AI 号码不符合其本期动态口径：{'；'.join(profile_violations)}")

    red_stats = {item["number"]: item for item in snapshot["red_statistics"]}
    blue_stats = {item["number"]: item for item in snapshot["blue_statistics"]}
    red_reasons = _reason_map(value.get("red_reasons"))
    blue_reasons = _reason_map(value.get("blue_reasons"))
    _validate_reason_language(red_reasons, field="红球")
    _validate_reason_language(blue_reasons, field="蓝球")
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

    result = {
        "summary": frozen_analysis["summary"],
        "selection_rules": frozen_analysis["selection_rules"],
        "dynamic_rules": frozen_analysis["dynamic_rules"],
        "dynamic_profile": dynamic_profile,
        "profile_evidence": frozen_analysis["profile_evidence"],
        "strategy_assessment": frozen_analysis["strategy_assessment"],
        "strategy": strategy,
        "bet_mode": bet_mode,
        "model_structure_rationale": model_structure_rationale,
        "structure_rationale": factual_structure_rationale(
            red,
            snapshot,
            bet_mode=bet_mode,
            dan=dan,
            tuo=tuo,
        ),
        "red": red,
        "blue": blue,
        "red_reasons": [explain(number, red_stats, red_reasons) for number in red],
        "blue_reasons": [explain(number, blue_stats, blue_reasons) for number in blue],
        "structure": structure,
        "ticket_structure": ticket_structure,
        "backtest_conclusion": frozen_analysis["backtest_conclusion"],
        "risk_note": frozen_analysis["risk_note"],
    }
    if bet_mode == "dantuo":
        result.update({"dan": dan, "tuo": tuo})
    return result


def build_messages(
    snapshot: dict,
    *,
    red_count: int,
    blue_count: int,
    shape_filter: bool,
    avoid_popular: bool,
    strategy: str = "balanced",
    bet_mode: str = "complex",
    dan_count: int = 0,
    tuo_count: int = 0,
) -> list[dict]:
    output_schema = {
        "summary": "不超过300字：基于所给数据的历史分析摘要",
        "strategy_assessment": "不超过300字：结合回测说明保留、弱化或否定页面所选策略方向",
        "selection_rules": "数组：3-5条、每条不超过100字的选号与覆盖取舍，不得暗示预测优势",
        "dynamic_rules": (
            "数组：自行选择0-5种机器规则且field不得重复。可选格式："
            "{field:'odd_count'|'small_count'|'sum',min整数,max整数,description字符串,evidence_ids数组}；"
            "{field:'zone_minimums',values:[整数,整数,整数],description字符串,evidence_ids数组}；"
            "{field:'max_consecutive_run',max整数,description字符串,evidence_ids数组}。"
            "每条 description 不超过100字，evidence_ids 必须至少含一个直接支持该 field 的 evidence_catalog id"
        ),
        "profile_evidence": "数组：7-10个{id必须来自evidence_catalog,reason不超过100字}对象，覆盖统计、走势、形态、回测及本次实际启用的规则",
        "backtest_conclusion": "不超过300字：比较回测值与随机期望，不夸大样本偏差",
        "risk_note": "不超过180字：说明每个合法组合概率相同且不保证中奖",
    }
    system = (
        "你是双色球历史研究助手。你只能使用用户消息里的真实 JSON 数据，不能补造开奖、频次、遗漏或回测结果。"
        "双色球是独立随机开奖，每个合法单式组合概率相同；历史标签只用于组合结构和覆盖分散，不能称为预测优势。"
        "先比较近期与长期统计、历史形态分布、最近20期走势及30/50期滚动回测，再自行归纳本期规则。"
        "页面所选策略只是一项待检验的研究方向；必须结合回测决定保留、弱化或否定，不能盲从。"
        "奇偶、大小、三区、和值和连号的历史统计都来自每期6个红球，因此动态规则必须针对每一组实际展开的6红组合，不能直接套在更大的红球池上。"
        "复式要同时考虑全部C(红球池,6)组合；胆拖只考虑胆码全选、再从拖码补足6红的合法组合。"
        "这是第一阶段，只生成分析报告和 dynamic_rules，严禁选号，严禁返回 red、dan、tuo、blue、逐号理由或任何候选号码。"
        "除玩法合法性外，服务端不会要求奇偶、大小、三区、和值或连号全部启用；你必须自行决定启用哪些规则类型。"
        "如果 constraints.shape_analysis_requested 为 false，可以返回空 dynamic_rules；否则至少选择一条有直接证据且可满足的规则。"
        "极端形态也是合法组合，未启用的规则类型不得在第二阶段被当作隐藏硬约束。"
        "profile_evidence 只能引用 evidence_catalog 中的 id，服务端会用原始数值复核；不要自行抄写或编造统计数值。"
        "禁止用该出、回补、延续、有望、看好或提高中奖概率等措辞暗示未来更容易开出；只能描述历史覆盖取舍。"
        "summary、strategy_assessment、selection_rules、dynamic_rules、profile_evidence、backtest_conclusion和risk_note必须完整返回。"
        "只输出合法 JSON，不要 Markdown，不要思维过程。"
    )
    constraints = {
        "red_count": red_count,
        "red_range": [1, RED_MAX],
        "blue_count": blue_count,
        "blue_range": [1, BLUE_MAX],
        "red_unique": True,
        "blue_unique": True,
        "bet_mode": bet_mode,
        "dan_count": dan_count,
        "tuo_count": tuo_count,
        "selected_strategy": strategy,
        "selected_strategy_policy": STRATEGY_POLICIES[strategy],
        "shape_analysis_requested": shape_filter,
        "structure_policy": "根据本次证据自行选择规则类型和阈值，不使用固定规则模板",
        "dynamic_rules_apply_to": "every_expanded_6_red_ticket",
        "expanded_red_ticket_count": red_ticket_count_for_mode(
            bet_mode=bet_mode,
            red_count=red_count,
            dan_count=dan_count,
            tuo_count=tuo_count,
        ),
        "available_dynamic_rule_fields": list(DYNAMIC_RULE_FIELDS),
        "avoid_popular_is_only_split_risk_hint": avoid_popular,
        "consecutive_numbers_are_allowed": True,
        "required_output_schema": output_schema,
    }
    user = {
        "stage": "analysis_profile",
        "task": "分析历史统计、走势、形态分布和滚动回测，核对所选策略并生成本期规则，不生成号码",
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
    strategy: str = "balanced",
    bet_mode: str = "complex",
    dan_count: int = 0,
    tuo_count: int = 0,
) -> list[dict]:
    output_schema = {
        "structure_rationale": "非空字符串：说明实际展开的每组6红组合如何满足已冻结的动态口径",
        "blue": f"数组：恰好{blue_count}个1-16不重复整数",
        "red_reasons": "数组：全部红球池中每个号码各一个{number整数,reason非空字符串}对象",
        "blue_reasons": "数组：blue中每个号码各一个{number整数,reason非空字符串}对象",
    }
    if bet_mode == "dantuo":
        output_schema.update({
            "dan": f"数组：恰好{dan_count}个1-33不重复胆码",
            "tuo": f"数组：恰好{tuo_count}个1-33不重复拖码，与dan不重复",
        })
    else:
        output_schema["red"] = f"数组：恰好{red_count}个1-33不重复整数"
    system = (
        "你是双色球历史研究助手。这是第二阶段，服务端已冻结第一阶段的分析和动态口径。"
        "你只能按 frozen_analysis.dynamic_rules 选号，不得返回、重申或修改 summary、strategy_assessment、selection_rules、dynamic_rules、dynamic_profile、profile_evidence、backtest_conclusion 或 risk_note。"
        "红蓝球理由只能使用给定的真实统计做定性取舍，不得补造数字，不得暗示提高中奖概率。"
        "只核对 server_validation_checklist 中实际启用的规则；未启用的形态字段不得被当作隐藏硬约束。"
        "冻结规则针对每一组实际展开的6红组合：复式检查全部C(红球池,6)，胆拖检查胆码全选并从拖码补足6红的全部组合；不能只检查整个红球池。"
        "胆拖必须明确区分胆码和拖码；胆码只是投注结构，不得声称其更可能开出。"
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
            "bet_mode": bet_mode,
            "dan_count": dan_count,
            "tuo_count": tuo_count,
            "dynamic_rules_apply_to": "every_expanded_6_red_ticket",
            "expanded_red_ticket_count": red_ticket_count_for_mode(
                bet_mode=bet_mode,
                red_count=red_count,
                dan_count=dan_count,
                tuo_count=tuo_count,
            ),
            "selected_strategy": strategy,
            "avoid_popular_is_only_split_risk_hint": avoid_popular,
            "required_output_schema": output_schema,
        },
        "frozen_analysis": frozen_analysis,
        "server_validation_checklist": frozen_analysis["dynamic_rules"],
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
        "max_tokens": 6000 if request_stage == "number_selection" else 4000,
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
                retry_instruction = (
                    "上次 JSON 因内容过长被截断。请严格遵守各字段字数上限，压缩说明并重新输出完整 JSON 对象。"
                    if "截断" in str(exc)
                    else "上次没有返回有效 JSON。请按原约束重新输出完整 JSON 对象。"
                )
                current_messages = current_messages + [
                    {
                        "role": "user",
                        "content": f"{stage_name}{retry_instruction}",
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
    strategy: str = "balanced",
    bet_mode: str = "complex",
    dan_count: int = 0,
    tuo_count: int = 0,
    requester: Callable[[list[dict]], dict] = call_deepseek,
) -> dict:
    if strategy not in STRATEGY_POLICIES:
        raise AiAnalysisError("AI 推荐策略类型无效")
    if bet_mode not in BET_MODES:
        raise AiAnalysisError("AI 投注方式无效")
    if not 1 <= blue_count <= 6:
        raise AiAnalysisError("AI 推荐蓝球数量应为 1-6 个")
    if bet_mode == "single":
        if red_count != 6 or blue_count != 1:
            raise AiAnalysisError("AI 单式必须为 6 个红球、1 个蓝球")
    elif bet_mode == "complex":
        if not 6 <= red_count <= 12:
            raise AiAnalysisError("AI 复式红球数量应为 6-12 个")
    else:
        if not 1 <= dan_count <= 5:
            raise AiAnalysisError("AI 胆码数量应为 1-5 个")
        if not max(4, 6 - dan_count) <= tuo_count <= 15:
            raise AiAnalysisError("AI 拖码数量不足或超出范围")
        red_count = dan_count + tuo_count
        if red_count > 20:
            raise AiAnalysisError("AI 胆拖红球池不能超过 20 个")

    snapshot = build_analysis_snapshot(rows, scope)
    analysis_messages = build_messages(
        snapshot,
        red_count=red_count,
        blue_count=blue_count,
        shape_filter=shape_filter,
        avoid_popular=avoid_popular,
        strategy=strategy,
        bet_mode=bet_mode,
        dan_count=dan_count,
        tuo_count=tuo_count,
    )
    frozen_analysis = _request_stage(
        requester,
        analysis_messages,
        lambda raw: validate_analysis_profile(
            raw,
            snapshot,
            red_count=red_count,
            shape_filter=shape_filter,
        ),
        stage_name="AI 分析阶段",
    )
    selection_messages = build_selection_messages(
        snapshot,
        frozen_analysis,
        red_count=red_count,
        blue_count=blue_count,
        avoid_popular=avoid_popular,
        strategy=strategy,
        bet_mode=bet_mode,
        dan_count=dan_count,
        tuo_count=tuo_count,
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
            bet_mode=bet_mode,
            strategy=strategy,
            dan_count=dan_count,
            tuo_count=tuo_count,
        ),
        stage_name="AI 选号阶段",
        max_attempts=3,
    )

    request_config = {
        "scope": scope,
        "strategy": strategy,
        "bet_mode": bet_mode,
        "red_count": red_count,
        "blue_count": blue_count,
        "dan_count": dan_count,
        "tuo_count": tuo_count,
        "shape_filter": shape_filter,
        "avoid_popular": avoid_popular,
    }
    return {
        "recommendation": recommendation,
        "research": {
            "data": snapshot["data"],
            "latest_draw": snapshot["latest_draw"],
            "trend": {key: value for key, value in snapshot["trend"].items() if key != "draws"},
            "shape_history": snapshot["shape_history"],
            "backtests": snapshot["backtests"],
        },
        "request": request_config,
        "pipeline": {
            "mode": "two_stage",
            "analysis_frozen_before_selection": True,
            "rules_selected_dynamically": True,
        },
        "model": os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": "历史统计、走势图和回测不能预测随机开奖；推荐只用于研究和组合结构参考。",
    }
