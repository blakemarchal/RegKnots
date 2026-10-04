"""2026-10-03 — only our hostnames get a TLS certificate or credentialed CORS."""
import asyncio

import pytest
from fastapi import HTTPException

from app import hosts
from app.config import settings
from app.routers import health


@pytest.mark.parametrize("domain", ["regknots.com", "www.regknots.com", "WWW.RegKnots.com.", " regknots.com "])
def test_the_apex_and_www_get_certificates(domain):
    assert asyncio.run(health.domain_check(domain)) == {"ok": True}


@pytest.mark.parametrize("domain", [
    "onlinebank.regknots.com", "payment.regknots.com", "admin.regknots.com",
    "2122cdf4a0-0fdc-4228-93f8-5de43e94796d.regknots.com",
    "regknots.com.evil.com", "evilregknots.com", "", "*.regknots.com",
])
def test_any_other_name_is_refused(domain):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(health.domain_check(domain))
    assert exc.value.status_code == 403


def test_client_subdomains_come_from_the_env_list(monkeypatch):
    monkeypatch.setattr(settings, "tls_subdomains", "maersk, Fleet.RegKnots.com, bad name!, a..b, ")
    assert hosts.allowed_hosts() == {"regknots.com", "www.regknots.com", "maersk.regknots.com", "fleet.regknots.com"}
    assert asyncio.run(health.domain_check("maersk.regknots.com")) == {"ok": True}
    with pytest.raises(HTTPException):
        asyncio.run(health.domain_check("onlinebank.regknots.com"))


def test_cors_origins_are_our_hosts_and_localhost_only_in_development(monkeypatch):
    monkeypatch.setattr(settings, "tls_subdomains", "maersk")
    monkeypatch.setattr(settings, "cors_origins", ["http://localhost:3000"])
    monkeypatch.setattr(settings, "environment", "production")
    assert hosts.cors_origins() == ["https://maersk.regknots.com", "https://regknots.com", "https://www.regknots.com"]
    monkeypatch.setattr(settings, "environment", "development")
    assert "http://localhost:3000" in hosts.cors_origins()


def test_the_api_refuses_a_preflight_from_an_unknown_subdomain():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)    # no context manager: lifespan (DB pool) not started
    preflight = {"Access-Control-Request-Method": "POST"}
    bad = client.options("/auth/register", headers={"Origin": "https://onlinebank.regknots.com", **preflight})
    assert bad.status_code == 400 and "access-control-allow-origin" not in bad.headers
    good = client.options("/auth/register", headers={"Origin": "https://www.regknots.com", **preflight})
    assert good.status_code == 200
    assert good.headers["access-control-allow-origin"] == "https://www.regknots.com"
    assert good.headers["access-control-allow-credentials"] == "true"
