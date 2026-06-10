#!/usr/bin/env python3
"""Fetch SSQ draw history and write browser-friendly data files.

Usage:
  python3 fetch_history.py --start 2026001 --end 2026065
  python3 fetch_history.py --months 6
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
import json
import os
import re
import ssl
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


BASE = "https://cp.china-ssq.net/ssq"
ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("SSQ_PUBLIC_DATA_DIR", ROOT / "data"))

INSECURE_CONTEXT = ssl.create_default_context()
INSECURE_CONTEXT.check_hostname = False
INSECURE_CONTEXT.verify_mode = ssl.CERT_NONE


def fetch_text(url: str, timeout: int = 20) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(req, timeout=timeout) as response:
            return response.read().decode("utf-8", "ignore")
    except (ssl.SSLError, URLError) as exc:
        reason = getattr(exc, "reason", exc)
        if not isinstance(exc, ssl.SSLError) and not isinstance(reason, ssl.SSLError):
            raise
        with urlopen(req, timeout=timeout, context=INSECURE_CONTEXT) as response:
            return response.read().decode("utf-8", "ignore")


def detect_latest_issue() -> int:
    html = fetch_text(f"{BASE}/latest")
    issues = [int(x) for x in re.findall(r"/ssq/info/(\d{7})", html)]
    if not issues:
        text = strip_tags(html)
        issues = [int(x) for x in re.findall(r"\b(20\d{5})\b", text)]
    if not issues:
        raise RuntimeError("无法从最新开奖页识别最新期号，请手动传入 --end")
    return max(issues)


def strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text)


def extract_prize_row(text: str, prize_name: str, condition_pattern: str) -> dict[str, int] | None:
    match = re.search(rf"{prize_name}\s+{condition_pattern}\s+(\d+)\s+(\d+)", text)
    if not match:
        return None
    return {"winners": int(match.group(1)), "amount": int(match.group(2))}


def parse_issue(issue: int) -> dict[str, object]:
    html = fetch_text(f"{BASE}/info/{issue}")
    text = strip_tags(html)
    date_match = re.search(r"开奖日期：([0-9-]+)", text)
    nums_match = re.search(r"开奖日期：[0-9-]+.*?((?:\b\d{1,2}\b\s+){6}\b\d{1,2}\b)", text)
    if not date_match or not nums_match:
        raise ValueError(f"{issue} 页面解析失败")

    numbers = [int(x) for x in re.findall(r"\b\d{1,2}\b", nums_match.group(1))]
    if len(numbers) != 7:
        raise ValueError(f"{issue} 开奖号码数量异常: {numbers}")

    red = numbers[:6]
    blue = numbers[6]
    if sorted(red) != red or len(set(red)) != 6 or not all(1 <= n <= 33 for n in red) or not 1 <= blue <= 16:
        raise ValueError(f"{issue} 开奖号码范围异常: {numbers}")

    prize_rows = {}
    for prize_name, condition_pattern in (("一等奖", r"6\s*\+\s*1"), ("二等奖", r"6\s*\+\s*0")):
        row = extract_prize_row(text, prize_name, condition_pattern)
        if row:
            prize_rows[prize_name] = row

    sale_match = re.search(r"本期全国销量：\s*([0-9.]+)\s*亿", text)
    pool_match = re.search(r"奖池累积：\s*([0-9.]+)\s*亿", text)

    result = {"issue": str(issue), "date": date_match.group(1), "red": red, "blue": blue}
    if sale_match:
        result["sales_yi"] = float(sale_match.group(1))
    if pool_match:
        result["pool_yi"] = float(pool_match.group(1))
    if prize_rows:
        result["prize_rows"] = prize_rows
    return result


def read_existing_rows() -> dict[int, dict[str, object]]:
    path = DATA_DIR / "ssq-history.json"
    if not path.exists():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {int(row["issue"]): row for row in rows}


def write_data(rows: list[dict[str, object]]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    payload = json.dumps(rows, ensure_ascii=False, indent=2)
    (DATA_DIR / "ssq-history.json").write_text(payload + "\n", encoding="utf-8")
    (DATA_DIR / "ssq-history.js").write_text("window.SSQ_HISTORY = " + payload + ";\n", encoding="utf-8")


def cutoff_date(months: int) -> date:
    today = date.today()
    year = today.year
    month = today.month - months
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, min(today.day, 28))


def prev_year_last_issue(year: int) -> int | None:
    for seq in range(160, 100, -1):
        issue = year * 1000 + seq
        try:
            parse_issue(issue)
            return issue
        except Exception:
            continue
    return None


def prev_issue(issue: int) -> int | None:
    seq = issue % 1000
    year = issue // 1000
    if seq > 1:
        return issue - 1
    return prev_year_last_issue(year - 1)


def parse_issue_with_retry(issue: int, sleep: float, attempts: int = 3) -> dict[str, object]:
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            if sleep:
                time.sleep(sleep)
            return parse_issue(issue)
        except Exception as exc:
            last_exc = exc
            if attempt < attempts - 1:
                time.sleep(1)
    raise last_exc if last_exc else RuntimeError("unknown error")


def collect_recent_issues(months: int, latest: int, sleep: float) -> list[int]:
    limit = cutoff_date(months)
    issues: list[int] = []
    current: int | None = latest
    while current is not None:
        try:
            row = parse_issue_with_retry(current, sleep)
        except Exception as exc:
            print(f"skip {current}: {exc}", flush=True)
            current = prev_issue(current)
            continue
        draw_day = datetime.strptime(str(row["date"]), "%Y-%m-%d").date()
        if draw_day < limit:
            break
        issues.append(current)
        print(f"ok {current} {row['date']}", flush=True)
        current = prev_issue(current)
    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取双色球历史开奖数据")
    parser.add_argument("--start", type=int, default=2026001, help="起始期号，例如 2026001")
    parser.add_argument("--end", type=int, help="结束期号；不传则自动识别最新期号")
    parser.add_argument("--months", type=int, help="抓取最近 N 个月的滚动窗口；传入则忽略 --start/--end")
    parser.add_argument("--sleep", type=float, default=0.15, help="每期抓取间隔秒数")
    parser.add_argument("--workers", type=int, default=6, help="并发抓取线程数")
    args = parser.parse_args()

    if args.months:
        latest = args.end or detect_latest_issue()
        print(f"最近 {args.months} 个月滚动窗口，最新期号 {latest}", flush=True)
        issues = collect_recent_issues(args.months, latest, args.sleep)
        if not issues:
            raise SystemExit("滚动窗口内没有抓到任何开奖数据")
        start = min(issues)
        end = max(issues)
    else:
        end = args.end or detect_latest_issue()
        issues = list(range(args.start, end + 1))
        start = args.start

    def fetch_with_retry(issue: int) -> tuple[int, dict[str, object] | None, str | None]:
        for attempt in range(3):
            try:
                if args.sleep:
                    time.sleep(args.sleep)
                return issue, parse_issue(issue), None
            except Exception as exc:
                if attempt == 2:
                    return issue, None, str(exc)
                time.sleep(1)
        return issue, None, "unknown error"

    existing = read_existing_rows()
    rows_by_issue = dict(existing)
    failures = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [executor.submit(fetch_with_retry, issue) for issue in issues]
        for future in as_completed(futures):
            issue, row, error = future.result()
            if row:
                rows_by_issue[issue] = row
                print(f"ok {issue}", flush=True)
            elif issue in existing:
                print(f"keep {issue}: {error}", flush=True)
            else:
                failures.append((issue, error or "unknown error"))
                print(f"fail {issue}: {error}", flush=True)

    rows = [rows_by_issue[issue] for issue in sorted(rows_by_issue) if start <= issue <= end]

    if not rows:
        raise SystemExit("没有抓到任何开奖数据")
    if failures:
        raise SystemExit("部分新期号抓取失败，已保留旧数据但不会写入不完整结果")

    write_data(rows)
    print(f"wrote {len(rows)} rows to {DATA_DIR / 'ssq-history.js'}")


if __name__ == "__main__":
    main()
