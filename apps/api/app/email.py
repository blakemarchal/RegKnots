import html as _html_lib

import resend
from app.config import settings

resend.api_key = settings.resend_api_key

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
    first_name = full_name.split()[0] if full_name.strip() else "Mariner"
    html = _html(f"""
      <h1>Welcome aboard, {first_name}</h1>
      <p>
        You're now registered with RegKnot — your AI-powered CFR co-pilot for U.S. maritime compliance.
        Get instant cited answers to questions across Titles 33, 46 &amp; 49, COLREGs, and NVICs, tailored
        to your vessel profile.
      </p>
      <p>
        Ask about inspection schedules, certificate requirements, carriage requirements, SOLAS
        applicability, and more — all cited to the exact regulation you can verify on eCFR.
      </p>
      <a href="{APP_URL}" class="cta">Start Asking Questions</a>
      <p style="font-size:12px; color:rgba(107,117,148,0.7); margin-top:8px;">
        Set up your vessel profile first for the most accurate answers.
      </p>
    """)
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": f"Welcome aboard, {first_name}",
        "html": html,
    })


async def send_verification_email(to_email: str, full_name: str, token: str) -> None:
    first_name = full_name.split()[0] if full_name and full_name.strip() else "Mariner"
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
    first_name = full_name.split()[0] if full_name and full_name.strip() else "Mariner"
    html = _html(f"""
      <h1>We got your message, {first_name}</h1>
      <p>
        Your support request has been received:
      </p>
      <div class="token-box" style="color:#f0ece4; border-color:rgba(255,255,255,0.1);">
        <strong>Subject:</strong> {subject}
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
    first_name = full_name.split()[0] if full_name and full_name.strip() else "Mariner"
    html = _html(f"""
      <h1>Password changed</h1>
      <p>
        Hey {first_name} — this is a confirmation that the password for your RegKnot account
        (<strong style="color:#f0ece4;">{to_email}</strong>) was just changed.
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
    first_name = full_name.split()[0] if full_name.strip() else "Mariner"
    html = _html(f"""
      <h1>Your trial ends in 3 days</h1>
      <p>
        Hey {first_name} — just a heads up that your RegKnot trial expires in 3 days.
        You've sent <strong style="color:#f0ece4;">{messages_used}</strong> messages so far.
      </p>
      <p>
        To keep your access to unlimited CFR queries, vessel-specific answers, and all regulation
        sources, subscribe to RegKnot Pro for <strong style="color:#f0ece4;">$39/month</strong>.
      </p>
      <p style="font-size:13px; color:#2dd4bf;">
        As a pilot member, this price is locked in forever — even when we raise it.
      </p>
      <a href="{APP_URL}/pricing" class="cta">Subscribe Now</a>
    """)
    resend.Emails.send({
        "from": CAPTAIN_EMAIL,
        "to": [to_email],
        "subject": "Your RegKnot trial ends in 3 days",
        "html": html,
    })


async def send_pilot_ended_email(to_email: str, full_name: str) -> None:
    first_name = full_name.split()[0] if full_name.strip() else "Mariner"
    html = _html(f"""
      <h1>Your pilot trial has ended</h1>
      <p>
        Hey {first_name} — your 14-day RegKnot pilot has expired. You've reached the end of your
        complimentary access period.
      </p>
      <p>
        To continue getting instant cited answers to CFR, COLREGs, NVIC, and SOLAS questions —
        subscribe to RegKnot Pro for <strong style="color:#f0ece4;">$39/month</strong>.
      </p>
      <p style="font-size:13px; color:#2dd4bf;">
        As a founding pilot member, this price is locked in forever — even when we raise it.
      </p>
      <a href="{APP_URL}/pricing" class="cta">Subscribe to Pro</a>
      <p style="font-size:12px; color:rgba(107,117,148,0.7); margin-top:8px;">
        Questions? Reply to this email — we read every message.
      </p>
    """)
    resend.Emails.send({
        "from": CAPTAIN_EMAIL,
        "to": [to_email],
        "subject": f"Your RegKnot trial has ended, {first_name}",
        "html": html,
    })


async def send_waitlist_confirmed_email(to_email: str, full_name: str) -> None:
    first_name = full_name.split()[0] if full_name.strip() else "Mariner"
    html = _html(f"""
      <h1>You're on the list, {first_name}</h1>
      <p>
        Thanks for your interest in RegKnot. You've been added to our waitlist and we'll notify you
        as soon as a spot opens up.
      </p>
      <p>
        In the meantime, here's what you can look forward to: instant cited answers across
        CFR Titles 33, 46 &amp; 49, COLREGs, NVICs, and SOLAS 2024 — all tailored to your
        vessel profile.
      </p>
      <p style="font-size:13px; color:#2dd4bf;">
        Waitlist members get priority access and founding member pricing when we open up.
      </p>
      <a href="{APP_URL}" class="cta">Learn More</a>
    """)
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": f"You're on the RegKnot waitlist, {first_name}",
        "html": html,
    })


async def send_subscription_cancelled_email(to_email: str, full_name: str) -> None:
    first_name = full_name.split()[0] if full_name.strip() else "Mariner"
    html = _html(f"""
      <h1>Your subscription has been cancelled</h1>
      <p>
        Hi {first_name} — your RegKnot Pro subscription has been cancelled.
        You'll continue to have Pro access until the end of your current billing period.
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


async def send_subscription_confirmed_email(to_email: str, full_name: str) -> None:
    first_name = full_name.split()[0] if full_name.strip() else "Mariner"
    html = _html(f"""
      <h1>Welcome to RegKnot Pro</h1>
      <p>
        Thanks for subscribing, {first_name}! Your Pro plan is now active.
      </p>
      <p>
        Here's what you get:
      </p>
      <ul style="padding-left:20px; margin:0 0 16px;">
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">Unlimited questions — no message caps</li>
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">CFR Titles 33, 46 &amp; 49 + COLREGs, NVICs &amp; SOLAS 2024</li>
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">Vessel-specific compliance answers</li>
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">Audit-ready chat logs</li>
      </ul>
      <p style="font-size:13px; color:#2dd4bf;">
        Your $39/month founding member price is locked in forever — even when we raise it.
      </p>
      <a href="{APP_URL}" class="cta">Start Asking Questions</a>
    """)
    resend.Emails.send({
        "from": CAPTAIN_EMAIL,
        "to": [to_email],
        "subject": f"Welcome to RegKnot Pro, {first_name}",
        "html": html,
    })


async def send_payment_failed_email(to_email: str, full_name: str) -> None:
    first_name = full_name.split()[0] if full_name.strip() else "Mariner"
    html = _html(f"""
      <h1>Action Required: Payment Failed</h1>
      <p>
        Hi {first_name} — we were unable to process your latest RegKnot Pro payment.
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


async def send_subscription_paused_email(to_email: str, full_name: str) -> None:
    first_name = full_name.split()[0] if full_name.strip() else "Mariner"
    html = _html(f"""
      <h1>Your Subscription is Paused</h1>
      <p>
        Hi {first_name} — your RegKnot Pro subscription has been paused.
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
    website_html = (
        f'<p><strong>Website:</strong> <a href="{website}">{website}</a></p>'
        if website else ""
    )
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": ["hello@regknots.com"],
        "reply_to": user_email,
        "subject": f"[Charity Suggestion] {org_name}",
        "html": (
            f"<h2>New Charity Partner Suggestion</h2>"
            f"<p><strong>From:</strong> {user_email}</p>"
            f"<p><strong>Organization:</strong> {org_name}</p>"
            f"{website_html}"
            f"<hr>"
            f"<p><strong>Why this organization:</strong></p>"
            f"<p>{reason}</p>"
        ),
    })


def render_founding_member_email(full_name: str | None) -> tuple[str, str]:
    """Return (subject, html) for the founding member announcement email.

    Used by both the send function and the admin preview endpoint.
    """
    raw_first = (full_name or "").split()[0] if (full_name or "").strip() else ""
    first_name = _html_lib.escape(raw_first) if raw_first else "Captain"
    subject = "Your RegKnot Pro access is ready"
    html = _html(f"""
      <h1>Hi {first_name},</h1>
      <p>
        Thank you for being one of the first mariners to try RegKnot during our pilot.
        Your questions, feedback, and patience while we tuned things have shaped this
        product in ways we couldn&rsquo;t have done alone.
      </p>
      <p>
        RegKnot Pro is now live &mdash; and because you were here from the beginning,
        you get to lock in the founding member rate:
        <strong style="color:#f0ece4;">$39/month</strong>
        (or save 26% with the annual plan at
        <strong style="color:#f0ece4;">$29/month</strong>, billed
        <strong style="color:#f0ece4;">$348/year</strong>).
        Even when we raise prices down the road, your rate stays the same.
      </p>
      <p style="color:#f0ece4; font-weight:700; margin-top:24px; margin-bottom:8px;">
        What you get with Pro:
      </p>
      <ul style="padding-left:20px; margin:0 0 16px;">
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">
          Unlimited compliance questions across CFR, SOLAS, COLREGs, STCW, NVICs, and ISM
        </li>
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">
          Cited, regulation-backed answers you can trust
        </li>
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">
          Vessel-aware context that remembers your ship&rsquo;s profile
        </li>
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">
          Real-time progress tracking as your question is researched across regulations
        </li>
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">
          Export your chat history for personal records
        </li>
        <li style="color:#6b7594; font-size:14px; line-height:1.7;">
          Enterprise subdomains for fleet-wide deployment
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
        Waves of Impact, and Elijah Rising. When you subscribe, you&rsquo;re not just
        getting a tool. You&rsquo;re supporting organizations that serve the maritime
        community.
        <a href="{APP_URL}/giving" style="color:#2dd4bf; text-decoration:none;">Learn more &rarr;</a>
      </p>
      <p>
        Your trial is still active, so there&rsquo;s no rush. But when you&rsquo;re
        ready, you can upgrade in the app:
      </p>
      <a href="{APP_URL}/pricing" class="cta">Upgrade to Pro</a>
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


async def send_subscription_resumed_email(to_email: str, full_name: str) -> None:
    first_name = full_name.split()[0] if full_name.strip() else "Mariner"
    html = _html(f"""
      <h1>Welcome Back, {first_name}!</h1>
      <p>
        Your RegKnot Pro subscription has been resumed. Full access is restored —
        unlimited questions, vessel-specific answers, and all regulation sources
        are available again.
      </p>
      <a href="{APP_URL}" class="cta">Start Asking Questions</a>
    """)
    resend.Emails.send({
        "from": CAPTAIN_EMAIL,
        "to": [to_email],
        "subject": f"RegKnot — Welcome Back! Subscription Resumed",
        "html": html,
    })
