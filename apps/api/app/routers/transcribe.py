"""Speech-to-text transcription endpoint (voice input).

POST /transcribe — upload audio, get text back

2026-10-16 — whisper-1 leaves the OpenAI API on 2027-02-26 (OpenAI's
transcription deprecation of 2026-08-26); the model is now gpt-transcribe
($0.0045 a minute; takes the same prompt and language hints). Also: the
async client, so a transcription no longer blocks the event loop; the
audio's own bytes decide its type; a capped read; and a daily per-user
limit (security review 2026-10-16).
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status

from app import ratelimit, uploads
from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transcribe", tags=["transcribe"])

TRANSCRIBE_MODEL = "gpt-transcribe"
_MAX_AUDIO_SIZE = 25 * 1024 * 1024  # 25 MB (the API's limit)

# Vocabulary hints, so maritime acronyms and regulation names come out right.
_VOCAB_HINT = (
    "COLREGs, SOLAS, STCW, ISM, ISM Code, CFR, MMC, TWIC, NVIC, "
    "ISPS, USCG, MARPOL, PSC, NMC, IMO, RegKnot, TSMS, Subchapter M, "
    "46 CFR, 33 CFR, 49 CFR, Port State Control"
)


@router.post("")
async def transcribe_audio(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    file: UploadFile = File(...),
) -> dict:
    """Transcribe an audio file with OpenAI's transcription API."""
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transcription service is not configured",
        )

    content = await uploads.read_capped(file, _MAX_AUDIO_SIZE, "Audio file too large. Maximum 25 MB.")
    sniffed = uploads.sniff_audio(content)
    if sniffed is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported audio format.",
        )
    mime_type, ext = sniffed
    await ratelimit.transcription(current_user.user_id)

    try:
        from openai import AsyncOpenAI
        async with AsyncOpenAI(api_key=settings.openai_api_key) as client:
            transcript = await client.audio.transcriptions.create(
                model=TRANSCRIBE_MODEL,
                file=(f"audio{ext}", content, mime_type),
                language="en",
                prompt=_VOCAB_HINT,
            )
    except Exception as exc:
        logger.exception("Transcription failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Transcription failed. Please try again.",
        )

    logger.info("Transcription complete: user=%s chars=%d", current_user.user_id, len(transcript.text))
    return {"text": transcript.text}
