"""Personal credential tracking endpoints.

POST   /credentials                      — create a credential
GET    /credentials                      — list all user credentials
GET    /credentials/{id}                 — get single credential
PUT    /credentials/{id}                 — update a credential
DELETE /credentials/{id}                 — delete a credential
POST   /credentials/extract-from-photo   — extract credential data from a photo
"""

import base64
import io
import json
import logging
import uuid as _uuid
from datetime import date, datetime, timedelta
from typing import Annotated

from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/credentials", tags=["credentials"])

# Sprint D6.67 — expanded type allow-list. Migration 0087 widened the
# DB CHECK constraint to match. Adding more types here without bumping
# the migration will cause CREATE/UPDATE inserts to fail at the DB.
_VALID_TYPES = {
    "mmc", "stcw", "medical", "twic",
    "passport", "passport_card",
    "gmdss", "dp",
    "drug_test", "vaccine",
    "sea_service", "course_cert",
    "other",
}


class CredentialCreate(BaseModel):
    credential_type: str
    title: str
    credential_number: str | None = None
    issuing_authority: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    notes: str | None = None


class CredentialUpdate(BaseModel):
    credential_type: str | None = None
    title: str | None = None
    credential_number: str | None = None
    issuing_authority: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    notes: str | None = None


class CredentialOut(BaseModel):
    id: str
    credential_type: str
    title: str
    credential_number: str | None
    issuing_authority: str | None
    issue_date: str | None
    expiry_date: str | None
    notes: str | None
    created_at: str
    updated_at: str


def _row_to_out(r) -> CredentialOut:
    return CredentialOut(
        id=str(r["id"]),
        credential_type=r["credential_type"],
        title=r["title"],
        credential_number=r["credential_number"],
        issuing_authority=r["issuing_authority"],
        issue_date=r["issue_date"].isoformat() if r["issue_date"] else None,
        expiry_date=r["expiry_date"].isoformat() if r["expiry_date"] else None,
        notes=r["notes"],
        created_at=r["created_at"].isoformat(),
        updated_at=r["updated_at"].isoformat(),
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CredentialOut)
async def create_credential(
    body: CredentialCreate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CredentialOut:
    if body.credential_type not in _VALID_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid credential_type. Must be one of: {', '.join(sorted(_VALID_TYPES))}",
        )
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO user_credentials
            (user_id, credential_type, title, credential_number,
             issuing_authority, issue_date, expiry_date, notes)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING *
        """,
        _uuid.UUID(user.user_id),
        body.credential_type,
        body.title.strip(),
        body.credential_number,
        body.issuing_authority,
        body.issue_date,
        body.expiry_date,
        body.notes,
    )
    return _row_to_out(row)


@router.get("", response_model=list[CredentialOut])
async def list_credentials(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> list[CredentialOut]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM user_credentials
        WHERE user_id = $1
        ORDER BY
            CASE WHEN expiry_date IS NULL THEN 1 ELSE 0 END,
            expiry_date ASC,
            created_at DESC
        """,
        _uuid.UUID(user.user_id),
    )
    return [_row_to_out(r) for r in rows]


# ── D6.62 Sprint 2 — PDF Package export ───────────────────────────────────
#
# IMPORTANT: this route MUST be declared before /{credential_id} because
# `/{credential_id}` is typed as UUID and "package" fails validation
# with a 422 if it captures the path first. Route declaration order
# wins in FastAPI on overlapping paths.

def _latin1_safe(s: str | None) -> str:
    """Coerce a string to fpdf2's core-font (Helvetica) charset.

    Helvetica is Latin-1 only. Common smart-typography from Claude
    Vision OCR or pasted user input (em-dash, smart quotes, arrows,
    ellipsis) trips fpdf2 with FPDFUnicodeEncodingException → 500.

    Strategy: replace well-known smart chars with ASCII equivalents,
    then for anything else outside Latin-1 (cp1252) fall back to '?'
    so the PDF still renders. User-controlled fields go through this
    on the way into pdf.cell().
    """
    if not s:
        return ""
    # Replace common smart chars with ASCII so the document still
    # reads naturally instead of getting littered with '?'.
    replacements = {
        "—": "-",   # em-dash
        "–": "-",   # en-dash
        "−": "-",   # math minus
        "→": " to ",  # rightwards arrow
        "←": " <- ",  # leftwards arrow
        "‘": "'", "’": "'",  # smart single quotes
        "“": '"', "”": '"',  # smart double quotes
        "…": "...",  # ellipsis
        "•": "*",    # bullet
        " ": " ",    # non-breaking space
    }
    for src, dst in replacements.items():
        s = s.replace(src, dst)
    # Anything else outside Latin-1 becomes '?'.
    return s.encode("latin-1", "replace").decode("latin-1")


@router.get("/package")
async def export_credential_package(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    tz: str | None = None,
) -> StreamingResponse:
    """Generate a single PDF bundling all of the user's credentials +
    sea-time totals and entries.

    The "share with employer / manning agency / port agent" file
    competitors paywall as a Pro feature. We build it from data the
    user already entered — no extra work, just the existing records
    rendered into a clean handoff document.

    `tz` is the IANA timezone the client is in (e.g. America/Chicago).
    Used to compute "today" so the cover-page date matches what the
    user sees on their wall clock. Falls back to UTC if absent or
    unrecognized.
    """
    import io
    from fpdf import FPDF

    # Resolve "today" in the user's timezone, falling back to UTC.
    try:
        if tz:
            from zoneinfo import ZoneInfo
            today_dt = datetime.now(ZoneInfo(tz))
            today = today_dt.date()
            today_label = today.isoformat()
            tz_label = tz
        else:
            today = date.today()
            today_label = today.isoformat()
            tz_label = "UTC"
    except Exception:
        today = date.today()
        today_label = today.isoformat()
        tz_label = "UTC"

    pool = await get_pool()
    user_uuid = _uuid.UUID(user.user_id)

    # User basics
    user_row = await pool.fetchrow(
        "SELECT full_name, email FROM users WHERE id = $1", user_uuid,
    )
    full_name = (user_row["full_name"] if user_row else "") or "(unnamed mariner)"
    email = (user_row["email"] if user_row else "") or ""

    # Credentials
    creds = await pool.fetch(
        "SELECT credential_type, title, credential_number, issuing_authority, "
        "issue_date, expiry_date, notes "
        "FROM user_credentials WHERE user_id = $1 "
        "ORDER BY credential_type, issue_date DESC NULLS LAST",
        user_uuid,
    )

    # Sea-time totals + entries (sourced from the same place the
    # logger UI reads). Computed inline because we don't want a circular
    # import to sea_time router.
    sea_time_rows = await pool.fetch(
        "SELECT vessel_name, official_number, vessel_type, gross_tonnage, "
        "horsepower, propulsion, route_type, capacity_served, "
        "from_date, to_date, days_on_board, employer_name "
        "FROM sea_time_entries WHERE user_id = $1 "
        "ORDER BY from_date DESC",
        user_uuid,
    )
    cutoff_3yr = today - timedelta(days=365 * 3)
    cutoff_5yr = today - timedelta(days=365 * 5)
    total_days = days_3yr = days_5yr = 0
    by_route: dict[str, int] = {}
    by_capacity: dict[str, int] = {}
    for r in sea_time_rows:
        d = int(r["days_on_board"])
        total_days += d
        rt = r["route_type"] or "Unspecified"
        cap = r["capacity_served"] or "Unspecified"
        by_route[rt] = by_route.get(rt, 0) + d
        by_capacity[cap] = by_capacity.get(cap, 0) + d
        for cutoff, key in ((cutoff_3yr, "3yr"), (cutoff_5yr, "5yr")):
            o_start = max(r["from_date"], cutoff)
            o_end = min(r["to_date"], today)
            if o_end >= o_start:
                ov = min((o_end - o_start).days + 1, d)
                if key == "3yr":
                    days_3yr += ov
                else:
                    days_5yr += ov

    # ── Build the PDF ─────────────────────────────────────────────────────
    pdf = FPDF(orientation="portrait", unit="mm", format="letter")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Cover header
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "Mariner Credential Package",
             new_x="LMARGIN", new_y="NEXT", align="L")
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, _latin1_safe(full_name),
             new_x="LMARGIN", new_y="NEXT", align="L")
    pdf.set_font("Helvetica", "", 10)
    if email:
        pdf.cell(0, 5, _latin1_safe(email),
                 new_x="LMARGIN", new_y="NEXT", align="L")
    pdf.cell(
        0, 5, f"Generated {today_label} ({tz_label}) via RegKnots",
        new_x="LMARGIN", new_y="NEXT", align="L",
    )
    pdf.ln(3)
    pdf.set_draw_color(140, 140, 140)
    pdf.line(20, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(5)

    # ── Credentials section ───────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, "Credentials", new_x="LMARGIN", new_y="NEXT", align="L")
    pdf.ln(1)

    if not creds:
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 6, "  (no credentials on file)",
                 new_x="LMARGIN", new_y="NEXT", align="L")
    else:
        # Header row
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(230, 230, 230)
        pdf.cell(35, 6, "Type", border=0, fill=True, align="L")
        pdf.cell(60, 6, "Title", border=0, fill=True, align="L")
        pdf.cell(35, 6, "Number", border=0, fill=True, align="L")
        pdf.cell(25, 6, "Issued", border=0, fill=True, align="L")
        pdf.cell(20, 6, "Expires", border=0, fill=True, align="L",
                 new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("Helvetica", "", 9)
        for c in creds:
            type_label = (c["credential_type"] or "").upper()
            title = (c["title"] or "")[:40]
            # Latin-1 only: fpdf2's core Helvetica font can't render em-dash
            # or arrow glyphs. ASCII hyphen for missing data; "to" for
            # date-range separator below. _latin1_safe() handles any
            # smart-typography that may have crept in from OCR/paste.
            number = (c["credential_number"] or "-")[:18]
            issued = c["issue_date"].isoformat() if c["issue_date"] else "-"
            expires = c["expiry_date"].isoformat() if c["expiry_date"] else "-"
            pdf.cell(35, 5, type_label, border=0, align="L")
            pdf.cell(60, 5, _latin1_safe(title), border=0, align="L")
            pdf.cell(35, 5, _latin1_safe(number), border=0, align="L")
            pdf.cell(25, 5, issued, border=0, align="L")
            pdf.cell(20, 5, expires, border=0, align="L",
                     new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5)

    # ── Sea-time summary ──────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, "Sea-time Summary", new_x="LMARGIN", new_y="NEXT", align="L")
    pdf.ln(1)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 5, f"Total days on board: {total_days}",
             new_x="LMARGIN", new_y="NEXT", align="L")
    pdf.cell(0, 5, f"Last 3 years: {days_3yr} days",
             new_x="LMARGIN", new_y="NEXT", align="L")
    pdf.cell(0, 5, f"Last 5 years: {days_5yr} days",
             new_x="LMARGIN", new_y="NEXT", align="L")
    if by_route:
        pdf.ln(1)
        pdf.cell(
            0, 5,
            _latin1_safe("By route: " + ", ".join(
                f"{k}: {v}d" for k, v in sorted(by_route.items(), key=lambda x: -x[1])
            )),
            new_x="LMARGIN", new_y="NEXT", align="L",
        )
    if by_capacity:
        pdf.cell(
            0, 5,
            _latin1_safe("By capacity: " + ", ".join(
                f"{k}: {v}d" for k, v in sorted(by_capacity.items(), key=lambda x: -x[1])
            )),
            new_x="LMARGIN", new_y="NEXT", align="L",
        )
    pdf.ln(5)

    # ── Sea-time entries (full log) ───────────────────────────────────────
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, "Sea-time Log", new_x="LMARGIN", new_y="NEXT", align="L")
    pdf.ln(1)

    if not sea_time_rows:
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 6, "  (no entries logged)",
                 new_x="LMARGIN", new_y="NEXT", align="L")
    else:
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(230, 230, 230)
        pdf.cell(45, 6, "Vessel", border=0, fill=True, align="L")
        pdf.cell(28, 6, "Capacity", border=0, fill=True, align="L")
        pdf.cell(22, 6, "Route", border=0, fill=True, align="L")
        pdf.cell(45, 6, "Dates", border=0, fill=True, align="L")
        pdf.cell(15, 6, "Days", border=0, fill=True, align="R")
        pdf.cell(20, 6, "GT/HP", border=0, fill=True, align="L",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        for r in sea_time_rows:
            vessel = (r["vessel_name"] or "")[:28]
            cap = (r["capacity_served"] or "")[:18]
            route = (r["route_type"] or "-")[:15]
            dates = f"{r['from_date'].isoformat()} to {r['to_date'].isoformat()}"
            days = str(int(r["days_on_board"]))
            gt = r["gross_tonnage"]
            hp = r["horsepower"]
            gt_hp = ""
            if gt is not None:
                gt_hp = f"{gt} GT"
            elif hp:
                gt_hp = f"{hp} HP"
            pdf.cell(45, 5, _latin1_safe(vessel), border=0, align="L")
            pdf.cell(28, 5, _latin1_safe(cap), border=0, align="L")
            pdf.cell(22, 5, _latin1_safe(route), border=0, align="L")
            pdf.cell(45, 5, dates, border=0, align="L")
            pdf.cell(15, 5, days, border=0, align="R")
            pdf.cell(20, 5, _latin1_safe(gt_hp)[:14], border=0, align="L",
                     new_x="LMARGIN", new_y="NEXT")

    # Footer disclaimer
    pdf.ln(8)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(110, 110, 110)
    pdf.multi_cell(
        0, 4,
        "This document is a self-reported summary generated by RegKnots from the "
        "mariner's stored credentials and sea-time log. It is not an official "
        "USCG document. Original credentials and signed sea-service letters "
        "remain the authoritative source.",
    )

    # ── Stream out ────────────────────────────────────────────────────────
    pdf_bytes = pdf.output()
    if isinstance(pdf_bytes, str):
        pdf_bytes = pdf_bytes.encode("latin-1")
    elif isinstance(pdf_bytes, bytearray):
        pdf_bytes = bytes(pdf_bytes)

    safe_name = (full_name or "mariner").replace(" ", "_").replace("/", "-")
    filename = f"{safe_name}_credential_package_{today_label}.pdf"

    logger.info(
        "credential package generated: user=%s creds=%d sea_time_entries=%d "
        "total_days=%d tz=%s",
        user.email, len(creds), len(sea_time_rows), total_days, tz_label,
    )

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{credential_id}", response_model=CredentialOut)
async def get_credential(
    credential_id: _uuid.UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CredentialOut:
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM user_credentials WHERE id = $1 AND user_id = $2",
        credential_id, _uuid.UUID(user.user_id),
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    return _row_to_out(row)


@router.put("/{credential_id}", response_model=CredentialOut)
async def update_credential(
    credential_id: _uuid.UUID,
    body: CredentialUpdate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CredentialOut:
    pool = await get_pool()
    user_id = _uuid.UUID(user.user_id)

    existing = await pool.fetchrow(
        "SELECT * FROM user_credentials WHERE id = $1 AND user_id = $2",
        credential_id, user_id,
    )
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")

    if body.credential_type and body.credential_type not in _VALID_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid credential_type. Must be one of: {', '.join(sorted(_VALID_TYPES))}",
        )

    # Build dynamic update
    sets: list[str] = []
    params: list = []
    idx = 1
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        if field == "title" and isinstance(value, str):
            value = value.strip()
        sets.append(f"{field} = ${idx}")
        params.append(value)
        idx += 1

    if not sets:
        return _row_to_out(existing)

    # Reset reminder flags if expiry_date changed
    if "expiry_date" in updates:
        sets.append(f"reminder_sent_90 = FALSE")
        sets.append(f"reminder_sent_30 = FALSE")
        sets.append(f"reminder_sent_7 = FALSE")

    params.append(credential_id)
    params.append(user_id)
    sql = f"UPDATE user_credentials SET {', '.join(sets)} WHERE id = ${idx} AND user_id = ${idx + 1} RETURNING *"
    row = await pool.fetchrow(sql, *params)
    return _row_to_out(row)


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    credential_id: _uuid.UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> None:
    pool = await get_pool()
    result = await pool.execute(
        "DELETE FROM user_credentials WHERE id = $1 AND user_id = $2",
        credential_id, _uuid.UUID(user.user_id),
    )
    if result == "DELETE 0":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")


# ── Photo extraction ──────────────────────────────────────────────────────

_CREDENTIAL_EXTRACTION_PROMPT = """\
You are analyzing a photo of a personal credential document — typically
a maritime credential, but the user may also scan adjacent travel /
identification / training documents we track alongside.

Classify the document into ONE of these credential_type values, using
the visual + textual cues listed for each. Pick the most specific
match; fall back to "other" only if nothing fits.

  "mmc"           — U.S. Merchant Mariner Credential. USCG seal, the
                    words "Merchant Mariner Credential" or "Merchant
                    Mariner's Document", endorsement listings (Master,
                    Mate, AB, etc.). Issuing authority is "USCG NMC"
                    or "U.S. Coast Guard".

  "stcw"          — STCW endorsement certificate. Header references
                    "STCW" (Standards of Training, Certification, and
                    Watchkeeping) plus a Roman-numeral regulation
                    (II/1, III/2, A-VI/1, etc.) OR a named training:
                    "Basic Safety Training", "Advanced Firefighting",
                    "Radar Observer", "GMDSS Operator".

  "medical"       — USCG Medical Certificate (Form CG-719K). Header
                    "Merchant Mariner Medical Certificate", USCG NMC
                    Medical Evaluation Branch.

  "twic"          — Transportation Worker Identification Credential.
                    TSA seal, "TWIC" text, holographic security card
                    layout, gold-embossed strip.

  "passport"      — U.S. Passport (book). U.S. Department of State
                    seal, "PASSPORT" header, photo + biographical
                    page, machine-readable zone (MRZ) at bottom.

  "passport_card" — U.S. Passport Card (wallet-sized). Says "PASSPORT
                    CARD" explicitly, smaller than a passport book,
                    valid for land/sea entry from Canada/Mexico/
                    Bermuda/Caribbean only. Has its own MRZ.

  "gmdss"         — GMDSS Radio Operator certificate. Either FCC
                    Restricted/General Radiotelephone Operator
                    Permit, or USCG GMDSS endorsement. References
                    "Global Maritime Distress and Safety System".

  "dp"            — Dynamic Positioning operator certificate. Issued
                    by Nautical Institute or DNV. Says "Dynamic
                    Positioning" + level (Limited / Unlimited).

  "drug_test"     — DOT 5-panel drug test letter. Letterhead from a
                    medical clinic / collection site, MRO (Medical
                    Review Officer) signature, "DRUG TEST" or "Drug
                    Screen", typically a one-page negative-result
                    letter.

  "vaccine"       — Vaccination record. Yellow Fever WHO yellow card,
                    CDC COVID-19 vaccination card, or similar
                    immunization record. References specific
                    vaccine + administration date.

  "sea_service"   — Sea-service letter / discharge. Company letterhead
                    addressed to USCG NMC, lists vessel + dates +
                    capacity served. Signed by an authorized company
                    official. NOT a card — a typed letter.

  "course_cert"   — Generic training course completion certificate
                    that ISN'T a named STCW endorsement. Typically a
                    school/training-provider certificate (Maritime
                    Professional Training, MITAGS, Calhoon MEBA, etc.)
                    for non-STCW courses (firefighting refresher, OUPV
                    prep, lifeboatman, etc.).

  "other"         — Doesn't fit any of the above. Common fallback:
                    union membership card, employment contract,
                    company ID, etc.

Now extract the following fields from the image:

- credential_type: ONE value from the list above
- title: the document's title or specific endorsement (e.g., "Master
         1600 GRT Near-Coastal", "STCW II/1 Officer in Charge of
         Navigational Watch on Vessels of 500 GT or More", "United
         States Passport", "DOT 5-Panel Drug Test Letter")
- credential_number: the document number if visible. For passports,
                     use the 9-character passport number. For TWIC, the
                     T-prefixed number. For MMC, the format is
                     typically "MMC-YYYY-NNNNNN". Return null if not
                     clearly visible.
- issuing_authority: who issued it. Examples: "USCG National Maritime
                     Center", "TSA", "U.S. Department of State",
                     "Nautical Institute", "Maritime Professional
                     Training", a clinic name for drug tests.
- issue_date: date issued in YYYY-MM-DD format. Many documents show
              this as "Issue Date" or "Date of Issue".
- expiry_date: expiration date in YYYY-MM-DD format. For documents
               without an explicit expiry (some sea-service letters,
               drug-test letters), return null. For passports with
               "Date of Expiration", that's the expiry.

Return ONLY a JSON object with these six fields. Use null for fields
you cannot identify. Do not include any explanation or markdown —
just the JSON.

If the document is clearly NOT a credential (e.g., a random photo,
a vessel COI, a chart), return null for ALL fields."""

_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}


class CredentialExtraction(BaseModel):
    credential_type: str | None = None
    title: str | None = None
    credential_number: str | None = None
    issuing_authority: str | None = None
    issue_date: str | None = None
    expiry_date: str | None = None


@router.post("/extract-from-photo", response_model=CredentialExtraction)
async def extract_credential_from_photo(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    file: UploadFile = File(...),
) -> CredentialExtraction:
    """Extract credential data from a photo using Claude Vision."""
    content_type = file.content_type or ""
    if content_type not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported file type: {content_type}. Allowed: JPEG, PNG, WebP, PDF.",
        )

    content = await file.read()
    if len(content) > _MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File too large. Maximum size is 10 MB.",
        )

    # Build vision content blocks
    if content_type == "application/pdf":
        from pdf2image import convert_from_bytes

        images = convert_from_bytes(content, first_page=1, last_page=2, dpi=200)
        content_blocks: list[dict] = []
        for img in images:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            content_blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": b64},
            })
        content_blocks.append({"type": "text", "text": _CREDENTIAL_EXTRACTION_PROMPT})
    else:
        b64 = base64.b64encode(content).decode("utf-8")
        content_blocks = [
            {"type": "image", "source": {"type": "base64", "media_type": content_type, "data": b64}},
            {"type": "text", "text": _CREDENTIAL_EXTRACTION_PROMPT},
        ]

    try:
        anthropic_client: AsyncAnthropic = request.app.state.anthropic
        response = await anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": content_blocks}],
        )

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        extracted = json.loads(text.strip())

        logger.info("Credential extraction complete: user=%s fields=%s", current_user.user_id, list(extracted.keys()))
        return CredentialExtraction(**{k: v for k, v in extracted.items() if v != "null" and v is not None})

    except Exception:
        logger.exception("Credential extraction failed")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not extract data from this document. Try a clearer photo.",
        )
