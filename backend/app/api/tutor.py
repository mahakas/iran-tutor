"""Student tutoring APIs: text, image, and voice questions."""

from __future__ import annotations

import io
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import resolve_book_scope
from app.db.session import get_session
from app.models.curriculum import Book, Grade
from app.services.multimodal_service import answer_audio_question, answer_image_question
from app.services.tutor_service import TutorMode, answer_from_textbook

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/tutor", tags=["tutor"])

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_IMAGE_EDGE = 3000
IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
AUDIO_MIME_TYPES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",
    "audio/m4a",
    "audio/x-m4a",
    "audio/webm",
    "audio/ogg",
    "audio/flac",
    "application/ogg",
}
AUDIO_MIME_BY_SUFFIX = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/m4a",
    ".mp4": "audio/mp4",
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
}


class AskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    grade_number: int = Field(ge=1, le=12)
    major_code: str | None = Field(default=None, max_length=64)
    book_id: int = Field(gt=0)
    top_k: int = Field(default=5, ge=1, le=20)
    mode: TutorMode = "tutor"


async def _read_upload_limited(upload: UploadFile, max_bytes: int) -> bytes:
    data = await upload.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"file exceeds {max_bytes // (1024 * 1024)} MiB limit")
    if not data:
        raise HTTPException(status_code=422, detail="uploaded file is empty")
    return data


def _normalize_image(data: bytes, content_type: str) -> bytes:
    if content_type not in IMAGE_MIME_TYPES:
        raise HTTPException(status_code=415, detail="image must be JPEG, PNG, or WebP")
    try:
        with Image.open(io.BytesIO(data)) as image:
            expected_formats = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
            if image.format != expected_formats[content_type]:
                raise HTTPException(status_code=415, detail="image content does not match its media type")
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
            output = io.BytesIO()
            image.save(output, format="PNG", optimize=True)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise HTTPException(status_code=422, detail="uploaded image is invalid or unsafe") from error


def _provider_failure(error: Exception, *, operation: str) -> HTTPException:
    if isinstance(error, RuntimeError) and "SPEECH_TO_TEXT_MODEL" in str(error):
        return HTTPException(status_code=503, detail="speech-to-text model is not configured")
    if isinstance(error, RuntimeError) and "TUTOR_MODEL" in str(error):
        return HTTPException(status_code=503, detail="tutor model is not configured")
    logger.error(
        "%s request failed: %s",
        operation,
        type(error).__name__,
        exc_info=(type(error), error, error.__traceback__),
    )
    return HTTPException(status_code=503, detail=f"{operation} service is temporarily unavailable")


@router.post("/ask")
async def ask_tutor(
    body: AskRequest, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    book, grade, major_code = await resolve_book_scope(
        session,
        book_id=body.book_id,
        grade_number=body.grade_number,
        major_code=body.major_code,
    )
    try:
        return await answer_from_textbook(
            query=body.query,
            grade_number=grade.number,
            major_code=major_code,
            book_id=book.id,
            top_k=body.top_k,
            mode=body.mode,
        )
    except Exception as error:  # noqa: BLE001 - do not expose provider details
        raise _provider_failure(error, operation="tutor") from error


@router.post("/ask-image")
async def ask_tutor_with_image(
    image: UploadFile = File(...),
    grade_number: int = Form(...),
    book_id: int = Form(...),
    major_code: str | None = Form(None),
    top_k: int = Form(5),
    mode: TutorMode = Form("tutor"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    if not 1 <= grade_number <= 12 or book_id <= 0 or not 1 <= top_k <= 20:
        raise HTTPException(status_code=422, detail="invalid grade, book, or result limit")
    book, grade, major_code = await resolve_book_scope(
        session,
        book_id=book_id,
        grade_number=grade_number,
        major_code=major_code,
    )
    image_bytes = await _read_upload_limited(image, MAX_IMAGE_BYTES)
    image_bytes = _normalize_image(image_bytes, image.content_type or "")
    try:
        return await answer_image_question(
            image_bytes=image_bytes,
            image_mime_type="image/png",
            grade_number=grade.number,
            major_code=major_code,
            book_id=book.id,
            top_k=top_k,
            mode=mode,
        )
    except Exception as error:  # noqa: BLE001 - do not expose provider details
        raise _provider_failure(error, operation="image tutor") from error


@router.post("/ask-audio")
async def ask_tutor_with_audio(
    audio: UploadFile = File(...),
    grade_number: int = Form(...),
    book_id: int = Form(...),
    major_code: str | None = Form(None),
    top_k: int = Form(5),
    mode: TutorMode = Form("tutor"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    if not 1 <= grade_number <= 12 or book_id <= 0 or not 1 <= top_k <= 20:
        raise HTTPException(status_code=422, detail="invalid grade, book, or result limit")
    book, grade, major_code = await resolve_book_scope(
        session,
        book_id=book_id,
        grade_number=grade_number,
        major_code=major_code,
    )
    filename = Path(audio.filename or "question.webm").name
    content_type = (audio.content_type or "").lower()
    if content_type in {"", "application/octet-stream"}:
        content_type = AUDIO_MIME_BY_SUFFIX.get(Path(filename).suffix.lower(), "")
    if content_type not in AUDIO_MIME_TYPES:
        raise HTTPException(status_code=415, detail="unsupported audio format")
    audio_bytes = await _read_upload_limited(audio, MAX_AUDIO_BYTES)
    try:
        return await answer_audio_question(
            audio_bytes=audio_bytes,
            filename=filename,
            content_type=content_type,
            grade_number=grade.number,
            major_code=major_code,
            book_id=book.id,
            top_k=top_k,
            mode=mode,
        )
    except Exception as error:  # noqa: BLE001 - do not expose provider details
        raise _provider_failure(error, operation="voice tutor") from error
