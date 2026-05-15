import asyncio
import html as _html_lib
import logging
from typing import Awaitable, Callable

import resend
from app.config import settings

logger = logging.getLogger(__name__)

# Resend enforces 5 requests/sec on the default plan. Sleeping 0.25s between
# sends gives us ~4/sec — a safe margin under that ceiling. All batch send
# loops (admin/founding-email/send, trial reminders, etc.) MUST go through
# send_with_throttle() to stay under the limit.
RESEND_THROTTLE_SECONDS: float = 0.25


def _is_rate_limit_error(exc: Exception) -> bool:
    """Heuristic: does this exception look like a Resend 429?"""
    msg = str(exc).lower()
    return (
        "429" in msg
        or "too many requests" in msg
        or "rate limit" in msg
        or "rate_limit" in msg
    )


async def send_with_throttle(
    coro_factory: Callable[[], Awaitable[None]],
    label: str,
) -> None:
    """Invoke one email send with a 1-retry on rate-limit errors.

    Does NOT sleep AFTER the send — callers are responsible for spacing
    successive sends by RESEND_THROTTLE_SECONDS so a 1-off send doesn't
    pay a needless delay.

    Args:
        coro_factory: a zero-arg callable returning an awaitable that
            performs exactly one Resend send. Passed as a factory (not a
            raw coroutine) so we can re-invoke it cleanly on retry.
        label: human-readable identifier for logs (usually the recipient
            email), used to differentiate entries in Sentry/journald.

    Raises:
        Whatever the underlying send raises (after the retry, on the
        second failure). Callers are expected to wrap this in their own
        try/except + collect failures into a list.
    """
    try:
        await coro_factory()
        logger.info("Email sent: %s", label)
        return
    except Exception as exc:
        if _is_rate_limit_error(exc):
            logger.warning(
                "Email rate-limited on first attempt (%s): %s — retrying in 1s",
                label, exc,
            )
            await asyncio.sleep(1.0)
            try:
                await coro_factory()
                logger.info("Email sent on retry: %s", label)
                return
            except Exception as retry_exc:
                logger.error(
                    "Email failed after retry (%s): %s", label, retry_exc,
                )
                raise
        logger.error("Email failed (%s): %s", label, exc)
        raise

resend.api_key = settings.resend_api_key


# Sprint D6.92 — tier-aware copy helpers for subscription lifecycle
# emails. Pre-D6.92 every lifecycle email said "RegKnot Pro" — a dead
# legacy tier — and `send_subscription_confirmed_email` claimed
# "Unlimited questions — no message caps" regardless of which tier the
# user actually subscribed to (a flat lie for Cadet at 25/mo and Mate
# at 100/mo). These helpers let each email render the actual tier name
# and cap line.
def _tier_label(tier: str | None) -> str:
    """User-facing label for an internal tier value. Legacy `pro`/`solo`
    map to Captain for visual consistency with the account page; an
    unrecognized tier returns the empty string so callers can fall back
    to generic "RegKnot subscription" wording."""
    return {
        "cadet":   "Cadet",
        "mate":    "Mate",
        "captain": "Captain",
        "pro":     "Captain",  # legacy → Captain
        "solo":    "Captain",  # legacy → Captain
    }.get(tier or "", "")


def _tier_cap_line(tier: str | None) -> str:
    """One-line description of the tier's message-cap benefit. Used in
    the welcome email's "Here's what you get" list."""
    if tier == "cadet":
        return "25 compliance questions per month"
    if tier == "mate":
        return "100 compliance questions per month"
    if tier in ("captain", "pro", "solo"):
        return "Unlimited compliance questions"
    return "RegKnot subscription benefits"

FROM_EMAIL = "RegKnot <hello@mail.regknots.com>"
CAPTAIN_EMAIL = "RegKnot <captain@mail.regknots.com>"
APP_URL = "https://regknots.com"

_BASE_STYLES = """
  body { margin: 0; padding: 0; background-color: #0a0e1a; font-family: 'Courier New', Courier, monospace; }
  .wrapper { max-width: 560px; margin: 0 auto; padding: 40px 24px; }
  .card { background-color: #111827; border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 36px 32px; }
  .logo { display: flex; align-items: center; gap: 10px; margin-bottom: 32px; }
  .logo-text { font-family: Arial, sans-serif; font-size: 22px; font-weight: 900; letter-spacing: 0.2em; text-transform: uppercase; color: #f0ece4; }
  .logo-text span { color: #2dd4bf; }
  h1 { font-family: Arial, sans-serif; font-size: 28px; font-weight: 900; color: #f0ece4; margin: 0 0 16px; letter-spacing: -0.02em; line-height: 1.1; }
  p { font-size: 14px; line-height: 1.7; color: #6b7594; margin: 0 0 16px; }
  .cta { display: inline-block; margin: 8px 0 24px; padding: 14px 28px; background-color: #2dd4bf; color: #0a0e1a; font-family: 'Courier New', Courier, monospace; font-size: 13px; font-weight: 700; text-decoration: none; border-radius: 10px; letter-spacing: 0.1em; text-transform: uppercase; }
  .divider { border: none; border-top: 1px solid rgba(255,255,255,0.08); margin: 24px 0; }
  .disclaimer { font-size: 11px; color: rgba(107,117,148,0.6); line-height: 1.6; margin: 0; }
  .token-box { background-color: #0d1225; border: 1px solid rgba(45,212,191,0.2); border-radius: 8px; padding: 12px 16px; font-size: 13px; color: #2dd4bf; word-break: break-all; margin: 16px 0; }
"""


def _html(body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>{_BASE_STYLES}</style>
</head>
<body>
  <div class="wrapper">
    <div class="card">
      <div class="logo">
        <span class="logo-text">Reg<span>Knot</span></span>
      </div>
      {body}
      <hr class="divider">
      <p class="disclaimer">
        RegKnot is a navigation aid only — not legal advice. Always verify compliance requirements with
        the applicable regulations and consult qualified maritime counsel for legal matters.
      </p>
    </div>
  </div>
</body>
</html>"""


async def send_welcome_email(to_email: str, full_name: str) -> None:
    raw_first = full_name.split()[0] if full_name.strip() else "Mariner"
    first_name = _html_lib.escape(raw_first)
    html = _html(f"""
      <h1>Welcome aboard, {first_name}</h1>
      <p>
        You're now registered with RegKnot — your AI-powered maritime compliance co-pilot.
        Get instant cited answers to questions across CFR Titles 33, 46 &amp; 49, COLREGs, NVICs,
        SOLAS 2024, STCW, the ISM Code, and the ERG — all tailored to your vessel profile.
      </p>
      <p>
        Ask about inspection schedules, certificate requirements, carriage requirements, SOLAS
        applicability, safety management systems, watchkeeping standards, and more — all cited
        to the exact regulation you can verify at the source.
      </p>
      <a href="{APP_URL}" class="cta">Start Asking Questions</a>
      <p style="font-size:12px; color:rgba(107,117,148,0.7); margin-top:8px;">
        Set up your vessel profile first for the most accurate answers.
      </p>
    """)
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": f"Welcome aboard, {raw_first}",
        "html": html,
    })


async def send_verification_email(to_email: str, full_name: str, token: str) -> None:
    raw_first = full_name.split()[0] if full_name and full_name.strip() else "Mariner"
    first_name = _html_lib.escape(raw_first)
    verify_url = f"{APP_URL}/verify-email?token={token}"
    html = _html(f"""
      <h1>Verify your email, {first_name}</h1>
      <p>
        Welcome to RegKnot! Please confirm your email address to unlock full access.
        You can send up to 5 messages before verifying.
      </p>
      <a href="{verify_url}" class="cta">Verify Email</a>
      <p style="font-size:12px; color:rgba(107,117,148,0.7); margin-top:4px;">
        Or copy this link into your browser:
      </p>
      <div class="token-box">{verify_url}</div>
      <p style="font-size:12px; color:rgba(107,117,148,0.6);">
        If you didn't create a RegKnot account, you can safely ignore this email.
      </p>
    """)
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": "Verify your email — RegKnot",
        "html": html,
    })


async def send_support_confirmation_email(to_email: str, full_name: str, subject: str) -> None:
    raw_first = full_name.split()[0] if full_name and full_name.strip() else "Mariner"
    first_name = _html_lib.escape(raw_first)
    safe_subject = _html_lib.escape(subject)
    html = _html(f"""
      <h1>We got your message, {first_name}</h1>
      <p>
        Your support request has been received:
      </p>
      <div class="token-box" style="color:#f0ece4; border-color:rgba(255,255,255,0.1);">
        <strong>Subject:</strong> {safe_subject}
      </div>
      <p>
        We typically respond within 24 hours. If your issue is urgent, you can also reply
        directly to this email.
      </p>
    """)
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "reply_to": ["support@regknots.com"],
        "subject": "We received your message — RegKnot Support",
        "html": html,
    })


async def send_support_reply_email(
    to_email: str,
    user_name: str,
    original_subject: str,
    reply_text: str,
    original_message: str,
) -> None:
    """Personal reply from the captain. reply_to → support@ for follow-ups."""
    first_name = user_name.split()[0] if user_name and user_name.strip() else "Mariner"
    safe_subject = _html_lib.escape(original_subject)
    safe_reply = _html_lib.escape(reply_text)
    safe_original = _html_lib.escape(original_message)
    html = _html(f"""
      <h1>Re: {safe_subject}</h1>
      <p>Hey {_html_lib.escape(first_name)},</p>
      <div style="background-color:#0d1225; border-left:3px solid #2dd4bf; padding:16px; border-radius:8px; margin:16px 0;">
        <p style="color:#f0ece4; white-space:pre-wrap; margin:0;">{safe_reply}</p>
      </div>
      <p>
        If you have follow-up questions, reply to this email or submit another
        request through the Support page in RegKnot.
      </p>
      <p style="color:rgba(107,117,148,0.9); font-size:12px; margin-top:24px; margin-bottom:4px;">
        Your original message:
      </p>
      <div style="background-color:rgba(13,18,37,0.6); border-left:2px solid rgba(107,117,148,0.4); padding:12px 16px; border-radius:6px; margin:0;">
        <p style="color:rgba(240,236,228,0.7); white-space:pre-wrap; margin:0; font-size:13px;">{safe_original}</p>
      </div>
    """)
    resend.Emails.send({
        "from": CAPTAIN_EMAIL,
        "to": [to_email],
        "reply_to": ["support@regknots.com"],
        "subject": f"Re: {original_subject} — RegKnot Support",
        "html": html,
    })


async def send_password_changed_email(to_email: str, full_name: str) -> None:
    raw_first = full_name.split()[0] if full_name and full_name.strip() else "Mariner"
    first_name = _html_lib.escape(raw_first)
    safe_email = _html_lib.escape(to_email)
    html = _html(f"""
      <h1>Password changed</h1>
      <p>
        Hey {first_name} — this is a confirmation that the password for your RegKnot account
        (<strong style="color:#f0ece4;">{safe_email}</strong>) was just changed.
      </p>
      <p>
        If you made this change, no action is needed.
      </p>
      <p style="color:#f59e0b;">
        If you did <strong>not</strong> change your password, please contact us immediately
        at <a href="mailto:support@regknots.com" style="color:#2dd4bf;">support@regknots.com</a>.
      </p>
    """)
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": "Your RegKnot password was changed",
        "html": html,
    })


async def send_password_reset_email(to_email: str, reset_token: str) -> None:
    reset_url = f"{APP_URL}/reset-password?token={reset_token}"
    html = _html(f"""
      <h1>Reset your password</h1>
      <p>
        We received a request to reset the password for your RegKnot account.
        Click the button below to choose a new password. This link expires in <strong style="color:#f0ece4;">1 hour</strong>.
      </p>
      <a href="{reset_url}" class="cta">Reset Password</a>
      <p style="font-size:12px; color:rgba(107,117,148,0.7); margin-top:4px;">
        Or copy this link into your browser:
      </p>
      <div class="token-box">{reset_url}</div>
      <p style="font-size:12px; color:rgba(107,117,148,0.6);">
        If you didn't request a password reset, you can safely ignore this email.
        Your password won't change until you click the link above.
      </p>
    """)
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": "Reset your RegKnot password",
        "html": html,
    })


async def send_trial_expiring_email(to_email: str, full_name: str, messages_used: int) -> None:
    """3-day pre-expiry trial reminder.

    Sprint D6.92 — copy refreshed for current tier landscape. Leads with
    Cadet at $9.99 as the low-friction entry; mentions Mate/Captain as
    upsells. Pre-D6.92 this said only "our paid plans cover unlimited
    compliance questions" — true for Captain but misleading for Cadet
    and Mate, both of which have caps.
    """
    raw_first = full_name.split()[0] if full_name.strip() else "Mariner"
    first_name = _html_lib.escape(raw_first)
    html = _html(f"""
      <h1>Your RegKnot trial ends in 3 days</h1>
      <p>
        Hey {first_name} — quick heads up that your trial expires in 3 days.
        You've asked <strong style="color:#f0ece4;">{messages_used}</strong> regulation
        questions so far.
      </p>
      <p>
        Before you decide whether to continue, I'd genuinely like your honest read
        on RegKnot — what's worked, what hasn't, what's missing for your day-to-day
        work. Just hit reply to this email; I read every response personally.
      </p>
      <p>
        If you've found it useful and want to keep going, we now offer three plans:
      </p>
      <ul style="padding-left:20px; margin:0 0 16px;">
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">
          <strong style="color:#f0ece4;">Cadet</strong> — $9.99/month — 25 questions per month
        </li>
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">
          <strong style="color:#f0ece4;">Mate</strong> — $19.99/month — 100 questions per month
        </li>
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">
          <strong style="color:#f0ece4;">Captain</strong> — $39.99/month — unlimited
        </li>
      </ul>
      <p>
        Most mariners we hear from end up on Cadet — designed as pocket-money
        compliance insurance, a straight answer the one time per month a question
        stumps you.
      </p>
      <a href="{APP_URL}/pricing" class="cta">See plans</a>
      <p style="font-size:12px; color:rgba(107,117,148,0.7); margin-top:14px;">
        Either way, thanks for trying RegKnot. Your feedback shapes what we build next.
      </p>
    """)
    resend.Emails.send({
        "from": CAPTAIN_EMAIL,
        "to": [to_email],
        "subject": "Your RegKnot trial ends in 3 days — quick favor first",
        "html": html,
    })


# Sprint D6.92 — `send_pilot_ended_email` REMOVED. This was a legacy
# function from the pre-launch pilot era that wasn't wired to any
# scheduled job (only the admin test-email endpoint exercised it). Its
# copy hardcoded "$39/month for RegKnot Pro" which contradicted the
# current /pricing page. Rather than refresh dead code, delete it.
# The trial 3-day warning above (send_trial_expiring_email) is the
# only auto-fired trial touchpoint going forward.


async def send_waitlist_confirmed_email(to_email: str, full_name: str) -> None:
    raw_first = full_name.split()[0] if full_name.strip() else "Mariner"
    first_name = _html_lib.escape(raw_first)
    html = _html(f"""
      <h1>You're on the list, {first_name}</h1>
      <p>
        Thanks for your interest in RegKnot. You've been added to our waitlist and we'll notify you
        as soon as a spot opens up.
      </p>
      <p>
        In the meantime, here's what you can look forward to: instant cited answers across
        CFR Titles 33, 46 &amp; 49, COLREGs, NVICs, SOLAS 2024, STCW, the ISM Code, and the ERG —
        all tailored to your vessel profile.
      </p>
      <p style="font-size:13px; color:#2dd4bf;">
        Waitlist members get priority access when we open up.
      </p>
      <a href="{APP_URL}" class="cta">Learn More</a>
    """)
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": f"You're on the RegKnot waitlist, {raw_first}",
        "html": html,
    })


async def send_subscription_cancelled_email(
    to_email: str, full_name: str, tier: str | None = None,
) -> None:
    """Sprint D6.92 — tier-aware copy. Pre-D6.92 hardcoded `RegKnot Pro`
    even for users on Cadet/Mate/Captain. `tier` is optional so legacy
    callers still work; falls back to generic "your RegKnot subscription"
    wording when omitted."""
    raw_first = full_name.split()[0] if full_name.strip() else "Mariner"
    first_name = _html_lib.escape(raw_first)
    tier_label = _tier_label(tier)
    sub_phrase = f"RegKnot {tier_label}" if tier_label else "RegKnot"
    html = _html(f"""
      <h1>Your subscription has been cancelled</h1>
      <p>
        Hi {first_name} — your {sub_phrase} subscription has been cancelled.
        You'll continue to have access until the end of your current billing period.
      </p>
      <p>
        If you change your mind, you can re-subscribe anytime:
      </p>
      <a href="{APP_URL}/pricing" class="cta">Re-subscribe</a>
      <p style="font-size:12px; color:rgba(107,117,148,0.7); margin-top:8px;">
        We'd love to hear what we could do better — reply to this email or use the
        support chat in the app. Fair winds.
      </p>
    """)
    resend.Emails.send({
        "from": CAPTAIN_EMAIL,
        "to": [to_email],
        "subject": "Your RegKnot subscription has been cancelled",
        "html": html,
    })


async def send_subscription_confirmed_email(
    to_email: str, full_name: str, tier: str | None = None,
) -> None:
    """Sprint D6.92 — tier-aware welcome copy. Pre-D6.92 claimed
    "Unlimited questions — no message caps" for every signup, which was
    a flat lie for Cadet (25/mo) and Mate (100/mo). Now names the
    actual tier and shows the right cap line."""
    raw_first = full_name.split()[0] if full_name.strip() else "Mariner"
    first_name = _html_lib.escape(raw_first)
    tier_label = _tier_label(tier)
    welcome_title = f"Welcome to RegKnot {tier_label}".strip()
    cap_line = _tier_cap_line(tier)
    html = _html(f"""
      <h1>{welcome_title}</h1>
      <p>
        Welcome aboard, {first_name} — your {f"RegKnot {tier_label}" if tier_label else "RegKnot"} subscription is now active.
      </p>
      <p>
        Here's what you get:
      </p>
      <ul style="padding-left:20px; margin:0 0 16px;">
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">{cap_line}</li>
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">CFR Titles 33, 46 &amp; 49 + SOLAS, COLREGs, NVICs, STCW, MARPOL, ISM Code &amp; ERG</li>
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">Vessel-specific compliance answers</li>
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">Audit-ready chat logs</li>
      </ul>
      <a href="{APP_URL}" class="cta">Start Asking Questions</a>
    """)
    resend.Emails.send({
        "from": CAPTAIN_EMAIL,
        "to": [to_email],
        "subject": f"{welcome_title}, {raw_first}",
        "html": html,
    })


async def send_payment_failed_email(
    to_email: str, full_name: str, tier: str | None = None,
) -> None:
    """Sprint D6.92 — tier-aware (drops `Pro` wording)."""
    raw_first = full_name.split()[0] if full_name.strip() else "Mariner"
    first_name = _html_lib.escape(raw_first)
    tier_label = _tier_label(tier)
    sub_phrase = f"RegKnot {tier_label}" if tier_label else "RegKnot"
    html = _html(f"""
      <h1>Action Required: Payment Failed</h1>
      <p>
        Hi {first_name} — we were unable to process your latest {sub_phrase} payment.
        Your payment method may have expired or been declined.
      </p>
      <p>
        You still have access for now, but your subscription may be interrupted if the
        payment isn't resolved soon. Please update your payment method in the billing portal:
      </p>
      <a href="{APP_URL}/account" class="cta">Update Payment Method</a>
      <p style="font-size:12px; color:rgba(107,117,148,0.7); margin-top:8px;">
        If you believe this is an error, reply to this email and we'll look into it.
      </p>
    """)
    resend.Emails.send({
        "from": CAPTAIN_EMAIL,
        "to": [to_email],
        "subject": f"RegKnot — Action Required: Payment Failed",
        "html": html,
    })


async def send_subscription_paused_email(
    to_email: str, full_name: str, tier: str | None = None,
) -> None:
    """Sprint D6.92 — tier-aware (drops `Pro` wording)."""
    raw_first = full_name.split()[0] if full_name.strip() else "Mariner"
    first_name = _html_lib.escape(raw_first)
    tier_label = _tier_label(tier)
    sub_phrase = f"RegKnot {tier_label}" if tier_label else "RegKnot"
    html = _html(f"""
      <h1>Your Subscription is Paused</h1>
      <p>
        Hi {first_name} — your {sub_phrase} subscription has been paused.
        You won't be charged during the pause period.
      </p>
      <p>
        While paused, your access to RegKnot Pro features is suspended.
        When you're ready to come back, you can resume your subscription anytime:
      </p>
      <a href="{APP_URL}/account" class="cta">Resume Subscription</a>
      <p style="font-size:12px; color:rgba(107,117,148,0.7); margin-top:8px;">
        Your vessel profiles and chat history are saved and will be waiting for you.
      </p>
    """)
    resend.Emails.send({
        "from": CAPTAIN_EMAIL,
        "to": [to_email],
        "subject": "RegKnot — Your Subscription is Paused",
        "html": html,
    })


async def send_charity_suggestion_email(
    user_email: str, org_name: str, website: str, reason: str
) -> None:
    safe_email = _html_lib.escape(user_email)
    safe_org = _html_lib.escape(org_name)
    safe_reason = _html_lib.escape(reason).replace("\n", "<br>")
    # Only allow http(s) websites and escape them before rendering
    if website and (website.startswith("http://") or website.startswith("https://")):
        safe_website = _html_lib.escape(website, quote=True)
        website_html = (
            f'<p><strong>Website:</strong> '
            f'<a href="{safe_website}" rel="noopener noreferrer">{safe_website}</a></p>'
        )
    else:
        website_html = ""
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": ["hello@regknots.com"],
        "reply_to": user_email,
        "subject": f"[Charity Suggestion] {org_name}",
        "html": (
            f"<h2>New Charity Partner Suggestion</h2>"
            f"<p><strong>From:</strong> {safe_email}</p>"
            f"<p><strong>Organization:</strong> {safe_org}</p>"
            f"{website_html}"
            f"<hr>"
            f"<p><strong>Why this organization:</strong></p>"
            f"<p>{safe_reason}</p>"
        ),
    })


def render_founding_member_email(full_name: str | None) -> tuple[str, str]:
    """Return (subject, html) for the early-user thank-you announcement email.

    Sprint D6.92 — copy refreshed for current tier landscape and 7-day
    trial (was 14-day pre-0050). Pre-D6.92 this hardcoded "$39/$29 for
    RegKnot Pro" and mentioned "Enterprise subdomains" which doesn't
    exist (replaced by Wheelhouse). Now leads with the three-tier
    structure including the new $9.99 Cadet entry point.

    Function name preserved for admin-dashboard backward compatibility.
    """
    raw_first = (full_name or "").split()[0] if (full_name or "").strip() else ""
    first_name = _html_lib.escape(raw_first) if raw_first else "Captain"
    subject = "Your RegKnot access is ready"
    html = _html(f"""
      <h1>Hi {first_name},</h1>
      <p>
        Thank you for being one of the first mariners to try RegKnot.
        Your questions and feedback have shaped this product in ways we
        couldn&rsquo;t have done alone.
      </p>
      <p>
        RegKnot now offers three plans, all billed monthly or annually:
      </p>
      <ul style="padding-left:20px; margin:0 0 16px;">
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">
          <strong style="color:#f0ece4;">Cadet</strong> &mdash; $9.99/month &mdash; 25 questions per month
        </li>
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">
          <strong style="color:#f0ece4;">Mate</strong> &mdash; $19.99/month &mdash; 100 questions per month
        </li>
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">
          <strong style="color:#f0ece4;">Captain</strong> &mdash; $39.99/month &mdash; unlimited
        </li>
      </ul>
      <p>
        Every subscription includes a 7-day free trial &mdash; no credit card required.
        For crews, Wheelhouse covers up to 10 seats per vessel.
      </p>
      <p style="color:#f0ece4; font-weight:700; margin-top:24px; margin-bottom:8px;">
        What you get:
      </p>
      <ul style="padding-left:20px; margin:0 0 16px;">
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">
          Cited, regulation-backed answers across CFR, SOLAS, MARPOL, STCW, COLREGs, NVICs, ISM Code, IMDG, and the ERG
        </li>
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">
          Vessel-aware context that remembers your ship&rsquo;s profile
        </li>
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">
          Study Tools &mdash; quiz and study-guide generators (Mate and Cadet plans)
        </li>
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">
          Real-time progress tracking as your question is researched
        </li>
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">
          Export your chat history for personal records
        </li>
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">
          Priority access to new features as we add them
        </li>
      </ul>
      <p style="color:#f0ece4; font-weight:700; margin-top:24px; margin-bottom:8px;">
        What your subscription supports:
      </p>
      <p>
        10% of every dollar goes directly to maritime charities &mdash; Mercy Ships,
        Waves of Impact, Women Offshore, and a few others. When you subscribe,
        you&rsquo;re not just getting a tool. You&rsquo;re supporting organizations
        doing meaningful work.
        <a href="{APP_URL}/giving" style="color:#2dd4bf; text-decoration:none;">Learn more &rarr;</a>
      </p>
      <p>
        Your trial is still active, so there&rsquo;s no rush. When you&rsquo;re
        ready, pick a plan:
      </p>
      <a href="{APP_URL}/pricing" class="cta">See plans</a>
      <p>
        If you have questions, feedback, or just want to say hey &mdash; reply to this
        email. It comes straight to us, not a support queue.
      </p>
      <p style="margin-top:24px;">
        Fair winds,<br>
        <strong style="color:#f0ece4;">Karynn Marchal</strong><br>
        <span style="color:rgba(107,117,148,0.85);">Co-founder &amp; Captain</span><br>
        <span style="color:rgba(107,117,148,0.85);">RegKnot</span>
      </p>
      <p style="font-size:12px; color:rgba(107,117,148,0.75); margin-top:24px;">
        P.S. &mdash; If you know another mariner who&rsquo;d find RegKnot useful, send
        them to <a href="{APP_URL}" style="color:#2dd4bf; text-decoration:none;">regknots.com</a>.
        We&rsquo;re building this for the fleet, not just the bridge.
      </p>
    """)
    return subject, html


async def send_founding_member_email(to: str, name: str | None) -> None:
    subject, html = render_founding_member_email(name)
    resend.Emails.send({
        "from": CAPTAIN_EMAIL,
        "to": [to],
        "reply_to": ["hello@regknots.com"],
        "subject": subject,
        "html": html,
    })


async def send_contact_inquiry_email(
    from_name: str,
    from_email: str,
    company: str | None,
    message: str,
) -> None:
    """Forward a public contact-form submission to hello@regknots.com.

    `reply_to` is set to the inquirer's email so replying from the inbox
    goes straight to them, not back to the RegKnot sending domain.
    """
    safe_name = _html_lib.escape(from_name)
    safe_email = _html_lib.escape(from_email)
    safe_company = _html_lib.escape(company) if company else None
    safe_message = _html_lib.escape(message).replace("\n", "<br>")

    company_line = (
        f"<p><strong>Company:</strong> {safe_company}</p>"
        if safe_company
        else '<p><strong>Company:</strong> <span style="color:rgba(107,117,148,0.7);">not provided</span></p>'
    )
    subject = (
        f"RegKnots Contact: {from_name} ({company})"
        if company
        else f"RegKnots Contact: {from_name}"
    )

    html = _html(f"""
      <h1>New Contact Inquiry</h1>
      <p><strong>Name:</strong> {safe_name}</p>
      <p><strong>Email:</strong> <a href="mailto:{safe_email}" style="color:#2dd4bf; text-decoration:none;">{safe_email}</a></p>
      {company_line}
      <hr class="divider">
      <p style="white-space: pre-wrap; color:#f0ece4;">{safe_message}</p>
    """)

    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": ["hello@regknots.com"],
        "reply_to": from_email,
        "subject": subject,
        "html": html,
    })


async def send_subscription_resumed_email(
    to_email: str, full_name: str, tier: str | None = None,
) -> None:
    """Sprint D6.92 — tier-aware (drops `Pro` + the false "unlimited"
    claim that applied only to Captain)."""
    raw_first = full_name.split()[0] if full_name.strip() else "Mariner"
    first_name = _html_lib.escape(raw_first)
    tier_label = _tier_label(tier)
    sub_phrase = f"RegKnot {tier_label}" if tier_label else "RegKnot"
    html = _html(f"""
      <h1>Welcome Back, {first_name}!</h1>
      <p>
        Your {sub_phrase} subscription has been resumed. Full access is restored —
        vessel-specific answers and every regulation source we've ingested are
        available again.
      </p>
      <a href="{APP_URL}" class="cta">Start Asking Questions</a>
    """)
    resend.Emails.send({
        "from": CAPTAIN_EMAIL,
        "to": [to_email],
        "subject": f"RegKnot — Welcome Back! Subscription Resumed",
        "html": html,
    })


# ── Workspace lifecycle (Sprint D6.54) ──────────────────────────────────


async def send_workspace_trial_ending_email(
    to_email: str, workspace_name: str,
) -> None:
    """Day 25 of trial — 5 days left, add a card."""
    safe_name = _html_lib.escape(workspace_name)
    workspaces_url = f"{APP_URL}/workspaces"
    html = _html(f"""
      <h1>5 days left in your Wheelhouse trial</h1>
      <p>
        Your <strong style="color:#2dd4bf;">{safe_name}</strong> Wheelhouse
        trial ends in 5 days. To keep your crew's chat history, dossier,
        and handoff notes flowing, add a payment method before the trial
        ends.
      </p>
      <p>
        After the trial, the workspace enters a 30-day read-only window
        where you can still view everything but can't add new entries.
        After that, it's archived (90-day recovery before purge).
      </p>
      <a href="{workspaces_url}" class="cta">Add Payment Method</a>
    """)
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": f"5 days left — add a card to keep {workspace_name}",
        "html": html,
    })


async def send_workspace_trial_ended_email(
    to_email: str, workspace_name: str,
) -> None:
    """Day 30 — trial ended, workspace is now read-only for 30 days."""
    safe_name = _html_lib.escape(workspace_name)
    workspaces_url = f"{APP_URL}/workspaces"
    html = _html(f"""
      <h1>Wheelhouse trial ended</h1>
      <p>
        The 30-day trial for <strong style="color:#2dd4bf;">{safe_name}</strong>
        has ended. The workspace is now <strong>read-only</strong> &mdash;
        your crew can still view existing chats, dossier entries, and
        handoff notes, but no new entries until you add a payment method.
      </p>
      <p>
        You have <strong>30 days</strong> to add a card. After that, the
        workspace is archived with a 90-day recovery window.
      </p>
      <a href="{workspaces_url}" class="cta">Add Payment Method</a>
    """)
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": f"Trial ended — {workspace_name} is read-only",
        "html": html,
    })


async def send_workspace_card_pending_reminder_email(
    to_email: str, workspace_name: str,
) -> None:
    """Day 25 of card_pending — 5 days left to rescue."""
    safe_name = _html_lib.escape(workspace_name)
    workspaces_url = f"{APP_URL}/workspaces"
    html = _html(f"""
      <h1>5 days left to save {safe_name}</h1>
      <p>
        Your <strong style="color:#2dd4bf;">{safe_name}</strong> Wheelhouse
        will be archived in 5 days unless you add a payment method.
      </p>
      <p>
        Once archived, the workspace becomes inaccessible to your crew.
        You'll have a 90-day recovery window before everything is
        permanently deleted. Add a card now to keep things running.
      </p>
      <a href="{workspaces_url}" class="cta">Add Payment Method</a>
    """)
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": f"5 days left — {workspace_name} will be archived",
        "html": html,
    })


async def send_workspace_archived_email(
    to_email: str, workspace_name: str,
) -> None:
    """Card-pending grace expired — workspace archived, 90-day retention."""
    safe_name = _html_lib.escape(workspace_name)
    workspaces_url = f"{APP_URL}/workspaces"
    html = _html(f"""
      <h1>Wheelhouse archived</h1>
      <p>
        <strong style="color:#2dd4bf;">{safe_name}</strong> has been
        archived. Your crew can no longer access it.
      </p>
      <p>
        You have <strong>90 days</strong> to restore the workspace by
        adding a payment method. After that, all data (chat history,
        dossier, handoff notes) will be permanently deleted.
      </p>
      <a href="{workspaces_url}" class="cta">Restore Workspace</a>
    """)
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": f"{workspace_name} archived — 90 days to restore",
        "html": html,
    })


async def send_workspace_subscription_confirmed_email(
    to_email: str, workspace_name: str,
) -> None:
    """First successful payment — welcome to paid Wheelhouse."""
    safe_name = _html_lib.escape(workspace_name)
    workspace_url = f"{APP_URL}/workspaces"
    html = _html(f"""
      <h1>You're in &mdash; {safe_name} is active</h1>
      <p>
        Payment received. Your <strong style="color:#2dd4bf;">{safe_name}</strong>
        Wheelhouse is now an active subscription. Your crew has
        uninterrupted access to shared chat, dossier, and handoff notes.
      </p>
      <p>
        You can manage billing, switch monthly &harr; annual, or update
        your payment method anytime from the workspace page.
      </p>
      <a href="{workspace_url}" class="cta">Open Workspace</a>
    """)
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": f"{workspace_name} Wheelhouse activated",
        "html": html,
    })


async def send_workspace_payment_failed_email(
    to_email: str, workspace_name: str,
) -> None:
    """invoice.payment_failed — card was declined."""
    safe_name = _html_lib.escape(workspace_name)
    workspaces_url = f"{APP_URL}/workspaces"
    html = _html(f"""
      <h1>Card declined for {safe_name}</h1>
      <p>
        We couldn't charge the card on file for your
        <strong style="color:#2dd4bf;">{safe_name}</strong> Wheelhouse.
        Stripe will retry the payment over the next two weeks.
      </p>
      <p>
        If the card has expired or changed, please update it now to avoid
        losing access. Your crew still has full access during this
        retry window.
      </p>
      <a href="{workspaces_url}" class="cta">Update Payment Method</a>
    """)
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": f"Card declined for {workspace_name}",
        "html": html,
    })


async def send_off_topic_abuse_alert(
    user_email: str, user_full_name: str, capped_days: int,
) -> None:
    """D6.58 — admin alert when a user hits their 3rd off-topic cap-day
    in any 30-day window.

    Recipient: Owner only (blakemarchal@gmail.com), per project standing
    rule on admin operational signals. Karynn doesn't want these.
    """
    safe_email = _html_lib.escape(user_email)
    safe_name = _html_lib.escape(user_full_name or "(no name)")
    admin_url = f"{APP_URL}/admin/users"
    html = _html(f"""
      <h1>Off-topic abuse threshold hit</h1>
      <p>
        User <strong style="color:#f0ece4;">{safe_name}</strong>
        (<code>{safe_email}</code>) has hit the off-topic daily cap
        (25 queries) on <strong>{capped_days}</strong> separate days
        within the last 30. Each cap-day suggests deliberate burn-
        through of free Haiku scope-check calls; sustained pattern is
        likely abuse.
      </p>
      <p>
        Their on-topic chat continues to work as normal. Off-topic
        queries today are returning a rate-limit message until UTC
        midnight rolls over.
      </p>
      <a href="{admin_url}" class="cta">Review user in admin</a>
      <p style="font-size:12px; color:rgba(107,117,148,0.7); margin-top:16px;">
        Decide manually whether to leave (accidental confusion?), warn,
        or hard-block the account. The off_topic_queries table has the
        full query log for context.
      </p>
    """)
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": ["blakemarchal@gmail.com"],
        "subject": (
            f"RegKnot — off-topic abuse threshold ({capped_days} cap-days/30) "
            f"— {user_email}"
        ),
        "html": html,
    })


async def send_workspace_invite_email(
    to_email: str,
    inviter_name: str,
    workspace_name: str,
    token: str,
    role: str,
) -> None:
    """Email a user an invite link to join a Wheelhouse workspace.

    The link lands on /invite/<token> in the web app, which handles
    both the "no account yet" (signup → auto-claim) and the "already
    have an account" (login → accept) paths. Sprint D6.53.

    The email is intentionally light — the invite landing page does
    the heavy lifting of explaining the workspace, the inviter, and
    what role they'll have. We don't want to repeat that copy in the
    email body.
    """
    invite_url = f"{APP_URL}/invite/{token}"
    safe_workspace = _html_lib.escape(workspace_name)
    safe_inviter = _html_lib.escape(inviter_name)
    role_label = "Admin" if role == "admin" else "Member"
    html = _html(f"""
      <h1>You've been invited to a Wheelhouse</h1>
      <p>
        <strong style="color:#f0ece4;">{safe_inviter}</strong> invited you to
        join <strong style="color:#2dd4bf;">{safe_workspace}</strong> on
        RegKnot &mdash; the maritime compliance co-pilot used by their crew.
      </p>
      <p>
        You'll join as a <strong style="color:#f0ece4;">{role_label}</strong>.
        Inside the workspace you'll have access to the vessel dossier,
        shared chat history, and crew-rotation handoff notes.
      </p>
      <a href="{invite_url}" class="cta">Accept Invite</a>
      <p style="font-size:12px; color:rgba(107,117,148,0.7); margin-top:4px;">
        Or copy this link into your browser:
      </p>
      <div class="token-box">{invite_url}</div>
      <p style="font-size:12px; color:rgba(107,117,148,0.6);">
        This invite expires in 14 days. If you weren't expecting it,
        you can safely ignore this email &mdash; nothing happens until
        you click the link.
      </p>
    """)
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": f"You're invited to {workspace_name} on RegKnot",
        "html": html,
    })


async def send_custom_email(to_email: str, subject: str, body_text: str) -> None:
    """Send an admin-composed custom email to a user.

    The body_text is plain text with line breaks preserved. It is rendered
    inside the standard RegKnot email template with the teal/dark styling.
    """
    safe_body = _html_lib.escape(body_text)
    html = _html(f"""
      <h1>{_html_lib.escape(subject)}</h1>
      <p style="white-space: pre-wrap; color: #f0ece4;">{safe_body}</p>
      <a href="{APP_URL}" class="cta">Open RegKnot</a>
    """)
    resend.Emails.send({
        "from": CAPTAIN_EMAIL,
        "to": [to_email],
        "subject": f"RegKnot — {subject}",
        "html": html,
    })


async def send_credential_expiry_email(
    to_email: str, full_name: str, credential_title: str, days_remaining: int,
) -> None:
    """Notify a user that a credential is expiring soon (or already expired)."""
    raw_first = full_name.split()[0] if full_name and full_name.strip() else "Mariner"
    first_name = _html_lib.escape(raw_first)
    safe_title = _html_lib.escape(credential_title)

    if days_remaining < 0:
        urgency = f'<span style="color:#f87171;">expired {abs(days_remaining)} day{"s" if abs(days_remaining) != 1 else ""} ago</span>'
        headline = f"Your {safe_title} has expired"
    elif days_remaining == 0:
        urgency = '<span style="color:#f87171;">expires today</span>'
        headline = f"Your {safe_title} expires today"
    elif days_remaining <= 7:
        urgency = f'<span style="color:#f87171;">expires in {days_remaining} day{"s" if days_remaining != 1 else ""}</span>'
        headline = f"Your {safe_title} expires in {days_remaining} days"
    elif days_remaining <= 30:
        urgency = f'<span style="color:#fbbf24;">expires in {days_remaining} days</span>'
        headline = f"Your {safe_title} expires in {days_remaining} days"
    else:
        urgency = f'<span style="color:#facc15;">expires in {days_remaining} days</span>'
        headline = f"Heads up: {safe_title} expires in {days_remaining} days"

    html = _html(f"""
      <h1>{headline}</h1>
      <p>Hey {first_name},</p>
      <div style="background-color:#0d1225; border:1px solid rgba(255,255,255,0.1); border-radius:10px; padding:20px; margin:16px 0;">
        <p style="color:#f0ece4; margin:0 0 8px; font-size:16px; font-weight:bold;">{safe_title}</p>
        <p style="margin:0; font-size:14px;">Status: {urgency}</p>
      </div>
      <p>
        Make sure your renewal is in progress to avoid lapses in your qualifications.
        You can manage all your credentials in RegKnot.
      </p>
      <a href="{APP_URL}/credentials" class="cta">View My Credentials</a>
      <p style="font-size:12px; color:rgba(107,117,148,0.7); margin-top:8px;">
        You can adjust reminder settings in your Account page.
      </p>
    """)
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": f"{headline} — RegKnot",
        "html": html,
    })


async def send_regulation_digest_email(
    to_email: str, full_name: str, updates: list[dict],
) -> None:
    """Send a digest of recent regulation changes.

    Each item in ``updates`` has keys: title, body, source, created_at.
    """
    raw_first = full_name.split()[0] if full_name and full_name.strip() else "Mariner"
    first_name = _html_lib.escape(raw_first)

    items_html = ""
    for u in updates:
        safe_title = _html_lib.escape(u.get("title", ""))
        safe_body = _html_lib.escape(u.get("body", ""))
        items_html += f"""
          <div style="background-color:#0d1225; border:1px solid rgba(255,255,255,0.08);
            border-radius:8px; padding:14px 16px; margin:10px 0;">
            <p style="color:#2dd4bf; font-size:13px; font-weight:bold; margin:0 0 6px;">{safe_title}</p>
            <p style="color:#f0ece4; font-size:13px; margin:0;">{safe_body}</p>
          </div>
        """

    count = len(updates)
    html = _html(f"""
      <h1>Regulation Update Digest</h1>
      <p>Hey {first_name} — here{"'s what" if count == 1 else " are the"} changed since your last digest:</p>
      {items_html}
      <a href="{APP_URL}" class="cta">Ask About These Changes</a>
      <p style="font-size:12px; color:rgba(107,117,148,0.7); margin-top:8px;">
        You can adjust digest frequency in your Account settings.
      </p>
    """)
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": f"{count} regulation update{'s' if count != 1 else ''} this week — RegKnot",
        "html": html,
    })


async def send_regulation_alert_email(
    to_email: str, full_name: str, source_label: str, summary: str,
) -> None:
    """Send an immediate alert when a regulation source is updated."""
    raw_first = full_name.split()[0] if full_name and full_name.strip() else "Mariner"
    first_name = _html_lib.escape(raw_first)
    safe_label = _html_lib.escape(source_label)
    safe_summary = _html_lib.escape(summary)

    html = _html(f"""
      <h1>{safe_label}</h1>
      <p>Hey {first_name},</p>
      <div style="background-color:#0d1225; border:1px solid rgba(45,212,191,0.2);
        border-radius:10px; padding:20px; margin:16px 0;">
        <p style="color:#f0ece4; margin:0; font-size:14px;">{safe_summary}</p>
      </div>
      <p>
        This regulation source has been updated in the RegKnot database.
        Ask me about the changes to understand how they affect your vessel.
      </p>
      <a href="{APP_URL}" class="cta">Ask About This Update</a>
      <p style="font-size:12px; color:rgba(107,117,148,0.7); margin-top:8px;">
        You're receiving this because you have alerts enabled for this regulation source.
        Adjust your alert preferences in Account settings.
      </p>
    """)
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": f"{source_label} — RegKnot",
        "html": html,
    })
