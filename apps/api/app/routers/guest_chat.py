"""One free answer before signup (growth plan step 2, 2026-10-14).

POST /public/ask/stream runs the visitor's question through the normal chat
stream (chat_stream_endpoint) as the internal guest account, after the
guest checks in app/guest.py: Turnstile, one question per device, a loose
per-IP cap and the daily / monthly budget. The stream opens with a `guest`
event carrying the claim secret and the conversation id; the browser keeps
them and sends the secret with registration (auth.register → guest.claim).
"""
from __future__ import annotations

import json
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import events, guest
from app.db import get_pool

router = APIRouter(prefix="/public/ask", tags=["public"])


class GuestStatus(BaseModel):
    enabled: bool
    vessel_types: list[str]


class GuestAskBody(BaseModel):
    query: str = Field(min_length=3, max_length=1500)
    turnstile_token: str = Field(default="", max_length=4096)
    device_id: str = Field(min_length=8, max_length=100)
    vessel_type: str | None = Field(default=None, max_length=60)
    page: str | None = Field(default=None, max_length=200)


@router.get("/status", response_model=GuestStatus)
async def guest_status() -> GuestStatus:
    return GuestStatus(enabled=guest.enabled(), vessel_types=list(guest.VESSEL_TYPES))


@router.post("/stream")
async def guest_stream(
    body: GuestAskBody,
    request: Request,
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
):
    if not guest.enabled():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail={"code": "guest_off", "message": "Questions without an account aren't open."})
    query = body.query.strip()
    vessel_type = body.vessel_type if body.vessel_type in guest.VESSEL_TYPES else None
    ip = guest.client_ip(request)
    device_hash = guest.keyed_hash(f"device:{body.device_id}")
    ip_hash = guest.keyed_hash(f"ip:{ip}")

    await guest.check_limits(pool, device_hash, ip_hash)
    if not await guest.verify_turnstile(body.turnstile_token, ip):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail={"code": "guest_check", "message": "The browser check didn't pass. Reload the page and try again."})

    guest_cu = await guest.guest_user(pool)
    conversation_id, vessel_id, token = await guest.start(
        pool, guest_cu, query=query, vessel_type=vessel_type, page=body.page,
        device_hash=device_hash, ip_hash=ip_hash,
    )
    await events.track(pool, "guest_question", anon_id=device_hash[:32],
                       props={"page": body.page, "vessel_type": vessel_type})

    from app.routers.chat import ChatRequestBody, chat_stream_endpoint
    inner = await chat_stream_endpoint(
        ChatRequestBody(query=query, conversation_id=conversation_id, vessel_id=vessel_id),
        request, guest_cu, pool,
    )

    async def stream():
        claim = json.dumps({"claim": token, "conversation_id": str(conversation_id)})
        yield f"event: guest\ndata: {claim}\n\n"
        async for chunk in inner.body_iterator:
            yield chunk

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                                      "X-Accel-Buffering": "no"})
