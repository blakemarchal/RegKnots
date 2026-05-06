"""Sea Service Letter generator.

GET  /credentials/sea-service-letter/prefill  — pre-fill data for the form
POST /credentials/sea-service-letter          — generate PDF (returns stream)

Mariners need a USCG-formatted Statement of Sea Service from their employer
for every credential upgrade or renewal application. The format is
semi-standardized but easy to get wrong, which causes USCG NMC to kick the
application back. This endpoint generates a properly-formatted PDF the
mariner can email to their employer to sign.

No DB persistence — letters are point-in-time documents. The signed paper
is the version that matters.
"""

import io
import json
import logging
import uuid as _uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/credentials/sea-service-letter", tags=["credentials"])


# ── Models ────────────────────────────────────────────────────────────────


class VesselEntry(BaseModel):
    vessel_id: str | None = None
    vessel_name: str
    official_number: str | None = None
    gross_tonnage: float | None = None
    vessel_type: str | None = None
    route_type: str | None = None       # e.g. "Inland", "Coastal", "Oceans"
    horsepower: str | None = None        # for engineering credentials
    propulsion: str | None = None        # e.g. "Diesel", "Steam"
    capacity_served: str                 # e.g. "Master", "Mate", "Engineer", "OS"
    from_date: date
    to_date: date
    days_on_board: int                   # mariner can override calculated value


class SeaServiceRequest(BaseModel):
    applicant_full_name: str
    applicant_address: str | None = None
    applicant_mariner_reference_number: str | None = None  # MMC reference if known
    target_endorsement: str | None = None                  # what they're applying for
    company_name: str
    company_address: str | None = None
    company_phone: str | None = None
    company_official_name: str
    company_official_title: str
    vessel_entries: list[VesselEntry] = Field(min_length=1)
    remarks: str | None = None


class PrefillVessel(BaseModel):
    id: str
    vessel_name: str
    official_number: str | None
    gross_tonnage: float | None
    vessel_type: str | None
    route_type: str | None  # primary route from route_types array


class PrefillSeaTimeEntry(BaseModel):
    """A logged sea-time block, mapped to VesselEntry's shape so the
    UI can drop it directly into the letter form."""
    id: str
    vessel_id: str | None
    vessel_name: str
    official_number: str | None
    gross_tonnage: float | None
    vessel_type: str | None
    route_type: str | None
    horsepower: str | None
    propulsion: str | None
    capacity_served: str
    from_date: str
    to_date: str
    days_on_board: int


class PrefillResponse(BaseModel):
    applicant_full_name: str
    applicant_mmc_number: str | None
    suggested_role: str | None  # from users.role for capacity hint
    vessels: list[PrefillVessel]
    # D6.62 — logged sea-time blocks pulled in for one-tap inclusion.
    sea_time_entries: list[PrefillSeaTimeEntry] = []


# ── Helpers ────────────────────────────────────────────────────────────────


def _primary_route(route_types: list[str] | None) -> str | None:
    """Pick the most permissive route as the 'primary' for sea service."""
    if not route_types:
        return None
    # Order of permissiveness: international > coastal > inland
    if "international" in route_types:
        return "Oceans"
    if "coastal" in route_types:
        return "Near-Coastal / Coastal"
    if "inland" in route_types:
        return "Inland"
    return route_types[0].title()


def _role_to_capacity(role: str | None) -> str | None:
    """Map user.role to a likely sea service capacity for pre-fill convenience."""
    if not role:
        return None
    mapping = {
        "captain": "Master",
        "mate": "Mate",
        "engineer": "Engineer",
        "chief_engineer": "Chief Engineer",
    }
    return mapping.get(role)


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/prefill", response_model=PrefillResponse)
async def prefill_sea_service_letter(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> PrefillResponse:
    """Return data RegKnot already knows so the form opens 80% pre-filled."""
    pool = await get_pool()
    user_id = _uuid.UUID(user.user_id)

    # User basics
    user_row = await pool.fetchrow(
        "SELECT full_name, role FROM users WHERE id = $1",
        user_id,
    )
    full_name = user_row["full_name"] if user_row else ""
    role = user_row["role"] if user_row else None

    # MMC reference number (if tracked)
    mmc_row = await pool.fetchrow(
        """
        SELECT credential_number FROM user_credentials
        WHERE user_id = $1 AND credential_type = 'mmc' AND credential_number IS NOT NULL
        ORDER BY created_at DESC
        LIMIT 1
        """,
        user_id,
    )
    mmc_number = mmc_row["credential_number"] if mmc_row else None

    # Vessels
    vessel_rows = await pool.fetch(
        """
        SELECT id, name, vessel_type, gross_tonnage, route_types, additional_details
        FROM vessels
        WHERE user_id = $1
        ORDER BY created_at ASC
        """,
        user_id,
    )

    vessels: list[PrefillVessel] = []
    for v in vessel_rows:
        additional = v["additional_details"] or {}
        if isinstance(additional, str):
            try:
                additional = json.loads(additional)
            except (ValueError, TypeError):
                additional = {}
        vessels.append(PrefillVessel(
            id=str(v["id"]),
            vessel_name=v["name"],
            official_number=additional.get("official_number") if isinstance(additional, dict) else None,
            gross_tonnage=float(v["gross_tonnage"]) if v["gross_tonnage"] is not None else None,
            vessel_type=v["vessel_type"],
            route_type=_primary_route(list(v["route_types"] or [])),
        ))

    # D6.62 — pull logged sea-time blocks. Most-recent first so the UI's
    # natural order is sensible. The form can include all, some, or none
    # — we hand them over and let the user decide.
    sea_time_rows = await pool.fetch(
        """
        SELECT id, vessel_id, vessel_name, official_number, vessel_type,
               gross_tonnage, horsepower, propulsion, route_type,
               capacity_served, from_date, to_date, days_on_board
        FROM sea_time_entries
        WHERE user_id = $1
        ORDER BY from_date DESC, created_at DESC
        """,
        user_id,
    )
    sea_time_entries = [
        PrefillSeaTimeEntry(
            id=str(r["id"]),
            vessel_id=str(r["vessel_id"]) if r["vessel_id"] else None,
            vessel_name=r["vessel_name"],
            official_number=r["official_number"],
            gross_tonnage=float(r["gross_tonnage"]) if r["gross_tonnage"] is not None else None,
            vessel_type=r["vessel_type"],
            route_type=r["route_type"],
            horsepower=r["horsepower"],
            propulsion=r["propulsion"],
            capacity_served=r["capacity_served"],
            from_date=r["from_date"].isoformat(),
            to_date=r["to_date"].isoformat(),
            days_on_board=int(r["days_on_board"]),
        )
        for r in sea_time_rows
    ]

    return PrefillResponse(
        applicant_full_name=full_name,
        applicant_mmc_number=mmc_number,
        suggested_role=_role_to_capacity(role),
        vessels=vessels,
        sea_time_entries=sea_time_entries,
    )


@router.post("")
async def generate_sea_service_letter(
    body: SeaServiceRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> StreamingResponse:
    """Generate a USCG-formatted Sea Service Letter as a PDF."""
    if not body.vessel_entries:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one vessel entry is required",
        )

    # Validate dates per entry
    for i, entry in enumerate(body.vessel_entries):
        if entry.from_date > entry.to_date:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Vessel entry {i + 1}: from_date must be before to_date",
            )
        if entry.days_on_board < 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Vessel entry {i + 1}: days_on_board must be non-negative",
            )

    pdf_bytes = _generate_pdf(body)

    safe_name = body.applicant_full_name.replace(" ", "_").replace("/", "-")
    filename = f"sea_service_letter_{safe_name}.pdf"

    logger.info(
        "Generated sea service letter: user=%s vessels=%d total_days=%d",
        user.email, len(body.vessel_entries),
        sum(e.days_on_board for e in body.vessel_entries),
    )

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── PDF generation ─────────────────────────────────────────────────────────


def _generate_pdf(body: SeaServiceRequest) -> bytes:
    """Generate the USCG-formatted Sea Service Letter PDF using fpdf2."""
    from fpdf import FPDF

    pdf = FPDF(orientation="portrait", unit="mm", format="letter")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # ── Company letterhead block ─────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, body.company_name, new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.set_font("Helvetica", "", 10)
    if body.company_address:
        for line in body.company_address.splitlines():
            line = line.strip()
            if line:
                pdf.cell(0, 5, line, new_x="LMARGIN", new_y="NEXT", align="C")
    if body.company_phone:
        pdf.cell(0, 5, body.company_phone, new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.ln(8)

    # ── Date + To: USCG NMC ───────────────────────────────────────────────
    today_str = date.today().strftime("%B %d, %Y")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 6, today_str, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.cell(0, 5, "U.S. Coast Guard", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, "National Maritime Center", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, "100 Forbes Drive", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, "Martinsburg, WV 25404", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(8)

    # ── Subject line ──────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 11)
    subject = f"SUBJECT: Statement of Sea Service for {body.applicant_full_name}"
    pdf.cell(0, 6, subject, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(4)

    # ── Opening paragraph ─────────────────────────────────────────────────
    pdf.set_font("Helvetica", "", 11)
    intro_lines = [
        f"To Whom It May Concern at the National Maritime Center:",
        "",
        f"This letter certifies the sea service of {body.applicant_full_name}"
        + (f" (Mariner Reference Number {body.applicant_mariner_reference_number})"
           if body.applicant_mariner_reference_number else "") + ".",
    ]
    if body.target_endorsement:
        intro_lines.append("")
        intro_lines.append(
            f"This statement is provided in support of an application for: {body.target_endorsement}."
        )
    intro_lines.append("")
    intro_lines.append(
        "The following service was performed aboard the vessel(s) listed below "
        "while in the active employ of the company named above:"
    )

    for line in intro_lines:
        if not line:
            pdf.ln(3)
            continue
        pdf.multi_cell(0, 5, line)

    pdf.ln(4)

    # ── Vessel service table ─────────────────────────────────────────────
    # Per-vessel: heading + key fields in label/value pairs
    for idx, entry in enumerate(body.vessel_entries, start=1):
        # Vessel block header
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 6, f"Vessel {idx}: {entry.vessel_name}", new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("Helvetica", "", 10)

        fields: list[tuple[str, str | None]] = [
            ("Official Number", entry.official_number),
            ("Vessel Type", entry.vessel_type),
            ("Gross Tonnage", f"{entry.gross_tonnage:,.0f} GT" if entry.gross_tonnage else None),
            ("Route", entry.route_type),
            ("Propulsion", entry.propulsion),
            ("Horsepower", entry.horsepower),
            ("Capacity Served", entry.capacity_served),
            ("From Date", entry.from_date.strftime("%B %d, %Y")),
            ("To Date", entry.to_date.strftime("%B %d, %Y")),
            ("Days On Board", str(entry.days_on_board)),
        ]

        for label, value in fields:
            if not value:
                continue
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(50, 5, f"{label}:", new_x="RIGHT")
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(0, 5, str(value), new_x="LMARGIN", new_y="NEXT")

        pdf.ln(3)

    # ── Total days ────────────────────────────────────────────────────────
    total_days = sum(e.days_on_board for e in body.vessel_entries)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, f"Total Days of Service: {total_days}", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(4)

    # ── Remarks ───────────────────────────────────────────────────────────
    if body.remarks and body.remarks.strip():
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, "Remarks:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 5, body.remarks.strip())
        pdf.ln(3)

    # ── Closing certification ────────────────────────────────────────────
    pdf.set_font("Helvetica", "", 11)
    closing = (
        "I certify under penalty of perjury that the above sea service is true and "
        "accurate to the best of my knowledge and was performed by the above-named "
        "applicant in the active service of this company."
    )
    pdf.multi_cell(0, 5, closing)

    pdf.ln(12)

    # ── Signature block ──────────────────────────────────────────────────
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(80, 6, "_______________________________", new_x="RIGHT")
    pdf.cell(0, 6, "Date: _________________", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 5, body.company_official_name, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 5, body.company_official_title, new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, body.company_name, new_x="LMARGIN", new_y="NEXT")

    # ── Footer ───────────────────────────────────────────────────────────
    pdf.ln(8)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(
        0, 4,
        "Generated via RegKnot \u00B7 regknots.com  \u00B7  Verify accuracy before submission to USCG NMC.",
        new_x="LMARGIN", new_y="NEXT", align="C",
    )

    return pdf.output()
