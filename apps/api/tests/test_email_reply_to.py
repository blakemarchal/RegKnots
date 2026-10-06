"""2026-10-06 — replies to app email reach Google Workspace (app.email.send_email).

App email is sent through Resend from mail.regknots.com, which takes no mail (no
MX, no A record), so every send needs a reply_to on regknots.com."""
import asyncio
import re
from pathlib import Path

from app import email as app_email

APP_DIR = Path(app_email.__file__).parent


def _capture(monkeypatch):
    sent = []
    monkeypatch.setattr(app_email.resend.Emails, "send", lambda params: sent.append(params) or {"id": "x"})
    return sent


def test_default_reply_to_and_an_explicit_one_wins(monkeypatch):
    sent = _capture(monkeypatch)
    app_email.send_email({"from": app_email.FROM_EMAIL, "to": ["a@example.com"], "subject": "s", "html": "h"})
    app_email.send_email({"from": app_email.FROM_EMAIL, "to": ["b@example.com"], "subject": "s", "html": "h",
                          "reply_to": "crew@example.com"})
    assert sent[0]["reply_to"] == ["support@regknots.com"]
    assert sent[1]["reply_to"] == "crew@example.com"


def test_an_email_without_its_own_reply_to_gets_one(monkeypatch):
    sent = _capture(monkeypatch)
    asyncio.run(app_email.send_welcome_email("new@example.com", "Jo Mariner"))
    assert sent[0]["reply_to"] == ["support@regknots.com"]
    assert sent[0]["from"].endswith("@mail.regknots.com>")


def test_no_send_bypasses_send_email():
    direct = []
    for path in APP_DIR.rglob("*.py"):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"resend\.Emails\.send\(", line) and not (path.name == "email.py" and "(params)" in line):
                direct.append(f"{path.relative_to(APP_DIR)}:{n}")
    assert direct == [], f"send through app.email.send_email instead: {direct}"
