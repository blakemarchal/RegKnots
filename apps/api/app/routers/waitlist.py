"""Waitlist endpoint for post-pilot email capture."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr

from app.db import get_pool

router = APIRouter(tags=["waitlist"])


class WaitlistRequest(BaseModel):
    email: EmailStr


@router.post("/waitlist", status_code=status.HTTP_201_CREATED)
async def join_waitlist(body: WaitlistRequest) -> dict:
    pool = await get_pool()
    try:
        await pool.execute(
            "INSERT INTO waitlist (email) VALUES ($1) ON CONFLICT (email) DO NOTHING",
            body.email,
        )
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to join waitlist")
    return {"detail": "You're on the list!"}
