"""A real browser must print even when the container's normal home is not writable."""
import pytest
from chobra_reporting.pdf import PdfUnavailable, browser, html_to_pdf


def test_pdf_with_unwritable_default_home(monkeypatch):
    try:
        browser()
    except PdfUnavailable:
        pytest.skip("A Chromium-family browser is required for PDF integration")
    monkeypatch.setenv("HOME", "/nonexistent-chobra-home")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/nonexistent-chobra-home/config")
    monkeypatch.setenv("XDG_CACHE_HOME", "/nonexistent-chobra-home/cache")
    data = html_to_pdf('<html><meta charset="utf-8"><body><h1>Chobra</h1><p>Проверка награды и результата</p></body></html>')
    assert data.startswith(b"%PDF-")
    assert b"%%EOF" in data[-100:]
    assert len(data) > 1000
