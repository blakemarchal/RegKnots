import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.config import settings

_pw_hash = PasswordHash([Argon2Hasher()])

# Emails granted admin access at the application level (no DB migration needed)
_APP_LEVEL_ADMINS: set[str] = {"kdmarchal@gmail.com"}


def hash_password(password: str) -> str:
    return _pw_hash.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pw_hash.verify(plain, hashed)


def create_access_token(
    user_id: str, email: str, role: str, tier: str,
    full_name: str | None = None, is_admin: bool = False,
    email_verified: bool = False,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "tier": tier,
        "full_name": full_name,
        "is_admin": is_admin or email in _APP_LEVEL_ADMINS,
        "email_verified": email_verified,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Raises jwt.InvalidTokenError subclasses on failure."""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


def create_refresh_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hash). Store the hash; send raw to the client."""
    raw = secrets.token_urlsafe(32)
    return raw, _hash_raw(raw)


def hash_refresh_token(raw: str) -> str:
    return _hash_raw(raw)


def _hash_raw(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
