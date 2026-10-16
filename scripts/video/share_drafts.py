# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "google-auth-oauthlib>=1.2",
#     "google-api-python-client>=2.140",
# ]
# ///
"""Gmail drafts in blake@regknots.com with the finished ads attached, for Karynn
(2026-10-16). Drafts only; Blake sends. Gmail takes about 25 MB per message, so
three drafts: the main ad in Chris, the main ad in River, and the four 15 s cuts.

    uv run scripts/video/share_drafts.py [--to kdmarchal@gmail.com]

Reuses scripts/outreach/gmail_draft.py's sign-in (token in ~/.regknots/).
"""
import argparse
import base64
import sys
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "outreach"))
import gmail_draft  # noqa: E402

SHARE = Path(__file__).resolve().parents[2] / "data" / "video" / "out" / "share"

DRAFTS = [
    ("RegKnot ad, 45 s (Chris narrating)", ["RegKnot_main_45s_AI-voice-Chris_vertical.mp4"],
     "the 45-second ad with the male narrator (Chris)"),
    ("RegKnot ad, 45 s (River narrating)", ["RegKnot_main_45s_AI-voice-River_vertical.mp4"],
     "the same 45-second ad with the other narrator (River)"),
    ("RegKnot ads, the two 15-second cuts", [
        "RegKnot_first-trip_15s_AI-voice-Chris_vertical.mp4", "RegKnot_first-trip_15s_AI-voice-River_vertical.mp4",
        "RegKnot_audit_15s_AI-voice-Chris_vertical.mp4", "RegKnot_audit_15s_AI-voice-River_vertical.mp4"],
     "the two 15-second towing cuts (\"First trip\" and \"Audit coming\"), each in both narrators"),
]


def body(what: str, n: int, of: int) -> str:
    return (f"Hi Karynn,\n\nHere's {what} ({n} of {of}). Every answer on screen is a real RegKnot answer "
            "from the Bay Pioneer demo profile; the narration is an AI voice until your own recording is in. "
            "Your name is said the way we settled on today.\n\nThese are the phone-sized versions. "
            "Widescreen versions exist too if you want them.\n\nBlake\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", default="kdmarchal@gmail.com")
    a = ap.parse_args()
    service = gmail_draft.gmail()
    for i, (subject, files, what) in enumerate(DRAFTS, 1):
        msg = EmailMessage()
        msg["From"] = gmail_draft.FROM
        msg["To"] = a.to
        msg["Subject"] = subject
        msg.set_content(body(what, i, len(DRAFTS)))
        total = 0
        for name in files:
            data = (SHARE / name).read_bytes()
            total += len(data)
            msg.add_attachment(data, maintype="video", subtype="mp4", filename=name)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        draft = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
        print(f"draft {draft['id']}: {subject!r} -> {a.to}, {len(files)} file(s), {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
