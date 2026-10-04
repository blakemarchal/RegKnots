"""The regknots.com hostnames that are ours (2026-10-03).

DNS has a wildcard record, and Caddy's site block covers *.regknots.com with
on-demand TLS: before requesting a certificate for a name it asks
/domain-check (routers/health.py). That check used to approve every
*.regknots.com name, so scanners trying names (onlinebank, payment, login,
id-sso, ...) made Caddy request certificates for them: 1,109 junk
certificates by October 2026, Let's Encrypt's 50-a-week limit for the domain
exhausted since at least September (thousands of refused requests a day), and
the app served under phishing-looking names; a bot signed up through
onlinebank.regknots.com. CORS trusted the same names, with credentials.

Now only the apex, www and the client subdomains listed in
settings.tls_subdomains are ours. To give a client a subdomain: add it to
REGKNOTS_TLS_SUBDOMAINS in /opt/RegKnots/.env ("maersk" or
"maersk.regknots.com", comma-separated), restart regknots-api, and add its DNS
record if the wildcard record is gone. Caddy obtains the certificate on the
first visit.
"""
from __future__ import annotations

import logging
import re

from app.config import settings

logger = logging.getLogger(__name__)

DOMAIN = "regknots.com"
_BASE = (DOMAIN, f"www.{DOMAIN}")
_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def allowed_hosts() -> set[str]:
    """The apex, www and the configured client subdomains."""
    hosts = set(_BASE)
    for raw in settings.tls_subdomains.split(","):
        name = raw.strip().lower().rstrip(".")
        if not name:
            continue
        if name.endswith(f".{DOMAIN}"):
            name = name[: -len(DOMAIN) - 1]
        if not all(_LABEL.match(label) for label in name.split(".")):
            logger.warning("REGKNOTS_TLS_SUBDOMAINS: %r is not a hostname label; ignored", raw)
            continue
        hosts.add(f"{name}.{DOMAIN}")
    return hosts


def is_allowed(host: str) -> bool:
    return host.strip().lower().rstrip(".") in allowed_hosts()


def cors_origins() -> list[str]:
    """Origins the API answers with credentials: our hosts over HTTPS, plus
    settings.cors_origins; localhost origins only in development."""
    local = ("localhost", "127.0.0.1")
    extra = {o for o in settings.cors_origins if settings.is_dev or not any(h in o for h in local)}
    return sorted({f"https://{h}" for h in allowed_hosts()} | extra)
