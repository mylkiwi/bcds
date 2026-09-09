#!/usr/bin/env python3
"""Pin entry assets to their contents; run before commit and during image builds."""

import hashlib
from pathlib import Path
import re
import sys


def update_versions(root: Path) -> None:
    page = root / "index.html"
    html = page.read_text(encoding="utf-8")
    for asset in ("app.js", "styles.css"):
        version = hashlib.sha256((root / asset).read_bytes()).hexdigest()[:12]
        pattern = rf'(["\']){re.escape(asset)}(?:\?v=[^"\']*)?(["\'])'
        html, count = re.subn(pattern, lambda m: f"{m[1]}{asset}?v={version}{m[2]}", html)
        if count != (2 if asset == "app.js" else 1):
            raise ValueError(f"Unexpected entry asset references: {asset} ({count})")
    page.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    update_versions(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent)
