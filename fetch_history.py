#!/usr/bin/env python3
"""Fetch SSQ draw history and write browser-friendly data files.

Usage:
  python3 fetch_history.py --start 2026001 --end 2026064
  python3 fetch_history.py --start 2026001
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
import json
import re
import ssl
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


BASE = "https://cp.china-ssq.net/ssq"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

# 容忍证书校验失败（如宿主机时钟偏差导致证书"已过期"）时降级为不校验。
# 该站点是公开开奖数据、无登录无敏感信息上行，降级仅影响传输校验。
_INSECURE_CTX = ssl.create_default_context()
_INSECURE_CTX.check_hostname = False
_INSECURE_CTX.verify_mode = ssl.CERT_NONE


def fetch_text(url: str, timeout: int = 20) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(req, timeout=timeout) as response:
            return response.read().decode("utf-8", "ignore")
    except (ssl.SSLError, URLError) as exc:
        # URLError 可能包裹了 SSLError（如证书过期）；只在 SSL 相关时降级重试。
        reason = getattr(exc, "reason", exc)
        if not isinstance(exc, ssl.SSLError) and not isinstance(reason, ssl.SSLError):
            raise
        with urlopen(req, timeout=timeout, context=_INSECURE_CTX) as response:
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


def cutoff_date(months: int) -> date:
    """Return today minus N months (approximate, calendar-aware)."""
    today = date.today()
    year = today.year
    month = today.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = min(today.day, 28)  # avoid invalid dates like Feb 30
    return date(year, month, day)


def prev_year_last_issue(year: int) -> int | None:
    """Probe for the last issue number of the previous year by trying YYYY160 downward."""
    for seq in range(160, 100, -1):
        issue = year * 1000 + seq
        try:
            parse_issue(issue)
            return issue
        except Exception:
            continue
    return None


def prev_issue(issue: int) -> int | None:
    """Return the issue right before `issue`, handling year rollover (e.g. 2026001 -> 2025xxx)."""
    seq = issue % 1000
    year = issue // 1000
    if seq > 1:
        return issue - 1
    return prev_year_last_issue(year - 1)


def parse_issue_with_retry(issue: int, sleep: float, attempts: int = 3) -> dict[str, object]:
    """parse_issue with retries to tolerate transient network/SSL timeouts."""
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
    """Walk backward from `latest` until a draw older than the cutoff date is reached."""
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
    else:
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

    rows = []
    failures = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [executor.submit(fetch_with_retry, issue) for issue in issues]
        for future in as_completed(futures):
            issue, row, error = future.result()
            if row:
                rows.append(row)
                print(f"ok {issue}", flush=True)
            else:
                failures.append((issue, error or "unknown error"))
                print(f"fail {issue}: {error}", flush=True)

    if not rows:
        raise SystemExit("没有抓到任何开奖数据")

    rows.sort(key=lambda item: int(item["issue"]))
    write_data(rows)
    print(f"wrote {len(rows)} rows to {DATA_DIR / 'ssq-history.js'}")
    if failures:
        print("部分期号失败：")
        for issue, message in failures:
            print(f"  {issue}: {message}")


if __name__ == "__main__":
    main()
