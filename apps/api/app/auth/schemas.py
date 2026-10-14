from pydantic import BaseModel, EmailStr


class SignupAttribution(BaseModel):
    """First campaign touch recorded by the web client (2026-09-26).
    See app/attribution.py; every field is optional and capped server-side."""
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_term: str | None = None
    src: str | None = None             # outreach code, e.g. "ob-3f9a"
    ref: str | None = None             # partner page code; informational only
    referrer_host: str | None = None
    landing_path: str | None = None
    first_seen_at: str | None = None


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: str = "other"
    attribution: SignupAttribution | None = None
    # 2026-10-14 — the secret a visitor's browser kept after a question asked
    # before signup (app/guest.py); the conversation moves to the new account.
    guest_claim: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    # 2026-10-14 — set on registration when a guest question was claimed
    claimed_conversation_id: str | None = None


class CurrentUser(BaseModel):
    user_id: str
    email: str
    role: str
    tier: str
    is_admin: bool = False
    email_verified: bool = False
    full_name: str | None = None
