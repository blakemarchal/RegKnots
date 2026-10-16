"""Upload checks (2026-10-16 security review, item 7).

A file's own bytes decide its type, never the browser's Content-Type, and a
file is read in chunks that stop as soon as it passes the size cap, instead
of being read whole before the check. Chat document uploads already sniff
PDF / DOCX (app/user_docs.sniff_type); this covers the image / PDF scans
(vessel documents, credentials) and voice input.
"""
from __future__ import annotations

from fastapi import HTTPException, UploadFile, status

_CHUNK = 1024 * 1024
IMAGE_OR_PDF_HINT = "Allowed: JPEG, PNG, WebP, PDF."


async def read_capped(file: UploadFile, max_bytes: int, too_large: str) -> bytes:
    """The upload's bytes, or 422 `too_large` once it passes max_bytes."""
    parts: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=too_large)
        parts.append(chunk)
    return b"".join(parts)


def sniff_image_or_pdf(content: bytes) -> str | None:
    """image/jpeg, image/png, image/webp or application/pdf by signature."""
    if content[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    if content[:5] == b"%PDF-":
        return "application/pdf"
    return None


def require_image_or_pdf(content: bytes) -> str:
    mime = sniff_image_or_pdf(content)
    if mime is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Unsupported file type. {IMAGE_OR_PDF_HINT}")
    return mime


# Audio containers a browser's MediaRecorder or a phone produces → (MIME, extension).
def sniff_audio(content: bytes) -> tuple[str, str] | None:
    if content[:4] == b"\x1a\x45\xdf\xa3":
        return "audio/webm", ".webm"          # WebM / Matroska (Chrome, Firefox, Edge)
    if content[:4] == b"OggS":
        return "audio/ogg", ".ogg"
    if content[:4] == b"RIFF" and content[8:12] == b"WAVE":
        return "audio/wav", ".wav"
    if content[:4] == b"fLaC":
        return "audio/flac", ".flac"
    if content[4:8] == b"ftyp":
        return "audio/mp4", ".m4a"            # MP4 / M4A (Safari, iOS)
    if content[:3] == b"ID3" or (len(content) > 1 and content[0] == 0xFF and content[1] & 0xE0 == 0xE0):
        return "audio/mpeg", ".mp3"
    return None
