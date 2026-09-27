"""Signup attribution (2026-09-26).

The web client records the first campaign touch (UTM parameters, an
outreach code `src`, a partner code `ref`, the external referrer and the
landing path) and sends it with registration. We keep the cleaned fields in
users.signup_attribution and one grouping label in users.signup_source.

Deliberately separate from users.referral_source, which carries the
charity-partner code, drives the tithe split and grants promo pricing.
"""
from __future__ import annotations

import re

FIELDS = (
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "src", "ref", "referrer_host", "landing_path", "first_seen_at",
)
_MAX_LEN = 120
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def clean(attribution) -> dict[str, str]:
    """The known fields, stripped of control characters, capped, blanks dropped."""
    if attribution is None:
        return {}
    out: dict[str, str] = {}
    for field in FIELDS:
        value = getattr(attribution, field, None)
        if value is None:
            continue
        value = _CONTROL.sub("", str(value)).strip()[:_MAX_LEN]
        if value:
            out[field] = value
    return out


def source_label(fields: dict[str, str]) -> str | None:
    """One label per signup for grouping, most specific first: an outreach
    code, then UTM source/medium/campaign, then a partner code, then the
    referring host. "direct" when the client sent a touch with none of those;
    None when it sent nothing."""
    if not fields:
        return None
    if fields.get("src"):
        return f"src:{fields['src'].lower()}"
    if fields.get("utm_source"):
        parts = (fields.get(k, "-").lower() for k in ("utm_source", "utm_medium", "utm_campaign"))
        return "utm:" + "/".join(parts)
    if fields.get("ref"):
        return f"ref:{fields['ref'].lower()}"
    if fields.get("referrer_host"):
        host = fields["referrer_host"].lower()
        return "referrer:" + (host[4:] if host.startswith("www.") else host)
    return "direct"
