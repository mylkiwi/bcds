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


ROOT = Path(__file__).resolve().parent
PUBLIC_DATA_DIR = Path(os.environ.get("SSQ_PUBLIC_DATA_DIR", ROOT / "data"))
PRIVATE_DATA_DIR = Path(os.environ.get("SSQ_PRIVATE_DATA_DIR", ROOT / "data"))
HISTORY_PATH = Path(os.environ.get("SSQ_HISTORY_PATH", PUBLIC_DATA_DIR / "ssq-history.json"))
PURCHASES_PATH = Path(os.environ.get("SSQ_PURCHASES_PATH", PRIVATE_DATA_DIR / "purchases.json"))
RESULTS_PATH = Path(os.environ.get("SSQ_RESULTS_PATH", PRIVATE_DATA_DIR / "check-results.json"))

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


def check_purchase(purchase: dict, draw: dict) -> dict:
    red_draw = set(normalize_nums(draw["red"]))
    blue_draw = int(draw["blue"])
    blue_nums = normalize_nums(purchase.get("blue", []))
    red_combos = expand_red_combos(purchase)
    counts = {"一等奖": 0, "二等奖": 0, "三等奖": 0, "四等奖": 0, "五等奖": 0, "六等奖": 0}
    best = None

    for red_combo in red_combos:
        red_hit = len(set(red_combo) & red_draw)
        for blue in blue_nums:
            prize = prize_name(red_hit, blue == blue_draw)
            if prize:
                counts[prize] += 1
                best = best or prize

    amount = sum(counts[name] * amount for name, amount in FIXED_PRIZES.items())
    return {
        "purchase_id": purchase["id"],
        "issue": str(purchase["issue"]),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "draw": {"red": normalize_nums(draw["red"]), "blue": blue_draw},
        "counts": counts,
        "fixed_amount": amount,
        "won": any(counts.values()),
        "note": purchase.get("note", ""),
    }


def format_alert(result: dict) -> tuple[str, str]:
    title = f"双色球中奖提醒 {result['issue']}"
    counts = result["counts"]
    hits = "，".join(f"{name}{count}注" for name, count in counts.items() if count)
    amount = result["fixed_amount"]
    red = " ".join(f"{n:02d}" for n in result["draw"]["red"])
    blue = f"{result['draw']['blue']:02d}"
    body = f"{result['purchase_id']}：{hits}。固定奖金约 {amount} 元。开奖号：{red} + {blue}"
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
    checked = {(item["purchase_id"], str(item["issue"])) for item in results}
    new_results = []

    for purchase in purchases:
        purchase_id = purchase["id"]
        issue = str(purchase["issue"])
        if (purchase_id, issue) in checked:
            continue
        if issue not in history:
            print(f"skip {purchase_id}: issue {issue} not drawn yet")
            continue

        result = check_purchase(purchase, history[issue])
        results.append(result)
        new_results.append(result)
        print(f"checked {purchase_id}: won={result['won']} amount={result['fixed_amount']}")
        if result["won"]:
            push_bark(result, args.dry_run)

    write_json(RESULTS_PATH, results)
    print(f"new results: {len(new_results)}")


if __name__ == "__main__":
    main()
