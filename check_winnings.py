#!/usr/bin/env python3
"""Check recorded SSQ purchases and optionally push winning alerts via Bark."""

from __future__ import annotations

import argparse
import itertools
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
PUBLIC_DATA_DIR = Path(os.environ.get("SSQ_PUBLIC_DATA_DIR", ROOT / "data"))
PRIVATE_DATA_DIR = Path(os.environ.get("SSQ_PRIVATE_DATA_DIR", ROOT / "data"))
HISTORY_PATH = Path(os.environ.get("SSQ_HISTORY_PATH", PUBLIC_DATA_DIR / "ssq-history.json"))
PURCHASES_PATH = Path(os.environ.get("SSQ_PURCHASES_PATH", PRIVATE_DATA_DIR / "purchases.json"))
RESULTS_PATH = Path(os.environ.get("SSQ_RESULTS_PATH", PRIVATE_DATA_DIR / "check-results.json"))
DISPLAY_TZ = ZoneInfo(os.environ.get("TZ", "Asia/Shanghai"))

FIXED_PRIZES = {
    "三等奖": 3000,
    "四等奖": 200,
    "五等奖": 10,
    "六等奖": 5,
}


def read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_nums(nums):
    return sorted(int(n) for n in nums)


def expand_red_combos(purchase: dict) -> list[tuple[int, ...]]:
    if "dan" in purchase or "tuo" in purchase:
        dan = normalize_nums(purchase.get("dan", []))
        tuo = normalize_nums(purchase.get("tuo", []))
        need = 6 - len(dan)
        if need < 0:
            raise ValueError(f"{purchase['id']} 胆码超过 6 个")
        return [tuple(sorted(dan + list(combo))) for combo in itertools.combinations(tuo, need)]

    red = normalize_nums(purchase.get("red", []))
    return [tuple(combo) for combo in itertools.combinations(red, 6)]


def prize_name(red_hit: int, blue_hit: bool) -> str | None:
    if red_hit == 6 and blue_hit:
        return "一等奖"
    if red_hit == 6:
        return "二等奖"
    if red_hit == 5 and blue_hit:
        return "三等奖"
    if red_hit == 5 or (red_hit == 4 and blue_hit):
        return "四等奖"
    if red_hit == 4 or (red_hit == 3 and blue_hit):
        return "五等奖"
    if blue_hit:
        return "六等奖"
    return None


def prize_amount(draw: dict, prize_name: str) -> int:
    prize_rows = draw.get("prize_rows") or {}
    row = prize_rows.get(prize_name) if isinstance(prize_rows, dict) else None
    if not isinstance(row, dict):
        return 0
    amount = row.get("amount", 0)
    return int(amount) if str(amount).isdigit() else 0


def needs_refresh(existing_result: dict, draw: dict) -> bool:
    if "floating_amount" not in existing_result or "total_amount" not in existing_result:
        return True
    if not draw.get("prize_rows"):
        return False
    counts = existing_result.get("counts") or {}
    expected_floating = (
        int(counts.get("一等奖", 0)) * prize_amount(draw, "一等奖")
        + int(counts.get("二等奖", 0)) * prize_amount(draw, "二等奖")
    )
    existing_floating = int(existing_result.get("floating_amount") or 0)
    existing_total = int(existing_result.get("total_amount") or 0)
    fixed_amount = int(existing_result.get("fixed_amount") or 0)
    return existing_floating != expected_floating or existing_total != fixed_amount + expected_floating


def check_purchase(purchase: dict, draw: dict) -> dict:
    red_draw = set(normalize_nums(draw["red"]))
    blue_draw = int(draw["blue"])
    blue_nums = normalize_nums(purchase.get("blue", []))
    red_combos = expand_red_combos(purchase)
    counts = {"一等奖": 0, "二等奖": 0, "三等奖": 0, "四等奖": 0, "五等奖": 0, "六等奖": 0}

    for red_combo in red_combos:
        red_hit = len(set(red_combo) & red_draw)
        for blue in blue_nums:
            prize = prize_name(red_hit, blue == blue_draw)
            if prize:
                counts[prize] += 1

    fixed_amount = sum(counts[name] * amount for name, amount in FIXED_PRIZES.items())
    floating_amount = (
        counts["一等奖"] * prize_amount(draw, "一等奖")
        + counts["二等奖"] * prize_amount(draw, "二等奖")
    )
    return {
        "purchase_id": purchase["id"],
        "issue": str(purchase["issue"]),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "draw": {"red": normalize_nums(draw["red"]), "blue": blue_draw},
        "counts": counts,
        "fixed_amount": fixed_amount,
        "floating_amount": floating_amount,
        "total_amount": fixed_amount + floating_amount,
        "won": any(counts.values()),
        "note": purchase.get("note", ""),
    }


def format_local_time(value: str) -> str:
    text = str(value).strip()
    if not text:
        return datetime.now(DISPLAY_TZ).strftime("%Y-%m-%d %H:%M:%S")
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(DISPLAY_TZ).strftime("%Y-%m-%d %H:%M:%S")


def format_num_line(label: str, values: list[int]) -> str:
    nums = " ".join(f"{int(n):02d}" for n in values)
    return f"{label}{nums}"


def format_alert(result: dict) -> tuple[str, str]:
    title = f"双色球{'中奖' if result['won'] else '未中奖'}提醒 {result['issue']}"
    counts = result["counts"]
    hits = "，".join(f"{name}{count}注" for name, count in counts.items() if count) or "未中奖"
    fixed_amount = int(result["fixed_amount"])
    floating_amount = int(result.get("floating_amount") or 0)
    total_amount = int(result.get("total_amount") or fixed_amount + floating_amount)
    amount_line = f"奖金：总约 {total_amount} 元（固定 {fixed_amount} + 浮动 {floating_amount}）"
    if not floating_amount:
        amount_line = f"奖金：固定约 {fixed_amount} 元"
    lines = [
        f"时间：{format_local_time(result.get('checked_at', ''))}",
        f"结果：{hits}",
        amount_line,
        format_num_line("🔴红球：", result["draw"]["red"]),
        format_num_line("🔵蓝球：", [result["draw"]["blue"]]),
    ]
    note = str(result.get("note", "")).strip()
    if note:
        lines.append(f"备注：{note}")
    body = "\n".join(lines)
    return title, body


def push_bark(result: dict, dry_run: bool) -> None:
    bark_key = os.environ.get("BARK_KEY", "").strip()
    sound = os.environ.get("BARK_SOUND", "minuet").strip() or "minuet"
    title, body = format_alert(result)

    if dry_run or not bark_key:
        print(f"bark skipped: {title} | {body}")
        return

    url = f"https://api.day.app/{quote(bark_key)}/{quote(title)}/{quote(body)}?sound={quote(sound)}"
    with urlopen(url, timeout=20) as response:
        print(response.read().decode("utf-8", "ignore"))


def main() -> None:
    parser = argparse.ArgumentParser(description="核验已购彩票是否中奖，并通过 Bark 推送")
    parser.add_argument("--dry-run", action="store_true", help="只输出，不发送 Bark")
    args = parser.parse_args()

    history = {str(row["issue"]): row for row in read_json(HISTORY_PATH, [])}
    purchases = read_json(PURCHASES_PATH, [])
    results = read_json(RESULTS_PATH, [])
    result_index = {(item["purchase_id"], str(item["issue"])): idx for idx, item in enumerate(results)}
    new_results = []
    updated_results = []

    for purchase in purchases:
        purchase_id = purchase["id"]
        issue = str(purchase["issue"])
        if issue not in history:
            print(f"skip {purchase_id}: issue {issue} not drawn yet")
            continue

        key = (purchase_id, issue)
        existing_idx = result_index.get(key)
        if existing_idx is not None and not needs_refresh(results[existing_idx], history[issue]):
            continue

        result = check_purchase(purchase, history[issue])
        if existing_idx is None:
            results.append(result)
            result_index[key] = len(results) - 1
            new_results.append(result)
            print(f"checked {purchase_id}: won={result['won']} total_amount={result['total_amount']}")
            push_bark(result, args.dry_run)
        else:
            results[existing_idx] = result
            updated_results.append(result)
            print(f"refreshed {purchase_id}: won={result['won']} total_amount={result['total_amount']}")

    write_json(RESULTS_PATH, results)
    print(f"new results: {len(new_results)}")
    print(f"updated results: {len(updated_results)}")


if __name__ == "__main__":
    main()
