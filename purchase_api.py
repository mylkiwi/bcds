#!/usr/bin/env python3
"""Small HTTP API for recording SSQ purchases on the server."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent
PUBLIC_DATA_DIR = Path(os.environ.get("SSQ_PUBLIC_DATA_DIR", ROOT / "data"))
PRIVATE_DATA_DIR = Path(os.environ.get("SSQ_PRIVATE_DATA_DIR", ROOT / "data"))
HISTORY_PATH = Path(os.environ.get("SSQ_HISTORY_PATH", PUBLIC_DATA_DIR / "ssq-history.json"))
PURCHASES_PATH = Path(os.environ.get("SSQ_PURCHASES_PATH", PRIVATE_DATA_DIR / "purchases.json"))
RESULTS_PATH = Path(os.environ.get("SSQ_RESULTS_PATH", PRIVATE_DATA_DIR / "check-results.json"))


def read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


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


def format_purchase_numbers(item: dict) -> str:
    if item.get("type") == "dantuo":
        dan = " ".join(f"{int(n):02d}" for n in item.get("dan", []))
        tuo = " ".join(f"{int(n):02d}" for n in item.get("tuo", []))
        blue = " ".join(f"{int(n):02d}" for n in item.get("blue", []))
        return f"胆拖 胆:{dan} 拖:{tuo} 蓝:{blue}"
    red = " ".join(f"{int(n):02d}" for n in item.get("red", []))
    blue = " ".join(f"{int(n):02d}" for n in item.get("blue", []))
    purchase_type = "单式" if item.get("type") == "single" else "复式"
    return f"{purchase_type} 红:{red} 蓝:{blue}"


def push_purchase_bark(item: dict) -> dict:
    bark_key = os.environ.get("BARK_KEY", "").strip()
    sound = os.environ.get("BARK_SOUND", "minuet").strip() or "minuet"
    title = f"双色球新增购买 {item['issue']}"
    body = f"{item['id']}：{format_purchase_numbers(item)}"
    note = str(item.get("note", "")).strip()
    if note:
        body += f"。备注：{note}"

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
        try:
            if path == "/api/health":
                self.write_response({"ok": True, "latest": latest_draw()})
                return

            if not self.authorized():
                self.write_response({"error": "unauthorized"}, status=401)
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
            if method == "POST" and path == "/api/purchases":
                self.save_purchase()
                return
            if method == "POST" and path == "/api/check-now":
                self.write_response(run_check())
                return
            if method == "DELETE" and path.startswith("/api/purchases/"):
                purchase_id = unquote(path.split("/", 3)[3])
                self.delete_purchase(purchase_id)
                return

            self.write_response({"error": "not found"}, status=404)
        except ValueError as exc:
            self.write_response({"error": str(exc)}, status=400)
        except Exception as exc:
            self.write_response({"error": str(exc)}, status=500)

    def save_purchase(self) -> None:
        payload = self.read_body()
        item = validate_purchase(payload)
        purchases = read_json(PURCHASES_PATH, [])
        purchases = [row for row in purchases if row.get("id") != item["id"]]
        purchases.append(item)
        purchases.sort(key=lambda row: (str(row.get("issue", "")), str(row.get("id", ""))))
        write_json(PURCHASES_PATH, purchases)
        self.write_response({"item": item, "notification": push_purchase_bark(item)})

    def delete_purchase(self, purchase_id: str) -> None:
        purchases = read_json(PURCHASES_PATH, [])
        remaining = [row for row in purchases if row.get("id") != purchase_id]
        if len(remaining) == len(purchases):
            self.write_response({"error": "purchase not found"}, status=404)
            return
        write_json(PURCHASES_PATH, remaining)
        self.write_response({"ok": True})

    def read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def authorized(self) -> bool:
        token = os.environ.get("SSQ_ADMIN_TOKEN", "").strip()
        if not token:
            return False
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and auth[7:].strip() == token:
            return True
        return self.headers.get("X-Admin-Token", "").strip() == token

    def write_response(self, payload, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_common_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_common_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "*"))
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, X-Admin-Token, Content-Type")
        self.send_header("Cache-Control", "no-store")

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
