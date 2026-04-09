"""Public contact-form endpoint — forwards inquiries to hello@regknots.com."""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from app.email import send_contact_inquiry_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contact", tags=["contact"])


class ContactInquiry(BaseModel):
    name: str = Field(..., max_length=120)
    email: EmailStr
    company: str | None = Field(default=None, max_length=160)
    message: str = Field(..., max_length=5000)


class ContactResult(BaseModel):
    ok: bool


@router.post("/inquiry", response_model=ContactResult)
async def submit_inquiry(body: ContactInquiry) -> ContactResult:
    """Accept a contact form submission and forward to hello@regknots.com via Resend."""
    if len(body.name.strip()) < 2:
        raise HTTPException(status_code=422, detail="Name is required")
    if len(body.message.strip()) < 10:
        raise HTTPException(status_code=422, detail="Message is too short")

    try:
        await send_contact_inquiry_email(
            from_name=body.name.strip(),
            from_email=body.email,
            company=body.company.strip() if body.company else None,
            message=body.message.strip(),
        )
    except Exception as exc:  # noqa: BLE001 — forward as 502 to the caller
        logger.error("Contact inquiry email failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to send message")

    logger.info("Contact inquiry from %s <%s>", body.name, body.email)
    return ContactResult(ok=True)
