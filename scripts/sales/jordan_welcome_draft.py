# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "google-auth-oauthlib>=1.2",
#     "google-api-python-client>=2.140",
# ]
# ///
"""The welcome email to Jordan Hall, as a Gmail draft in blake@regknots.com with
the fleet one-pager attached (2026-10-16). Drafts only; Blake sends.

    uv run scripts/sales/jordan_welcome_draft.py [--to jordan@example.com]

Without --to the draft has no recipient; Blake fills it in.
"""
import argparse
import base64
import sys
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "outreach"))
import gmail_draft  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ONE_PAGER = ROOT / "docs" / "sales" / "regknot-fleet-one-pager.pdf"
LINK = "regknots.com/fleet?src=pilot-jordan"

TEXT = f"""Hi Jordan,

I'm glad you're in. Everything you need is below, and the one-page leave-behind is attached.

YOUR LINK
{LINK}
Every fleet that starts from this link is yours, and it gives them 90 days free instead of the usual 30.

THE DEAL, BETWEEN FRIENDS
- 25% of what any fleet you bring in pays us, for as long as they keep paying. Paid monthly, as the money arrives.
- Once your fleets have 10 boats paying, we sit down and talk about equity. Karynn's in that conversation.
- No quotas, no exclusivity, no notice. Either of us can stop anytime; what's already paying keeps paying you.

WHAT YOU'RE SELLING
Wheelhouse, the fleet version of RegKnot: one subscription per boat, up to 10 crew on each. The crew asks a compliance question and gets the answer from the regulation text with the exact citation, set up for that boat. The company's own safety manual (TSMS) lives in the same chat, and an audit log shows who asked what, with citations. Built with Karynn, a USCG Master Unlimited.

Pricing per boat, per month:
- 1 to 4 boats: $99.99 ($89.99 billed annually)
- 5 to 9 boats: $89.99 ($80.99 annually), code FLEET5 at checkout
- 10 or more:   $79.99 ($71.99 annually), code FLEET10 at checkout
Bigger fleets or one invoice for the whole company: we quote it.

WHO TO TALK TO
Subchapter M towing companies with 3 to 30 boats: the owner, the safety manager or the DPA. The fastest way in is whoever already knows them: marine insurance brokers and underwriters, the TPOs that audit them, maritime lawyers and surveyors, towing associations. You don't need to be maritime; you need to know people, and you do.

THE CAPTAIN
Anyone who wants to hear it from Karynn can: captain@regknots.com goes straight to her. Use it.

NEXT STEPS
1. Sign up through your own link. That's the live test of the whole funnel, and I'll watch it land.
2. I'll add you to the demo fleet, Gulf Coast Marine Towing: a boat, a crew, a TSMS and real answers, so you can run a demo on your own.
3. Read the attached one-pager; the full playbook comes with the demo access.
4. Call me with the first prospect. We'll do that demo together, with Karynn when she's reachable.

Thank you for doing this.

Blake
blake@regknots.com
"""

HTML = f"""<!doctype html><html><body style="margin:0;padding:0;background:#f4f5f7;font-family:Georgia,'Times New Roman',serif;color:#1b2130;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f5f7;padding:28px 12px;"><tr><td align="center">
<table role="presentation" width="600" cellspacing="0" cellpadding="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:14px;overflow:hidden;">
<tr><td style="background:#0a0e1a;padding:26px 32px;">
  <span style="font-family:Arial Narrow,Arial,sans-serif;font-weight:800;font-size:22px;letter-spacing:3px;color:#f0ece4;">REG<span style="color:#2dd4bf;">KNOT</span></span>
  <span style="font-family:Arial,sans-serif;font-size:10px;letter-spacing:3px;color:#8a94ad;margin-left:10px;">MARITIME COMPLIANCE CO-PILOT</span>
</td></tr>
<tr><td style="padding:30px 32px 8px;font-size:17px;line-height:1.55;">
  <p style="margin:0 0 14px;">Hi Jordan,</p>
  <p style="margin:0 0 14px;">I'm glad you're in. Everything you need is below, and the one-page leave-behind is attached.</p>
</td></tr>

<tr><td style="padding:6px 32px;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#0d1225;border-radius:12px;"><tr><td style="padding:18px 22px;">
    <p style="margin:0 0 6px;font-family:Arial,sans-serif;font-size:11px;letter-spacing:3px;color:#2dd4bf;">YOUR LINK</p>
    <p style="margin:0 0 8px;font-family:Consolas,Menlo,monospace;font-size:19px;color:#ffffff;"><a href="https://{LINK}" style="color:#ffffff;text-decoration:none;">{LINK}</a></p>
    <p style="margin:0;font-family:Arial,sans-serif;font-size:13px;line-height:1.5;color:#a8b0c4;">Every fleet that starts from this link is yours, and it gives them <b style="color:#f0ece4;">90 days free</b> instead of the usual 30.</p>
  </td></tr></table>
</td></tr>

<tr><td style="padding:22px 32px 4px;">
  <h2 style="margin:0 0 10px;font-family:Arial Narrow,Arial,sans-serif;font-size:22px;color:#0a0e1a;">The deal, between friends</h2>
  <table role="presentation" cellspacing="0" cellpadding="0" style="font-size:16px;line-height:1.5;">
    <tr><td style="padding:4px 10px 4px 0;color:#2dd4bf;font-weight:bold;vertical-align:top;">25%</td><td style="padding:4px 0;">of what any fleet you bring in pays us, <b>for as long as they keep paying</b>. Paid monthly, as the money arrives.</td></tr>
    <tr><td style="padding:4px 10px 4px 0;color:#2dd4bf;font-weight:bold;vertical-align:top;">10</td><td style="padding:4px 0;">boats paying across your fleets, and we sit down and talk about equity. Karynn's in that conversation.</td></tr>
    <tr><td style="padding:4px 10px 4px 0;color:#2dd4bf;font-weight:bold;vertical-align:top;">0</td><td style="padding:4px 0;">quotas, exclusivity or notice. Either of us can stop anytime; what's already paying keeps paying you.</td></tr>
  </table>
</td></tr>

<tr><td style="padding:22px 32px 4px;">
  <h2 style="margin:0 0 10px;font-family:Arial Narrow,Arial,sans-serif;font-size:22px;color:#0a0e1a;">What you're selling</h2>
  <p style="margin:0 0 12px;font-size:16px;line-height:1.55;"><b>Wheelhouse</b>, the fleet version of RegKnot: one subscription per boat, up to 10 crew on each. The crew asks a compliance question and gets the answer from the regulation text with the exact citation, set up for that boat. The company's own safety manual lives in the same chat, and an audit log shows who asked what, with citations. Built with Karynn, a USCG Master Unlimited.</p>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="font-family:Arial,sans-serif;font-size:14px;border-collapse:collapse;">
    <tr style="color:#6b7594;font-size:11px;letter-spacing:2px;"><td style="padding:6px 8px;border-bottom:1px solid #e3e6ec;">PER BOAT, PER MONTH</td><td style="padding:6px 8px;border-bottom:1px solid #e3e6ec;">MONTHLY</td><td style="padding:6px 8px;border-bottom:1px solid #e3e6ec;">ANNUAL</td><td style="padding:6px 8px;border-bottom:1px solid #e3e6ec;">CODE</td></tr>
    <tr><td style="padding:8px;">1 to 4 boats</td><td style="padding:8px;">$99.99</td><td style="padding:8px;">$89.99</td><td style="padding:8px;color:#6b7594;">standard</td></tr>
    <tr style="background:#f4f5f7;"><td style="padding:8px;">5 to 9 boats</td><td style="padding:8px;">$89.99</td><td style="padding:8px;">$80.99</td><td style="padding:8px;font-family:Consolas,Menlo,monospace;color:#0f766e;">FLEET5</td></tr>
    <tr><td style="padding:8px;">10 or more</td><td style="padding:8px;">$79.99</td><td style="padding:8px;">$71.99</td><td style="padding:8px;font-family:Consolas,Menlo,monospace;color:#0f766e;">FLEET10</td></tr>
  </table>
  <p style="margin:10px 0 0;font-size:14px;color:#4b5563;">The code goes in at checkout and stays for the life of the subscription. Bigger fleets, or one invoice for the whole company: we quote it.</p>
</td></tr>

<tr><td style="padding:22px 32px 4px;">
  <h2 style="margin:0 0 10px;font-family:Arial Narrow,Arial,sans-serif;font-size:22px;color:#0a0e1a;">Who to talk to</h2>
  <p style="margin:0;font-size:16px;line-height:1.55;">Subchapter M towing companies with 3 to 30 boats: the owner, the safety manager or the DPA. The fastest way in is whoever already knows them: marine insurance brokers and underwriters, the TPOs that audit them, maritime lawyers and surveyors, towing associations. You don't need to be maritime. You need to know people, and you do.</p>
</td></tr>

<tr><td style="padding:22px 32px 4px;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-left:4px solid #2dd4bf;background:#f0fdfa;border-radius:0 10px 10px 0;"><tr><td style="padding:14px 18px;font-size:16px;line-height:1.5;">
    <b>The captain.</b> Anyone who wants to hear it from Karynn can: <a href="mailto:captain@regknots.com" style="color:#0f766e;">captain@regknots.com</a> goes straight to her. Use it.
  </td></tr></table>
</td></tr>

<tr><td style="padding:22px 32px 8px;">
  <h2 style="margin:0 0 10px;font-family:Arial Narrow,Arial,sans-serif;font-size:22px;color:#0a0e1a;">Next steps</h2>
  <table role="presentation" cellspacing="0" cellpadding="0" style="font-size:16px;line-height:1.5;">
    <tr><td style="padding:5px 12px 5px 0;vertical-align:top;"><span style="display:inline-block;width:26px;height:26px;border-radius:13px;background:#0a0e1a;color:#2dd4bf;text-align:center;line-height:26px;font-family:Arial,sans-serif;font-weight:bold;font-size:14px;">1</span></td><td style="padding:5px 0;"><b>Sign up through your own link.</b> That's the live test of the whole funnel, and I'll watch it land.</td></tr>
    <tr><td style="padding:5px 12px 5px 0;vertical-align:top;"><span style="display:inline-block;width:26px;height:26px;border-radius:13px;background:#0a0e1a;color:#2dd4bf;text-align:center;line-height:26px;font-family:Arial,sans-serif;font-weight:bold;font-size:14px;">2</span></td><td style="padding:5px 0;"><b>I'll add you to the demo fleet</b>, Gulf Coast Marine Towing: a boat, a crew, a TSMS and real answers, so you can run a demo on your own.</td></tr>
    <tr><td style="padding:5px 12px 5px 0;vertical-align:top;"><span style="display:inline-block;width:26px;height:26px;border-radius:13px;background:#0a0e1a;color:#2dd4bf;text-align:center;line-height:26px;font-family:Arial,sans-serif;font-weight:bold;font-size:14px;">3</span></td><td style="padding:5px 0;"><b>Read the attached one-pager.</b> The full playbook comes with the demo access.</td></tr>
    <tr><td style="padding:5px 12px 5px 0;vertical-align:top;"><span style="display:inline-block;width:26px;height:26px;border-radius:13px;background:#0a0e1a;color:#2dd4bf;text-align:center;line-height:26px;font-family:Arial,sans-serif;font-weight:bold;font-size:14px;">4</span></td><td style="padding:5px 0;"><b>Call me with the first prospect.</b> We'll do that demo together, with Karynn when she's reachable.</td></tr>
  </table>
</td></tr>

<tr><td style="padding:14px 32px 30px;font-size:17px;line-height:1.55;">
  <p style="margin:0 0 14px;">Thank you for doing this.</p>
  <p style="margin:0;">Blake<br><span style="font-size:14px;color:#6b7594;">blake@regknots.com</span></p>
</td></tr>
<tr><td style="background:#0a0e1a;padding:14px 32px;font-family:Arial,sans-serif;font-size:11px;color:#6b7594;">RegKnot &middot; La Marque, Texas &middot; regknots.com</td></tr>
</table>
</td></tr></table>
</body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", default="")
    a = ap.parse_args()
    msg = EmailMessage()
    msg["From"] = gmail_draft.FROM
    if a.to:
        msg["To"] = a.to
    msg["Subject"] = "Welcome aboard, Jordan: your link, the deal, and where to start"
    msg.set_content(TEXT)
    msg.add_alternative(HTML, subtype="html")
    msg.add_attachment(ONE_PAGER.read_bytes(), maintype="application", subtype="pdf", filename="RegKnot-for-fleets.pdf")
    service = gmail_draft.gmail()
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    draft = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    print(f"draft {draft['id']}: to={a.to or '(blank: fill in)'}, one-pager attached")


if __name__ == "__main__":
    main()
