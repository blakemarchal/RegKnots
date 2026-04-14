"""Speech-to-text transcription endpoint (Whisper fallback).

POST /transcribe — upload audio, get text back
"""

import logging
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transcribe", tags=["transcribe"])

_MAX_AUDIO_SIZE = 25 * 1024 * 1024  # 25 MB (Whisper limit)
_ALLOWED_AUDIO = {
    "audio/webm", "audio/mp4", "audio/mpeg", "audio/mp3",
    "audio/wav", "audio/x-wav", "audio/ogg", "audio/flac",
    "video/webm",  # MediaRecorder on some browsers produces video/webm
}


@router.post("")
async def transcribe_audio(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    file: UploadFile = File(...),
) -> dict:
    """Transcribe an audio file using OpenAI Whisper API."""
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transcription service is not configured",
        )

    content_type = file.content_type or ""
    if content_type not in _ALLOWED_AUDIO:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported audio type: {content_type}",
        )

    content = await file.read()
    if len(content) > _MAX_AUDIO_SIZE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Audio file too large. Maximum 25 MB.",
        )

    # Whisper needs a file with an extension
    ext_map = {
        "audio/webm": ".webm", "video/webm": ".webm",
        "audio/mp4": ".mp4", "audio/mpeg": ".mp3", "audio/mp3": ".mp3",
        "audio/wav": ".wav", "audio/x-wav": ".wav",
        "audio/ogg": ".ogg", "audio/flac": ".flac",
    }
    ext = ext_map.get(content_type, ".webm")

    try:
        import openai
        client = openai.OpenAI(api_key=settings.openai_api_key)

        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        # The prompt parameter provides vocabulary hints to Whisper so it
        # correctly recognizes maritime acronyms and regulation names.
        _WHISPER_VOCAB_HINT = (
            "COLREGs, SOLAS, STCW, ISM, ISM Code, CFR, MMC, TWIC, NVIC, "
            "ISPS, USCG, MARPOL, PSC, NMC, IMO, RegKnot, "
            "46 CFR, 33 CFR, 49 CFR, Port State Control"
        )

        with open(tmp_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="en",
                prompt=_WHISPER_VOCAB_HINT,
            )

        Path(tmp_path).unlink(missing_ok=True)

        logger.info(
            "Transcription complete: user=%s chars=%d",
            current_user.user_id, len(transcript.text),
        )

        return {"text": transcript.text}

    except Exception as exc:
        logger.exception("Transcription failed: %s", exc)
        Path(tmp_path).unlink(missing_ok=True) if 'tmp_path' in dir() else None
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Transcription failed. Please try again.",
        )
