"""PDF through a headless Chromium-family browser printing the report HTML."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

CANDIDATES = [
    os.environ.get("CHOBRA_CHROME", ""),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    shutil.which("chromium") or "",
    shutil.which("chromium-browser") or "",
    shutil.which("google-chrome") or "",
]


class PdfUnavailable(Exception):
    pass


def browser() -> str:
    for path in CANDIDATES:
        if path and Path(path).exists():
            return path
    raise PdfUnavailable("Не найден браузер для печати PDF; укажите CHOBRA_CHROME")


def html_to_pdf(document: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "report.html"
        target = Path(tmp) / "report.pdf"
        source.write_text(document, encoding="utf-8")
        subprocess.run(
            [browser(), "--headless=new", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage", "--no-pdf-header-footer", f"--user-data-dir={tmp}/profile", f"--print-to-pdf={target}", source.as_uri()],
            check=True, capture_output=True, timeout=90,
            env={**os.environ, "HOME": tmp, "XDG_CONFIG_HOME": f"{tmp}/config", "XDG_CACHE_HOME": f"{tmp}/cache"},
        )
        return target.read_bytes()
