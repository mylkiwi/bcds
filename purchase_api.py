#!/usr/bin/env python3
"""Small HTTP API for recording SSQ purchases on the server."""

from __future__ import annotations

from contextlib import closing
import hashlib
import ipaddress
import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from ai_analysis import AiAnalysisError, DEFAULT_MODEL, generate_ai_recommendation


ROOT = Path(__file__).resolve().parent
PUBLIC_DATA_DIR = Path(os.environ.get("SSQ_PUBLIC_DATA_DIR", ROOT / "data"))
PRIVATE_DATA_DIR = Path(os.environ.get("SSQ_PRIVATE_DATA_DIR", ROOT / "data"))
HISTORY_PATH = Path(os.environ.get("SSQ_HISTORY_PATH", PUBLIC_DATA_DIR / "ssq-history.json"))
PURCHASES_PATH = Path(os.environ.get("SSQ_PURCHASES_PATH", PRIVATE_DATA_DIR / "purchases.json"))
RESULTS_PATH = Path(os.environ.get("SSQ_RESULTS_PATH", PRIVATE_DATA_DIR / "check-results.json"))
AI_DATABASE_PATH = Path(os.environ.get("SSQ_AI_DATABASE_PATH", PRIVATE_DATA_DIR / "ssq.sqlite3"))
DISPLAY_TZ = ZoneInfo(os.environ.get("TZ", "Asia/Shanghai"))
AI_REQUEST_LOCK = threading.BoundedSemaphore(1)
AI_USAGE_LOCK = threading.Lock()
AI_REQUEST_TIMES: list[float] = []
AI_JOB_LOCK = threading.Lock()
AI_DATABASE_LOCK = threading.Lock()
AI_JOBS: dict[str, dict] = {}
AI_JOB_TTL_SECONDS = 3600
AI_JOB_MAX_TERMINAL = 100
PURCHASE_SESSION_COOKIE = "__Host-ssq_purchase"
PURCHASE_SESSION_TTL = 30 * 86400
LOGIN_ATTEMPT_LOCK = threading.Lock()
LOGIN_FAILURE_TIMES: list[float] = []
LOGIN_MAX_FAILURES = 10
LOGIN_WINDOW_SECONDS = 300


def _secret_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_purchase_session(admin_token: str, previous: str = "") -> str:
    value = secrets.token_urlsafe(32)
    now = time.time()
    with AI_DATABASE_LOCK, closing(_open_ai_database()) as db, db:
        db.execute("DELETE FROM purchase_sessions WHERE expires_at <= ? OR admin_hash != ? OR session_hash = ?",
                   (now, _secret_hash(admin_token), _secret_hash(previous)))
        # Bound the session table; this is a single-owner application.
        db.execute("DELETE FROM purchase_sessions WHERE session_hash IN "
                   "(SELECT session_hash FROM purchase_sessions ORDER BY expires_at DESC LIMIT -1 OFFSET 255)")
        db.execute("INSERT INTO purchase_sessions VALUES (?, ?, ?)",
                   (_secret_hash(value), _secret_hash(admin_token), now + PURCHASE_SESSION_TTL))
    return value


def valid_purchase_session(value: str, admin_token: str) -> bool:
    if not value or not admin_token:
        return False
    with AI_DATABASE_LOCK, closing(_open_ai_database()) as db:
        row = db.execute("SELECT admin_hash, expires_at FROM purchase_sessions WHERE session_hash = ?",
                         (_secret_hash(value),)).fetchone()
    return bool(row and row["expires_at"] > time.time()
                and secrets.compare_digest(row["admin_hash"], _secret_hash(admin_token)))


def revoke_purchase_session(value: str) -> None:
    if value:
        with AI_DATABASE_LOCK, closing(_open_ai_database()) as db, db:
            db.execute("DELETE FROM purchase_sessions WHERE session_hash = ?", (_secret_hash(value),))



def reserve_ai_quota() -> tuple[bool, str]:
    now = time.time()
    daily_limit = max(1, int(os.environ.get("DEEPSEEK_DAILY_LIMIT", "50")))
    min_interval = max(0.0, float(os.environ.get("DEEPSEEK_MIN_INTERVAL", "2")))
    with AI_USAGE_LOCK:
        AI_REQUEST_TIMES[:] = [value for value in AI_REQUEST_TIMES if value >= now - 86400]
        if AI_REQUEST_TIMES and now - AI_REQUEST_TIMES[-1] < min_interval:
            return False, "AI 请求过于频繁，请稍后再试"
        if len(AI_REQUEST_TIMES) >= daily_limit:
            return False, "AI 今日调用额度已用完"
        AI_REQUEST_TIMES.append(now)
    return True, ""


def _payload_bool(value, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if type(value) is int and value in {0, 1}:
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in {"true", "1", "yes", "on"}:
        return True
    if isinstance(value, str) and value.strip().lower() in {"false", "0", "no", "off"}:
        return False
    raise ValueError("AI 布尔参数格式错误")


def ai_request_options(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("AI 请求格式错误")
    strategy = str(payload.get("strategy", "balanced")).strip()
    if strategy not in {"official", "fair", "balanced", "hot", "omission", "cold", "mixed", "random"}:
        raise ValueError("AI 策略类型无效")
    bet_mode = str(payload.get("bet_mode", "complex")).strip()
    if bet_mode not in {"single", "complex", "dantuo"}:
        raise ValueError("AI 投注方式无效")

    blue_count = int(payload.get("blue_count", 1 if bet_mode == "single" else 2))
    red_count = int(payload.get("red_count", 6 if bet_mode == "single" else 7))
    dan_count = int(payload.get("dan_count", 0))
    tuo_count = int(payload.get("tuo_count", 0))
    if bet_mode == "single":
        red_count, blue_count, dan_count, tuo_count = 6, 1, 0, 0
    elif bet_mode == "complex":
        if not 6 <= red_count <= 12 or not 1 <= blue_count <= 6:
            raise ValueError("复式应选择 6-12 个红球、1-6 个蓝球")
        dan_count = tuo_count = 0
    else:
        if not 1 <= dan_count <= 5:
            raise ValueError("胆码数量应为 1-5 个")
        if not max(4, 6 - dan_count) <= tuo_count <= 15:
            raise ValueError("拖码数量不足或超出范围")
        if dan_count + tuo_count > 20:
            raise ValueError("胆拖红球池不能超过 20 个")
        if not 1 <= blue_count <= 6:
            raise ValueError("蓝球数量应为 1-6 个")
        red_count = dan_count + tuo_count

    return {
        "scope": payload.get("scope", "all"),
        "strategy": strategy,
        "bet_mode": bet_mode,
        "red_count": red_count,
        "blue_count": blue_count,
        "dan_count": dan_count,
        "tuo_count": tuo_count,
        "shape_filter": _payload_bool(payload.get("shape_filter"), default=True),
        "avoid_popular": _payload_bool(payload.get("avoid_popular"), default=True),
    }


def ai_client_request_id(payload: dict) -> str:
    value = str(payload.get("client_request_id", "")).strip()
    if value and not re.fullmatch(r"[-_A-Za-z0-9]{16,64}", value):
        raise ValueError("client_request_id 格式错误")
    return value


def _ai_job_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cleanup_ai_jobs_locked(now: float) -> None:
    expired = [
        job_id
        for job_id, job in AI_JOBS.items()
        if job["status"] != "running" and now - job["updated_epoch"] >= AI_JOB_TTL_SECONDS
    ]
    for job_id in expired:
        AI_JOBS.pop(job_id, None)
    terminal = sorted(
        (
            (job["updated_epoch"], job_id)
            for job_id, job in AI_JOBS.items()
            if job["status"] != "running"
        ),
        reverse=True,
    )
    for _, job_id in terminal[AI_JOB_MAX_TERMINAL:]:
        AI_JOBS.pop(job_id, None)


def get_ai_job(job_id: str) -> dict | None:
    with AI_JOB_LOCK:
        _cleanup_ai_jobs_locked(time.time())
        job = AI_JOBS.get(job_id)
        if not job:
            return None
        payload = {
            "task_id": job_id,
            "status": job["status"],
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
            "request": job.get("request", {}),
        }
        if job["status"] == "succeeded":
            payload["result"] = job["result"]
        elif job["status"] == "failed":
            payload["error"] = job["error"]
        return payload


def find_ai_job_by_client_request_id(client_request_id: str) -> dict | None:
    if not client_request_id:
        return None
    with AI_JOB_LOCK:
        _cleanup_ai_jobs_locked(time.time())
        for job_id, job in AI_JOBS.items():
            if job.get("client_request_id") == client_request_id:
                return {"task_id": job_id}
    return None


def _finish_ai_job(job_id: str, *, result: dict | None = None, error: dict | None = None) -> None:
    now = time.time()
    with AI_JOB_LOCK:
        job = AI_JOBS.get(job_id)
        if not job:
            return
        job["status"] = "failed" if error else "succeeded"
        job["updated_at"] = _ai_job_timestamp()
        job["updated_epoch"] = now
        if error:
            job["error"] = error
        else:
            job["result"] = result


def _run_ai_job(job_id: str, options: dict, client_request_id: str, generator) -> None:
    try:
        result = generator(read_json(HISTORY_PATH, []), **options)
        result = dict(result)
        result["report_id"] = job_id
        save_ai_recommendation(
            job_id,
            task_id=job_id,
            client_request_id=client_request_id,
            options=options,
            result=result,
        )
        _finish_ai_job(job_id, result=result)
    except AiAnalysisError as exc:
        _finish_ai_job(job_id, error={"code": "ai_analysis_failed", "message": str(exc)})
    except Exception:
        traceback.print_exc()
        _finish_ai_job(
            job_id,
            error={"code": "internal_error", "message": "AI 分析发生内部错误"},
        )
    finally:
        AI_REQUEST_LOCK.release()


def start_ai_job(options: dict, *, client_request_id: str = "", generator=None) -> str:
    job_id = secrets.token_urlsafe(18)
    timestamp = _ai_job_timestamp()
    with AI_JOB_LOCK:
        _cleanup_ai_jobs_locked(time.time())
        AI_JOBS[job_id] = {
            "status": "running",
            "created_at": timestamp,
            "updated_at": timestamp,
            "updated_epoch": time.time(),
            "client_request_id": client_request_id,
            "request": dict(options),
        }
    worker = threading.Thread(
        target=_run_ai_job,
        args=(job_id, options, client_request_id, generator or generate_ai_recommendation),
        name=f"ssq-ai-{job_id[:8]}",
        daemon=True,
    )
    try:
        worker.start()
    except Exception:
        with AI_JOB_LOCK:
            AI_JOBS.pop(job_id, None)
        raise
    return job_id


def read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _open_ai_database() -> sqlite3.Connection:
    AI_DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(AI_DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_recommendations (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL UNIQUE,
            client_request_id TEXT,
            latest_issue TEXT,
            strategy TEXT NOT NULL,
            bet_mode TEXT NOT NULL,
            request_json TEXT NOT NULL,
            result_json TEXT NOT NULL,
            model TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_recommendations_created_at ON ai_recommendations(created_at DESC)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS purchase_sessions ("
        "session_hash TEXT PRIMARY KEY, admin_hash TEXT NOT NULL, expires_at REAL NOT NULL)"
    )
    return connection


def save_ai_recommendation(
    report_id: str,
    *,
    task_id: str,
    client_request_id: str,
    options: dict,
    result: dict,
) -> dict:
    recommendation = (result.get("recommendation") or {}) if isinstance(result, dict) else {}
    research_data = result.get("research", {}).get("data", {}) if isinstance(result, dict) else {}
    created_at = str(result.get("generated_at") or _ai_job_timestamp())
    record = {
        "id": report_id,
        "task_id": task_id,
        "latest_issue": str(research_data.get("latest_issue", "")),
        "strategy": str(options.get("strategy", recommendation.get("strategy", "balanced"))),
        "bet_mode": str(options.get("bet_mode", recommendation.get("bet_mode", "complex"))),
        "request": options,
        "result": result,
        "model": str(result.get("model", "")),
        "created_at": created_at,
    }
    with AI_DATABASE_LOCK:
        with closing(_open_ai_database()) as connection:
            connection.execute(
                """
                INSERT INTO ai_recommendations (
                    id, task_id, client_request_id, latest_issue, strategy, bet_mode,
                    request_json, result_json, model, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    latest_issue=excluded.latest_issue,
                    strategy=excluded.strategy,
                    bet_mode=excluded.bet_mode,
                    request_json=excluded.request_json,
                    result_json=excluded.result_json,
                    model=excluded.model,
                    created_at=excluded.created_at
                """,
                (
                    report_id,
                    task_id,
                    client_request_id or None,
                    record["latest_issue"],
                    record["strategy"],
                    record["bet_mode"],
                    json.dumps(options, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                    record["model"],
                    created_at,
                ),
            )
            connection.commit()
    return record


def _ai_record_from_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "latest_issue": row["latest_issue"] or "",
        "strategy": row["strategy"],
        "bet_mode": row["bet_mode"],
        "request": json.loads(row["request_json"]),
        "result": json.loads(row["result_json"]),
        "model": row["model"] or "",
        "created_at": row["created_at"],
    }


def get_ai_recommendation(report_id: str | None = None) -> dict | None:
    with AI_DATABASE_LOCK:
        with closing(_open_ai_database()) as connection:
            if report_id:
                row = connection.execute(
                    "SELECT * FROM ai_recommendations WHERE id = ?",
                    (report_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM ai_recommendations ORDER BY created_at DESC, rowid DESC LIMIT 1"
                ).fetchone()
    return _ai_record_from_row(row) if row else None


def list_ai_recommendations(limit: int = 20) -> list[dict]:
    limit = max(1, min(int(limit), 50))
    with AI_DATABASE_LOCK:
        with closing(_open_ai_database()) as connection:
            rows = connection.execute(
                "SELECT * FROM ai_recommendations ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
    items = []
    for row in rows:
        record = _ai_record_from_row(row)
        recommendation = record["result"].get("recommendation", {})
        items.append({
            "id": record["id"],
            "latest_issue": record["latest_issue"],
            "strategy": record["strategy"],
            "bet_mode": record["bet_mode"],
            "request": record["request"],
            "model": record["model"],
            "created_at": record["created_at"],
            "recommendation": {
                "summary": recommendation.get("summary", ""),
                "red": recommendation.get("red", []),
                "dan": recommendation.get("dan", []),
                "tuo": recommendation.get("tuo", []),
                "blue": recommendation.get("blue", []),
            },
        })
    return items


def delete_ai_recommendation(report_id: str) -> bool:
    with AI_DATABASE_LOCK:
        with closing(_open_ai_database()) as connection:
            cursor = connection.execute("DELETE FROM ai_recommendations WHERE id = ?", (report_id,))
            connection.commit()
    return cursor.rowcount > 0


def normalize_nums(value, *, min_value: int, max_value: int, field: str) -> list[int]:
    if isinstance(value, str):
        raw = re.findall(r"\d+", value)
    elif isinstance(value, list):
        raw = value
    else:
        raise ValueError(f"{field} 格式错误")
    nums = sorted(int(n) for n in raw)
    if len(nums) != len(set(nums)):
        raise ValueError(f"{field} 不能有重复号码")
    if any(n < min_value or n > max_value for n in nums):
        raise ValueError(f"{field} 号码范围应为 {min_value}-{max_value}")
    return nums


def validate_purchase(payload: dict) -> dict:
    issue = str(payload.get("issue", "")).strip()
    if not re.fullmatch(r"20\d{5}", issue):
        raise ValueError("期号格式应为 7 位，例如 2026066")

    purchase_type = str(payload.get("type", "")).strip() or "complex"
    blue = normalize_nums(payload.get("blue", []), min_value=1, max_value=16, field="蓝球")
    if not 1 <= len(blue) <= 16:
        raise ValueError("蓝球至少 1 个")

    now = datetime.now(timezone.utc).isoformat()
    purchase_id = str(payload.get("id", "")).strip()
    if not purchase_id:
        purchase_id = f"{issue}-{int(time.time() * 1000)}"
    if not re.fullmatch(r"[-_a-zA-Z0-9.]+", purchase_id):
        raise ValueError("记录 ID 只能包含字母、数字、横线、下划线和点")

    result = {
        "id": purchase_id,
        "issue": issue,
        "blue": blue,
        "note": str(payload.get("note", "")).strip(),
        "created_at": str(payload.get("created_at") or now),
        "updated_at": now,
    }

    if purchase_type == "dantuo" or "dan" in payload or "tuo" in payload:
        dan = normalize_nums(payload.get("dan", []), min_value=1, max_value=33, field="胆码")
        tuo = normalize_nums(payload.get("tuo", []), min_value=1, max_value=33, field="拖码")
        if not 1 <= len(dan) <= 5:
            raise ValueError("胆码数量应为 1-5 个")
        if set(dan) & set(tuo):
            raise ValueError("胆码和拖码不能重复")
        if len(tuo) < 6 - len(dan):
            raise ValueError("拖码数量不足，无法补足 6 个红球")
        result.update({"type": "dantuo", "dan": dan, "tuo": tuo})
        return result

    red = normalize_nums(payload.get("red", []), min_value=1, max_value=33, field="红球")
    if not 6 <= len(red) <= 20:
        raise ValueError("红球数量应为 6-20 个")
    result.update({"type": "single" if len(red) == 6 and len(blue) == 1 else "complex", "red": red})
    return result


def latest_draw() -> dict | None:
    rows = read_json(HISTORY_PATH, [])
    if not rows:
        return None
    return rows[-1]


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


def build_purchase_body(item: dict) -> str:
    purchase_type = {"single": "单式", "complex": "复式", "dantuo": "胆拖"}.get(item.get("type"), "复式")
    lines = [
        f"时间：{format_local_time(item.get('created_at', ''))}",
        f"类型：{purchase_type}",
    ]
    if item.get("type") == "dantuo":
        lines.append(format_num_line("红球胆码：", item.get("dan", [])))
        lines.append(format_num_line("红球拖码：", item.get("tuo", [])))
    else:
        lines.append(format_num_line("红球：", item.get("red", [])))
    lines.append(format_num_line("蓝球：", item.get("blue", [])))
    note = str(item.get("note", "")).strip()
    if note:
        lines.append(f"{note}")
    return "\n".join(lines)


def push_purchase_bark(item: dict) -> dict:
    bark_key = os.environ.get("BARK_KEY", "").strip()
    sound = os.environ.get("BARK_SOUND", "minuet").strip() or "minuet"
    title = f"新增购买 {item['issue']}"
    body = build_purchase_body(item)

    if not bark_key:
        return {"sent": False, "message": "未配置 BARK_KEY，已跳过推送"}

    url = f"https://api.day.app/{quote(bark_key)}/{quote(title)}/{quote(body)}?sound={quote(sound)}"
    try:
        with urlopen(url, timeout=20) as response:
            payload = response.read().decode("utf-8", "ignore")
        try:
            parsed = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            parsed = {}
        message = parsed.get("message") if isinstance(parsed, dict) else ""
        return {"sent": True, "message": message or "购买记录已推送"}
    except Exception as exc:
        return {"sent": False, "message": f"Bark 推送失败：{exc}"}


def run_check() -> dict:
    env = os.environ.copy()
    process = subprocess.run(
        [sys.executable, str(ROOT / "check_winnings.py")],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    return {
        "ok": process.returncode == 0,
        "returncode": process.returncode,
        "stdout": process.stdout.strip(),
        "stderr": process.stderr.strip(),
    }


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "SSQPurchaseAPI/1.0"

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_common_headers()
        self.end_headers()

    def do_GET(self) -> None:
        self.handle_request("GET")

    def do_POST(self) -> None:
        self.handle_request("POST")

    def do_DELETE(self) -> None:
        self.handle_request("DELETE")

    def handle_request(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        try:
            if method == "GET" and not path.startswith("/api"):
                self.serve_static(path)
                return
            if method == "GET" and path == "/api/health":
                self.write_response({"ok": True, "latest": latest_draw()})
                return

            # Public AI generation does not imply public purchase data or destructive operations.
            if method in {"POST", "DELETE"} and not self.same_origin_request():
                self.write_response({"error": "不允许跨站操作，请在本站页面重试"}, status=403)
                return
            if method == "POST" and self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                self.write_response({"error": "请求必须使用 application/json"}, status=415)
                return
            if method == "GET" and path == "/api/session":
                self.write_response(self.access_info(include_session=True))
                return
            if method == "POST" and path == "/api/session":
                self.unlock_purchase()
                return
            if method == "DELETE" and path == "/api/session":
                revoke_purchase_session(self.session_value())
                self.write_response({"ok": True}, cookie=self.session_cookie("", max_age=0))
                return

            public_ai = (
                method == "GET" and (path in {"/api/ai/status", "/api/ai/recommendations"}
                    or path.startswith("/api/ai/recommendations/") or path.startswith("/api/ai/tasks/"))
                or method == "POST" and path in {"/api/ai/tasks", "/api/ai/recommendation"}
            )
            if not public_ai and not self.authorized():
                self.write_response({"error": "请先解锁购买记录；AI 分析无需授权"}, status=401)
                return

            if method == "GET" and path == "/api/access":
                self.write_response(self.access_info())
                return
            if method == "GET" and path == "/api/purchases":
                self.write_response({"items": read_json(PURCHASES_PATH, [])})
                return
            if method == "GET" and path == "/api/check-results":
                self.write_response({"items": read_json(RESULTS_PATH, [])})
                return
            if method == "GET" and path == "/api/state":
                self.write_response({
                    "latest": latest_draw(),
                    "purchases": read_json(PURCHASES_PATH, []),
                    "results": read_json(RESULTS_PATH, []),
                })
                return
            if method == "GET" and path == "/api/ai/status":
                self.write_response({
                    "configured": bool(os.environ.get("DEEPSEEK_API_KEY", "").strip()),
                    "model": os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
                })
                return
            if method == "GET" and path == "/api/ai/recommendations":
                limit = int(query.get("limit", ["20"])[-1])
                self.write_response({"items": list_ai_recommendations(limit)})
                return
            if method == "GET" and path == "/api/ai/recommendations/latest":
                item = get_ai_recommendation()
                self.write_response({"item": item})
                return
            if method == "GET" and path.startswith("/api/ai/recommendations/"):
                report_id = unquote(path.removeprefix("/api/ai/recommendations/"))
                self.write_ai_recommendation(report_id)
                return
            if method == "GET" and path.startswith("/api/ai/tasks/"):
                self.ai_task_status(unquote(path.removeprefix("/api/ai/tasks/")))
                return
            if method == "POST" and path == "/api/purchases":
                self.save_purchase()
                return
            if method == "POST" and path == "/api/ai/tasks":
                self.ai_recommendation(async_mode=True)
                return
            if method == "POST" and path == "/api/ai/recommendation":
                self.ai_recommendation(async_mode=query.get("async", [""])[-1].lower() in {"1", "true"})
                return
            if method == "POST" and path == "/api/check-now":
                self.write_response(run_check())
                return
            if method == "DELETE" and path.startswith("/api/purchases/"):
                purchase_id = unquote(path.split("/", 3)[3])
                self.delete_purchase(purchase_id)
                return
            if method == "DELETE" and path.startswith("/api/ai/recommendations/"):
                report_id = unquote(path.removeprefix("/api/ai/recommendations/"))
                self.delete_ai_recommendation(report_id)
                return

            self.write_response({"error": "not found"}, status=404)
        except ValueError as exc:
            self.write_response({"error": str(exc)}, status=400)
        except Exception as exc:
            self.write_response({"error": str(exc)}, status=500)

    def serve_static(self, path: str) -> None:
        allowed = {
            "/": (ROOT / "index.html", "text/html; charset=utf-8"),
            "/index.html": (ROOT / "index.html", "text/html; charset=utf-8"),
            "/styles.css": (ROOT / "styles.css", "text/css; charset=utf-8"),
            "/app.js": (ROOT / "app.js", "text/javascript; charset=utf-8"),
            "/data/ssq-history.js": (HISTORY_PATH.with_suffix(".js"), "text/javascript; charset=utf-8"),
            "/data/ssq-history.json": (HISTORY_PATH, "application/json; charset=utf-8"),
        }
        item = allowed.get(path)
        if not item or not item[0].is_file():
            self.write_response({"error": "not found"}, status=404)
            return
        file_path, content_type = item
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def save_purchase(self) -> None:
        payload = self.read_body()
        item = validate_purchase(payload)
        purchases = read_json(PURCHASES_PATH, [])
        purchases = [row for row in purchases if row.get("id") != item["id"]]
        purchases.append(item)
        purchases.sort(key=lambda row: (str(row.get("issue", "")), str(row.get("id", ""))))
        write_json(PURCHASES_PATH, purchases)
        self.write_response({"item": item, "notification": push_purchase_bark(item)})

    def ai_task_status(self, task_id: str) -> None:
        if not re.fullmatch(r"[-_A-Za-z0-9]{20,64}", task_id):
            self.write_response({"error": "AI 任务不存在或已过期"}, status=404)
            return
        task = get_ai_job(task_id)
        if not task:
            self.write_response({"error": "AI 任务不存在或已过期"}, status=404)
            return
        self.write_response(task)

    def write_ai_recommendation(self, report_id: str) -> None:
        if not re.fullmatch(r"[-_A-Za-z0-9]{20,64}", report_id):
            self.write_response({"error": "AI 分析记录不存在"}, status=404)
            return
        item = get_ai_recommendation(report_id)
        if not item:
            self.write_response({"error": "AI 分析记录不存在"}, status=404)
            return
        self.write_response({"item": item})

    def write_ai_task_reference(self, task_id: str) -> None:
        task = get_ai_job(task_id) or {"task_id": task_id, "status": "running"}
        task.update({
            "status_url": f"/api/ai/tasks/{task_id}",
            "poll_after_ms": 3000,
        })
        self.write_response(task, status=202)

    def ai_recommendation(self, *, async_mode: bool = False) -> None:
        if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
            self.write_response({"error": "服务端未配置 DeepSeek API"}, status=503)
            return
        payload = self.read_body()
        options = ai_request_options(payload)
        client_request_id = ai_client_request_id(payload) if async_mode else ""
        existing = find_ai_job_by_client_request_id(client_request_id)
        if existing:
            self.write_ai_task_reference(existing["task_id"])
            return
        if not AI_REQUEST_LOCK.acquire(blocking=False):
            self.write_response({"error": "已有 AI 分析正在进行，请稍后再试"}, status=429)
            return
        worker_owns_slot = False
        try:
            allowed, message = reserve_ai_quota()
            if not allowed:
                self.write_response({"error": message}, status=429)
                return
            if async_mode:
                task_id = start_ai_job(options, client_request_id=client_request_id)
                worker_owns_slot = True
                self.write_ai_task_reference(task_id)
                return
            result = generate_ai_recommendation(read_json(HISTORY_PATH, []), **options)
            report_id = secrets.token_urlsafe(18)
            result = dict(result)
            result["report_id"] = report_id
            save_ai_recommendation(
                report_id,
                task_id=report_id,
                client_request_id="",
                options=options,
                result=result,
            )
            self.write_response(result)
        except AiAnalysisError as exc:
            self.write_response({"error": str(exc)}, status=502)
        finally:
            if not worker_owns_slot:
                AI_REQUEST_LOCK.release()

    def delete_purchase(self, purchase_id: str) -> None:
        purchases = read_json(PURCHASES_PATH, [])
        remaining = [row for row in purchases if row.get("id") != purchase_id]
        if len(remaining) == len(purchases):
            self.write_response({"error": "purchase not found"}, status=404)
            return
        write_json(PURCHASES_PATH, remaining)
        self.write_response({"ok": True})

    def delete_ai_recommendation(self, report_id: str) -> None:
        if not re.fullmatch(r"[-_A-Za-z0-9]{20,64}", report_id) or not delete_ai_recommendation(report_id):
            self.write_response({"error": "AI 分析记录不存在"}, status=404)
            return
        self.write_response({"ok": True})

    def read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        if length > 65536:
            raise ValueError("请求内容不能超过 64KB")
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def local_authorized(self) -> bool:
        # Opt-in only in run_local.py. Never trust proxy headers or a loopback peer alone:
        # production nginx also connects from loopback.
        if os.environ.get("SSQ_LOCAL_AUTO_AUTH") != "1":
            return False
        if self.headers.get("X-SSQ-Local") != "1":
            return False
        try:
            if not ipaddress.ip_address(self.server.server_address[0]).is_loopback:
                return False
            if not ipaddress.ip_address(self.client_address[0]).is_loopback:
                return False
        except ValueError:
            return False
        if any(name.lower() == "forwarded" or name.lower().startswith("x-forwarded-")
               for name in self.headers):
            return False
        host = self.headers.get("Host", "")
        port = self.server.server_port
        allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
        if port == 80:
            allowed_hosts.update({"127.0.0.1", "localhost", "[::1]"})
        if host not in allowed_hosts:
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin != f"http://{host}":
            return False
        if self.headers.get("Sec-Fetch-Site", "same-origin") != "same-origin":
            return False
        return True

    def same_origin_request(self) -> bool:
        # Ignore proxy-supplied scheme/IP for authorization. Same-site subdomains are not trusted.
        if self.headers.get("Sec-Fetch-Site", "same-origin") != "same-origin":
            return False
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        return origin is None or bool(host and origin in {f"https://{host}", f"http://{host}"})

    def session_value(self) -> str:
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            value = cookies[PURCHASE_SESSION_COOKIE].value if PURCHASE_SESSION_COOKIE in cookies else ""
            return value if re.fullmatch(r"[-_A-Za-z0-9]{43}", value) else ""
        except CookieError:
            return ""

    def authorized(self) -> bool:
        token = os.environ.get("SSQ_ADMIN_TOKEN", "").strip()
        if not token or not self.same_origin_request():
            return False
        if self.local_authorized():
            return True
        auth = self.headers.get("Authorization", "")
        supplied = auth[7:].strip() if auth.startswith("Bearer ") else self.headers.get("X-Admin-Token", "").strip()
        if supplied and secrets.compare_digest(supplied.encode(), token.encode()):
            return True
        return valid_purchase_session(self.session_value(), token)

    def access_info(self, *, include_session: bool = False) -> dict:
        admin_token = os.environ.get("SSQ_ADMIN_TOKEN", "").strip()
        ai_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        info = {
            "mode": "local" if self.local_authorized() else "token",
            "keys": {"ai": bool(ai_key), "purchase": bool(admin_token)},
            "configured_key_count": int(bool(ai_key)) + int(bool(admin_token)),
            "independent_keys": bool(ai_key and admin_token and ai_key != admin_token),
        }
        if include_session:
            info["purchase_authorized"] = self.authorized()
            if not info["purchase_authorized"]:
                info["mode"] = "locked"
            elif info["mode"] != "local" and valid_purchase_session(self.session_value(), admin_token):
                info["mode"] = "session"
        return info

    def session_cookie(self, value: str, *, max_age: int = PURCHASE_SESSION_TTL) -> str:
        # Production TLS terminates outside this container. Never downgrade Secure from X-Forwarded-Proto.
        # Local HTTP uses the existing narrowly validated automatic access, not this cookie.
        return f"{PURCHASE_SESSION_COOKIE}={value}; Path=/; Max-Age={max_age}; HttpOnly; Secure; SameSite=Strict"

    def unlock_purchase(self) -> None:
        token = os.environ.get("SSQ_ADMIN_TOKEN", "").strip()
        if not token:
            self.write_response({"error": "服务端尚未配置购买密钥，AI 功能不受影响"}, status=503)
            return
        if self.headers.get("Origin", "https:").startswith("http:") and not self.local_authorized():
            self.write_response({"error": "请使用 HTTPS 网站解锁购买记录"}, status=400)
            return
        payload = self.read_body()
        if not isinstance(payload, dict) or not isinstance(payload.get("token"), str) or len(payload["token"]) > 4096:
            raise ValueError("请输入购买密钥，不是 AI 密钥")
        with LOGIN_ATTEMPT_LOCK:
            now = time.time()
            LOGIN_FAILURE_TIMES[:] = [t for t in LOGIN_FAILURE_TIMES if t > now - LOGIN_WINDOW_SECONDS]
            if len(LOGIN_FAILURE_TIMES) >= LOGIN_MAX_FAILURES:
                self.write_response({"error": "解锁尝试过多，请 5 分钟后重试"}, status=429)
                return
            if not secrets.compare_digest(payload["token"].strip().encode(), token.encode()):
                LOGIN_FAILURE_TIMES.append(now)
                self.write_response({"error": "购买密钥不正确，请勿填写 AI 密钥"}, status=401)
                return
        value = create_purchase_session(token, self.session_value())
        info = self.access_info(include_session=True)
        info.update(purchase_authorized=True, mode="session")
        self.write_response(info, cookie=self.session_cookie(value))

    def write_response(self, payload, status: int = 200, *, cookie: str | None = None) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_common_headers()
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_common_headers(self) -> None:
        # Same-origin UI only: never reflect an arbitrary Origin or enable credentialed CORS.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}", flush=True)


def ensure_files() -> None:
    PRIVATE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not PURCHASES_PATH.exists():
        write_json(PURCHASES_PATH, [])
    if not RESULTS_PATH.exists():
        write_json(RESULTS_PATH, [])


def main() -> None:
    ensure_files()
    host = os.environ.get("SSQ_API_HOST", "127.0.0.1")
    port = int(os.environ.get("SSQ_API_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), ApiHandler)
    print(f"SSQ purchase API listening on {host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
