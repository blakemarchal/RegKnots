from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.schemas import CurrentUser
from app.auth.service import decode_access_token

_bearer = HTTPBearer()

# Emails granted admin access at the application level (no DB migration needed)
_APP_LEVEL_ADMINS: set[str] = {"kdmarchal@gmail.com"}


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> CurrentUser:
    token = credentials.credentials
    try:
        payload = decode_access_token(token)
        if payload.get("type") != "access":
            raise ValueError("wrong token type")
        email = payload["email"]
        return CurrentUser(
            user_id=payload["sub"],
            email=email,
            role=payload["role"],
            tier=payload["tier"],
            is_admin=payload.get("is_admin", False) or email in _APP_LEVEL_ADMINS,
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
