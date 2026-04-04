import resend
from app.config import settings

resend.api_key = settings.resend_api_key

FROM_EMAIL = "RegKnots <hello@mail.regknots.com>"
CAPTAIN_EMAIL = "RegKnots <captain@regknots.com>"
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
        <span class="logo-text">Reg<span>Knots</span></span>
      </div>
      {body}
      <hr class="divider">
      <p class="disclaimer">
        RegKnots is a navigation aid only — not legal advice. Always verify compliance requirements with
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
        You're now registered with RegKnots — your AI-powered CFR co-pilot for U.S. maritime compliance.
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


async def send_password_reset_email(to_email: str, reset_token: str) -> None:
    reset_url = f"{APP_URL}/reset-password?token={reset_token}"
    html = _html(f"""
      <h1>Reset your password</h1>
      <p>
        We received a request to reset the password for your RegKnots account.
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
        "subject": "Reset your RegKnots password",
        "html": html,
    })


async def send_trial_expiring_email(to_email: str, full_name: str, messages_used: int) -> None:
    first_name = full_name.split()[0] if full_name.strip() else "Mariner"
    html = _html(f"""
      <h1>Your trial ends in 3 days</h1>
      <p>
        Hey {first_name} — just a heads up that your RegKnots trial expires in 3 days.
        You've sent <strong style="color:#f0ece4;">{messages_used}</strong> messages so far.
      </p>
      <p>
        To keep your access to unlimited CFR queries, vessel-specific answers, and all regulation
        sources, subscribe to RegKnots Pro for <strong style="color:#f0ece4;">$49/month</strong>.
      </p>
      <p style="font-size:13px; color:#2dd4bf;">
        As a pilot member, this price is locked in forever — even when we raise it.
      </p>
      <a href="{APP_URL}/pricing" class="cta">Subscribe Now</a>
    """)
    resend.Emails.send({
        "from": CAPTAIN_EMAIL,
        "to": [to_email],
        "subject": "Your RegKnots trial ends in 3 days",
        "html": html,
    })


async def send_subscription_confirmed_email(to_email: str, full_name: str) -> None:
    first_name = full_name.split()[0] if full_name.strip() else "Mariner"
    html = _html(f"""
      <h1>Welcome to RegKnots Pro</h1>
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
        Your $49/month pilot price is locked in forever — even when we raise it.
      </p>
      <a href="{APP_URL}" class="cta">Start Asking Questions</a>
    """)
    resend.Emails.send({
        "from": CAPTAIN_EMAIL,
        "to": [to_email],
        "subject": f"Welcome to RegKnots Pro, {first_name}",
        "html": html,
    })
