#!/usr/bin/env python3
"""Start the local, default-configured application without browser key entry."""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
import re
import secrets
import tempfile


ROOT = Path(__file__).resolve().parent


def configure_local_environment(root: Path = ROOT) -> None:
    os.environ.setdefault("SSQ_API_HOST", "127.0.0.1")
    os.environ.setdefault("SSQ_API_PORT", "8000")
    os.environ.setdefault("SSQ_LOCAL_AUTO_AUTH", "1")
    host = os.environ["SSQ_API_HOST"]
    try:
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if os.environ["SSQ_LOCAL_AUTO_AUTH"] == "1" and not loopback:
        raise ValueError("本地自动连接只能监听本机地址，不能开放到局域网或公网")

    admin_token = os.environ.get("SSQ_ADMIN_TOKEN", "").strip()
    ai_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    env_path = root / ".env"
    if not admin_token or admin_token == "replace-with-a-strong-admin-token" or admin_token == ai_key:
        # Only the local management credential is generated/rotated; never alter the AI key.
        admin_token = secrets.token_urlsafe(32)
        content = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        lines = [line for line in content.splitlines()
                 if not re.match(r"^\s*(?:export\s+)?SSQ_ADMIN_TOKEN=", line)]
        lines.append(f"SSQ_ADMIN_TOKEN={admin_token}")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=root, prefix=".env.", delete=False,
                                             encoding="utf-8") as stream:
                temporary = Path(stream.name)
                stream.write("\n".join(lines) + "\n")
            temporary.replace(env_path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        os.environ["SSQ_ADMIN_TOKEN"] = admin_token
    if env_path.exists():
        env_path.chmod(0o600)


def main() -> None:
    configure_local_environment()
    from purchase_api import main as serve
    serve()


if __name__ == "__main__":
    main()
