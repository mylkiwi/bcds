#!/usr/bin/env python3
"""Fetch SSQ draw history and write browser-friendly data files.

Usage:
  python3 fetch_history.py --start 2026001 --end 2026064
  python3 fetch_history.py --start 2026001
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
import ssl
import time
from pathlib import Path
from urllib.request import Request, urlopen


BASE = "https://cp.china-ssq.net/ssq"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SSL_CONTEXT = ssl._create_unverified_context()


def fetch_text(url: str, timeout: int = 20) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=timeout, context=SSL_CONTEXT) as response:
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

    return {"issue": str(issue), "date": date_match.group(1), "red": red, "blue": blue}


def write_data(rows: list[dict[str, object]]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    payload = json.dumps(rows, ensure_ascii=False, indent=2)
    (DATA_DIR / "ssq-history.json").write_text(payload + "\n", encoding="utf-8")
    (DATA_DIR / "ssq-history.js").write_text("window.SSQ_HISTORY = " + payload + ";\n", encoding="utf-8")


def read_existing_rows() -> dict[int, dict[str, object]]:
    path = DATA_DIR / "ssq-history.json"
    if not path.exists():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {int(row["issue"]): row for row in rows}


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取双色球历史开奖数据")
    parser.add_argument("--start", type=int, default=2026001, help="起始期号，例如 2026001")
    parser.add_argument("--end", type=int, help="结束期号；不传则自动识别最新期号")
    parser.add_argument("--sleep", type=float, default=0.15, help="每期抓取间隔秒数")
    parser.add_argument("--workers", type=int, default=6, help="并发抓取线程数")
    args = parser.parse_args()

    end = args.end or detect_latest_issue()
    issues = list(range(args.start, end + 1))

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

    rows = [rows_by_issue[issue] for issue in sorted(rows_by_issue) if args.start <= issue <= end]

    if not rows:
        raise SystemExit("没有抓到任何开奖数据")
    if failures:
        raise SystemExit("部分新期号抓取失败，已保留旧数据但不会写入不完整结果")

    write_data(rows)
    print(f"wrote {len(rows)} rows to {DATA_DIR / 'ssq-history.js'}")
    if failures:
        print("部分期号失败：")
        for issue, message in failures:
            print(f"  {issue}: {message}")


if __name__ == "__main__":
    main()
