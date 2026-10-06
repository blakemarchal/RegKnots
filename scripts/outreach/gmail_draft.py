# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "google-auth-oauthlib>=1.2",
#     "google-api-python-client>=2.140",
# ]
# ///
"""Save outreach emails as Gmail drafts in blake@regknots.com, exactly as written.

The Gmail connector rewrites every link it saves into a google.com/url redirect, and clicking
one opens Google's "Redirect Notice" page. This script goes through the Gmail API directly, so
the link, the HTML and the branded signature stay as rendered here. It only creates and updates
drafts; Blake reviews and sends.

    uv run scripts/outreach/gmail_draft.py auth [--no-browser]
    uv run scripts/outreach/gmail_draft.py check
    uv run scripts/outreach/gmail_draft.py create email.json [--dry-run OUT_DIR]
    uv run scripts/outreach/gmail_draft.py update DRAFT_ID email.json

email.json holds the content; the script adds the offer link, the signature and the opt-out line:

    {
      "to": "info@example.com",
      "subject": "A Subchapter M question for Example Towing",
      "lead_id": "ob-0128",
      "paragraphs": ["One sentence about them.", "The hook question and answer."],
      "greeting": "optional; default 'Hello,' (e.g. 'Hi Dana,')",
      "cta": "optional; the sentence the link follows (default: the offer's own sentence)",
      "offer": "optional; fleet (default), practice, partner (see OFFERS), or none",
      "thread_id": "optional; the sent message's Gmail thread id, for a follow-up"
    }

"offer": "none" is a note to an existing user (2026-10-05): the same branded signature, but no
lead_id, no tracking link and no opt-out line. It may end with one plain link to a page on the
site: "link": "/login", with "cta" (the sentence before it) and "link_text". Any email may set
"signoff" (e.g. "Thanks for trying RegKnot,"), placed after the link, above the signature.

Credentials live outside the repo: the OAuth client in ~/.regknots/gmail_client.json and the
saved token in ~/.regknots/gmail_token.json (override with REGKNOTS_GMAIL_CLIENT and
REGKNOTS_GMAIL_TOKEN). Scopes: gmail.compose (drafts) and gmail.metadata (headers, to thread
follow-ups; no message bodies).
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from email.message import EmailMessage
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.metadata",
]
ACCOUNT = "blake@regknots.com"
FROM = f"Blake Marchal <{ACCOUNT}>"
SITE = "https://regknots.com"
LOGO = f"{SITE}/brand/logo-full-light.png"
LEAD_ID = re.compile(r"^ob-\d{4}$")

DEFAULT_CTA = (
    "RegKnot gives compliance answers in seconds with exact CFR and SOLAS citations, tailored "
    "to each boat, built with Captain Karynn Marchal, USCG Master Unlimited. Your first boat is "
    "free for 30 days on the fleet plan, no card needed:"
)
LINK_TEXT = "set up your first boat"

# 2026-10-02 — one offer per niche. fleet: towing companies, the fleet trial via the
# /fleet redirect. practice: schools, the free /practice page. partner: the
# Subchapter M TPOs, the landing page (/ redirects to /landing with the query).
OFFERS = {
    "fleet": {"path": "/fleet", "cta": DEFAULT_CTA, "link_text": LINK_TEXT, "expect": "redirect"},
    "practice": {
        "path": "/practice",
        "cta": (
            "We built a free practice page from the NMC's published sample exams: students pick a "
            "topic, answer 10 questions, and see the right answer and, where one applies, the regulation "
            "behind it. No sign-up, no ads:"
        ),
        "link_text": "open the practice questions",
        "expect": "ok",
    },
    "partner": {
        "path": "/",
        "cta": (
            "RegKnot gives compliance answers in seconds with exact CFR citations, tailored to each "
            "boat, built with Captain Karynn Marchal, USCG Master Unlimited. If it helps to look "
            "before we talk:"
        ),
        "link_text": "see RegKnot",
        "expect": "redirect",
    },
}
OPT_OUT = "If this isn't useful, reply 'no thanks' and I won't write again."
NOTE = "none"   # "offer": "none" — a note to an existing user, not outreach

CONFIG_DIR = Path.home() / ".regknots"
CLIENT_FILE = Path(os.environ.get("REGKNOTS_GMAIL_CLIENT", CONFIG_DIR / "gmail_client.json"))
TOKEN_FILE = Path(os.environ.get("REGKNOTS_GMAIL_TOKEN", CONFIG_DIR / "gmail_token.json"))


def offer_link(lead_id: str, offer: str = "fleet") -> str:
    """The one link in the email. /fleet redirects to the fleet-trial signup and adds the
    tracking tags; every link carries src=<lead id>, the signup attribution code."""
    return f"{SITE}{OFFERS[offer]['path']}?src={lead_id}"


def load_email(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    note = data.setdefault("offer", "fleet") == NOTE
    for key in ("to", "subject", "paragraphs") + (() if note else ("lead_id",)):
        if not data.get(key):
            sys.exit(f"{path}: missing {key!r}")
    if data.get("lead_id") and not LEAD_ID.match(data["lead_id"]):
        sys.exit(f"{path}: lead_id must look like ob-0128, got {data['lead_id']!r}")
    if not isinstance(data["paragraphs"], list) or not all(isinstance(p, str) for p in data["paragraphs"]):
        sys.exit(f"{path}: paragraphs must be a list of strings")
    if re.search(r"https?://|www\.", " ".join(data["paragraphs"] + [data.get(k, "") for k in ("cta", "greeting", "signoff")])):
        sys.exit(f"{path}: put no links in the text; the script adds the link")
    if not note and data["offer"] not in OFFERS:
        sys.exit(f"{path}: offer must be one of {', '.join(OFFERS)} or {NOTE}, got {data['offer']!r}")
    if note and data.get("link") and not re.fullmatch(r"/[\w\-/]*", data["link"]):
        sys.exit(f"{path}: link must be a path on the site such as /login, got {data['link']!r}")
    return data


def closing(data: dict) -> tuple[str, str, str] | None:
    """(sentence, url, link text) for the email's one link: the offer link, or for a note
    its optional plain site link; None for a note without one."""
    if data.get("offer") == NOTE:
        if not data.get("link"):
            return None
        return data.get("cta") or "", f"{SITE}{data['link']}", data.get("link_text") or "open RegKnot"
    offer = OFFERS[data.get("offer", "fleet")]
    return data.get("cta") or offer["cta"], offer_link(data["lead_id"], data["offer"]), offer["link_text"]


def render_text(data: dict) -> str:
    end = closing(data)
    parts = [data.get("greeting") or "Hello,", *data["paragraphs"]]
    if end:
        sentence, url, link_text = end
        # a note names its link in the text ("… open RegKnot: https://…"); outreach keeps "<cta> <url>"
        parts.append((f"{sentence} {link_text}: {url}" if data.get("offer") == NOTE else f"{sentence} {url}").strip())
    if data.get("signoff"):
        parts.append(data["signoff"])
    signature = "\n".join([
        "Blake Marchal",
        "Co-founder, RegKnot",
        "regknots.com · hello@regknots.com",
        "20 N Sandpiper St, La Marque, TX 77568",
    ])
    footer = [] if data.get("offer") == NOTE else [OPT_OUT]
    return "\n\n".join(parts + [signature, *footer]) + "\n"


def render_html(data: dict) -> str:
    esc = html.escape
    end = closing(data)
    p = '<p style="margin:0 0 14px 0;">{}</p>'
    body = [p.format(esc(data.get("greeting") or "Hello,"))]
    body += [p.format(esc(text)) for text in data["paragraphs"]]
    if end:
        sentence, url, link_text = end
        body.append(p.format(
            f'{esc(sentence)} <a href="{esc(url, quote=True)}" style="color:#0f766e;font-weight:bold;">'
            f'{esc(link_text)}</a>.'.lstrip()
        ))
    if data.get("signoff"):
        body.append(p.format(esc(data["signoff"])))
    signature = f"""\
<table cellpadding="0" cellspacing="0" border="0" style="margin:22px 0 16px 0;border-collapse:collapse;">
  <tr>
    <td style="padding:0 14px 0 0;vertical-align:middle;">
      <a href="{SITE}"><img src="{LOGO}" width="160" height="40" alt="RegKnot" style="display:block;border:0;"></a>
    </td>
    <td style="border-left:2px solid #2dd4bf;padding:0 0 0 14px;vertical-align:middle;font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:1.5;color:#374151;">
      <strong style="font-size:14px;color:#0b1220;">Blake Marchal</strong><br>
      Co-founder, RegKnot<br>
      <a href="{SITE}" style="color:#0f766e;text-decoration:none;">regknots.com</a> &middot; <a href="mailto:hello@regknots.com" style="color:#0f766e;text-decoration:none;">hello@regknots.com</a><br>
      <span style="color:#6b7280;">20 N Sandpiper St, La Marque, TX 77568</span>
    </td>
  </tr>
</table>"""
    footer = "" if data.get("offer") == NOTE else f'<p style="margin:0;font-size:12px;color:#6b7280;">{esc(OPT_OUT)}</p>'
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.55;color:#1f2937;">'
        + "".join(body) + signature + footer + "</div>"
    )


def build_message(data: dict, reply_headers: dict | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = FROM
    msg["To"] = data["to"]
    subject = data["subject"]
    if reply_headers:
        if not subject.lower().startswith("re:"):
            subject = f"Re: {reply_headers.get('Subject') or subject}"
        msg["In-Reply-To"] = reply_headers["Message-ID"]
        msg["References"] = " ".join(
            x for x in (reply_headers.get("References"), reply_headers["Message-ID"]) if x
        )
    msg["Subject"] = subject
    msg.set_content(render_text(data), cte="quoted-printable")
    msg.add_alternative(render_html(data), subtype="html", cte="quoted-printable")
    return msg


def credentials(open_browser: bool = True):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not CLIENT_FILE.exists():
            sys.exit(f"No OAuth client at {CLIENT_FILE}. Create a Desktop OAuth client in the "
                     "regknots-outreach Google Cloud project and save its JSON there.")
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
        creds = flow.run_local_server(
            port=0,
            open_browser=open_browser,
            login_hint=ACCOUNT,
            authorization_prompt_message="Open this URL signed in as blake@regknots.com:\n{url}\n",
        )
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return creds


def gmail(open_browser: bool = True):
    from googleapiclient.discovery import build

    service = build("gmail", "v1", credentials=credentials(open_browser), cache_discovery=False)
    email = service.users().getProfile(userId="me").execute()["emailAddress"]
    if email.lower() != ACCOUNT:
        sys.exit(f"Signed in as {email}; drafts must go into {ACCOUNT}. Delete {TOKEN_FILE} and re-run auth.")
    return service


def check_link_live(data: dict) -> None:
    """Refuse to draft an email whose link would not work: /fleet and / must redirect,
    /practice must answer 200, a note's site link must answer 200 or redirect."""

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    redirects = (301, 302, 307, 308)
    if data.get("offer") == NOTE:
        if not data.get("link"):
            return
        url, want = f"{SITE}{data['link']}", (200, *redirects)
    else:
        offer = data.get("offer", "fleet")
        url = offer_link("ob-0000", offer)
        want = redirects if OFFERS[offer]["expect"] == "redirect" else (200,)
    opener = urllib.request.build_opener(NoRedirect)
    try:
        opener.open(urllib.request.Request(url, method="HEAD"), timeout=15)
        status = 200
    except urllib.error.HTTPError as exc:
        status = exc.code
    if status not in want:
        sys.exit(f"{url} answered {status}, expected {' or '.join(map(str, want))}; deploy it first.")


def reply_headers_for(service, thread_id: str) -> dict:
    thread = service.users().threads().get(
        userId="me", id=thread_id, format="metadata",
        metadataHeaders=["Message-ID", "Subject", "References"],
    ).execute()
    last = thread["messages"][-1]
    headers = {h["name"].title().replace("Message-Id", "Message-ID"): h["value"]
               for h in last["payload"].get("headers", [])}
    if "Message-ID" not in headers:
        sys.exit(f"Thread {thread_id}: no Message-ID on its last message; can't thread the follow-up.")
    return headers


def save_draft(data: dict, draft_id: str | None) -> None:
    check_link_live(data)
    service = gmail()
    reply = reply_headers_for(service, data["thread_id"]) if data.get("thread_id") else None
    message = {"raw": base64.urlsafe_b64encode(build_message(data, reply).as_bytes()).decode()}
    if data.get("thread_id"):
        message["threadId"] = data["thread_id"]
    drafts = service.users().drafts()
    if draft_id:
        draft = drafts.update(userId="me", id=draft_id, body={"id": draft_id, "message": message}).execute()
    else:
        draft = drafts.create(userId="me", body={"message": message}).execute()
    print(json.dumps({"draft_id": draft["id"], "thread_id": draft["message"].get("threadId"),
                      "to": data["to"], "lead_id": data.get("lead_id")}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    auth = sub.add_parser("auth", help="sign in once and save the token")
    auth.add_argument("--no-browser", action="store_true", help="print the URL instead of opening a browser")
    sub.add_parser("check", help="confirm the saved token works and belongs to blake@regknots.com")
    create = sub.add_parser("create", help="create a draft from email.json")
    create.add_argument("email_json")
    create.add_argument("--dry-run", metavar="OUT_DIR", help="write the rendered .txt/.html/.eml, touch nothing")
    update = sub.add_parser("update", help="replace an existing draft's content")
    update.add_argument("draft_id")
    update.add_argument("email_json")
    args = parser.parse_args()

    if args.cmd == "auth":
        gmail(open_browser=not args.no_browser)
        print(f"Signed in as {ACCOUNT}; token saved to {TOKEN_FILE}")
    elif args.cmd == "check":
        gmail(open_browser=False)
        print(f"OK: {ACCOUNT}")
    elif args.cmd == "create" and args.dry_run:
        data = load_email(args.email_json)
        out = Path(args.dry_run)
        out.mkdir(parents=True, exist_ok=True)
        stem = data.get("lead_id") or "note"
        (out / f"{stem}.txt").write_text(render_text(data), encoding="utf-8")
        (out / f"{stem}.html").write_text(render_html(data), encoding="utf-8")
        (out / f"{stem}.eml").write_bytes(build_message(data).as_bytes())
        print(f"Wrote {out / stem}.txt, .html and .eml")
    elif args.cmd == "create":
        save_draft(load_email(args.email_json), None)
    elif args.cmd == "update":
        save_draft(load_email(args.email_json), args.draft_id)


if __name__ == "__main__":
    main()
