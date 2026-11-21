"""Student tutoring APIs: text, image, and voice questions (OTP-authenticated & token-metered)."""

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_student, resolve_book_scope
from app.core.llm_client import track_token_usage
from app.db.session import get_session
from app.models.auth import User, UserFile
from app.models.chat import ChatSession
from app.models.curriculum import Book
from app.services.account_service import (
    ensure_user_file_path,
    normalize_preferences,
    save_user_file,
    serialize_user_file,
)
from app.services.auth_billing_service import (
    get_or_init_billing_settings,
    record_and_deduct_usage,
)
from app.services.quota_service import enforce_ai_quota
from app.services.multimodal_service import answer_audio_question, answer_image_question
from app.services.tutor_service import TutorMode, answer_from_textbook

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/tutor", tags=["tutor"])

# Feature keys so admins can route a different model per tutor mode (Phase 1).
TUTOR_MODE_FEATURES = {
    "tutor": "chat",
    "problem_solver": "solve",
    "question_designer": "quiz",
}

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
    chat_session_id: str | None = Field(default=None, max_length=64)


class ChatMessageItem(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)
    sources: list[dict[str, Any]] | None = None
    attachment: str | None = None


class CreateChatSessionRequest(BaseModel):
    book_id: int = Field(gt=0)
    grade_number: int = Field(ge=1, le=12)
    major_code: str | None = Field(default=None, max_length=64)
    mode: TutorMode = "tutor"
    title: str = Field(min_length=1, max_length=255)
    messages: list[ChatMessageItem] = Field(min_length=1, max_length=200)


class UpdateChatSessionRequest(BaseModel):
    mode: TutorMode | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    messages: list[ChatMessageItem] = Field(min_length=1, max_length=200)


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _serialize_chat_summary(
    chat: ChatSession, *, book_title: str | None = None
) -> dict[str, object]:
    return {
        "id": chat.id,
        "title": chat.title,
        "book_id": chat.book_id,
        "book_title": book_title,
        "grade_number": chat.grade_number,
        "major_code": chat.major_code,
        "mode": chat.mode,
        "message_count": len(chat.messages or []),
        "created_at": _utc_iso(chat.created_at),
        "updated_at": _utc_iso(chat.updated_at),
    }


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


async def _maybe_store_tutor_attachment(
    session: AsyncSession,
    *,
    user: User,
    filename: str,
    content_bytes: bytes,
    mime_type: str,
    source_context: str,
    chat_session_id: str | None = None,
) -> UserFile | None:
    if not isinstance(user, User) or not isinstance(session, AsyncSession):
        return None
    prefs = normalize_preferences(getattr(user, "preferences", None))
    if not prefs["privacy"].get("store_uploaded_attachments", True):
        return None
    billing = await get_or_init_billing_settings(session)
    return await save_user_file(
        session,
        user=user,
        billing=billing,
        filename=filename,
        content_bytes=content_bytes,
        mime_type=mime_type,
        source_context=source_context,
        chat_session_id=chat_session_id,
        enforce_quota=True,
    )


async def _finalize_usage(
    session: AsyncSession,
    *,
    user: User,
    action: str,
    book_id: int,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    result: dict[str, Any],
) -> None:
    if total_tokens > 0:
        usage_payload = await record_and_deduct_usage(
            session,
            user=user,
            action=action,
            book_id=book_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        result["usage"] = usage_payload
    else:
        if isinstance(session, AsyncSession):
            await session.commit()
        result["usage"] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost_toman": 0,
            "tokens_remaining": user.tokens_remaining,
        }


@router.post("/ask")
async def ask_tutor(
    body: AskRequest,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    book, grade, major_code = await resolve_book_scope(
        session,
        book_id=body.book_id,
        grade_number=body.grade_number,
        major_code=body.major_code,
    )
    await enforce_ai_quota(
        session,
        user=current_user,
        feature_key=TUTOR_MODE_FEATURES.get(body.mode, "chat"),
    )
    try:
        with track_token_usage() as usage:
            result = await answer_from_textbook(
                query=body.query,
                grade_number=grade.number,
                major_code=major_code,
                book_id=book.id,
                top_k=body.top_k,
                mode=body.mode,
                user_id=current_user.id,
                session_id=body.chat_session_id,
                db_session=session,
            )
    except Exception as error:  # noqa: BLE001 - do not expose provider details
        raise _provider_failure(error, operation="tutor") from error

    await _finalize_usage(
        session,
        user=current_user,
        action="tutor_ask",
        book_id=book.id,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        result=result,
    )
    return result


@router.post("/ask-image")
async def ask_tutor_with_image(
    image: UploadFile = File(...),
    grade_number: int = Form(...),
    book_id: int = Form(...),
    major_code: str | None = Form(None),
    top_k: int = Form(5),
    mode: TutorMode = Form("tutor"),
    chat_session_id: str | None = Form(None),
    current_user: User = Depends(require_student),
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
    await enforce_ai_quota(session, user=current_user, feature_key="vision_ocr")
    image_bytes = await _read_upload_limited(image, MAX_IMAGE_BYTES)
    image_bytes = _normalize_image(image_bytes, image.content_type or "")
    saved_file = await _maybe_store_tutor_attachment(
        session,
        user=current_user,
        filename=Path(image.filename or "question.png").stem + ".png",
        content_bytes=image_bytes,
        mime_type="image/png",
        source_context="tutor_image",
        chat_session_id=chat_session_id,
    )
    try:
        with track_token_usage() as usage:
            result = await answer_image_question(
                image_bytes=image_bytes,
                image_mime_type="image/png",
                grade_number=grade.number,
                major_code=major_code,
                book_id=book.id,
                top_k=top_k,
                mode=mode,
                user_id=current_user.id,
                session_id=chat_session_id,
                db_session=session,
            )
    except Exception as error:  # noqa: BLE001 - do not expose provider details
        if saved_file is not None:
            try:
                ensure_user_file_path(current_user.id, saved_file.storage_path).unlink(missing_ok=True)
            except HTTPException:
                pass
            await session.rollback()
        raise _provider_failure(error, operation="image tutor") from error

    await _finalize_usage(
        session,
        user=current_user,
        action="tutor_image",
        book_id=book.id,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        result=result,
    )
    if saved_file is not None:
        result["saved_file"] = serialize_user_file(saved_file)
    return result


@router.post("/ask-audio")
async def ask_tutor_with_audio(
    audio: UploadFile = File(...),
    grade_number: int = Form(...),
    book_id: int = Form(...),
    major_code: str | None = Form(None),
    top_k: int = Form(5),
    mode: TutorMode = Form("tutor"),
    chat_session_id: str | None = Form(None),
    current_user: User = Depends(require_student),
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
    await enforce_ai_quota(session, user=current_user, feature_key="stt")
    filename = Path(audio.filename or "question.webm").name
    content_type = (audio.content_type or "").lower()
    if content_type in {"", "application/octet-stream"}:
        content_type = AUDIO_MIME_BY_SUFFIX.get(Path(filename).suffix.lower(), "")
    if content_type not in AUDIO_MIME_TYPES:
        raise HTTPException(status_code=415, detail="unsupported audio format")
    audio_bytes = await _read_upload_limited(audio, MAX_AUDIO_BYTES)
    saved_file = await _maybe_store_tutor_attachment(
        session,
        user=current_user,
        filename=filename,
        content_bytes=audio_bytes,
        mime_type=content_type,
        source_context="tutor_audio",
        chat_session_id=chat_session_id,
    )
    try:
        with track_token_usage() as usage:
            result = await answer_audio_question(
                audio_bytes=audio_bytes,
                filename=filename,
                content_type=content_type,
                grade_number=grade.number,
                major_code=major_code,
                book_id=book.id,
                top_k=top_k,
                mode=mode,
                user_id=current_user.id,
                session_id=chat_session_id,
                db_session=session,
            )
    except Exception as error:  # noqa: BLE001 - do not expose provider details
        if saved_file is not None:
            try:
                ensure_user_file_path(current_user.id, saved_file.storage_path).unlink(missing_ok=True)
            except HTTPException:
                pass
            await session.rollback()
        raise _provider_failure(error, operation="voice tutor") from error

    await _finalize_usage(
        session,
        user=current_user,
        action="tutor_audio",
        book_id=book.id,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        result=result,
    )
    if saved_file is not None:
        result["saved_file"] = serialize_user_file(saved_file)
    return result


@router.get("/sessions")
async def list_chat_sessions(
    limit: int = Query(default=30, ge=1, le=100),
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    rows = (
        await session.execute(
            select(ChatSession, Book.title)
            .outerjoin(Book, ChatSession.book_id == Book.id)
            .where(ChatSession.user_id == current_user.id)
            .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [_serialize_chat_summary(chat, book_title=book_title) for chat, book_title in rows]


@router.post("/sessions")
async def create_chat_session(
    body: CreateChatSessionRequest,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    book, grade, major_code = await resolve_book_scope(
        session,
        book_id=body.book_id,
        grade_number=body.grade_number,
        major_code=body.major_code,
    )
    now = datetime.now(timezone.utc)
    chat = ChatSession(
        book_id=book.id,
        user_id=current_user.id,
        grade_number=grade.number,
        major_code=major_code or "general",
        mode=body.mode,
        title=body.title.strip()[:255] or "گفت‌وگو با معلم",
        messages=[item.model_dump() for item in body.messages],
        created_at=now,
        updated_at=now,
    )
    session.add(chat)
    await session.commit()
    await session.refresh(chat)
    return {**_serialize_chat_summary(chat, book_title=book.title), "messages": chat.messages}


@router.get("/sessions/{session_id}")
async def get_chat_session(
    session_id: str,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    row = (
        await session.execute(
            select(ChatSession, Book.title)
            .outerjoin(Book, ChatSession.book_id == Book.id)
            .where(ChatSession.id == session_id, ChatSession.user_id == current_user.id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="chat session not found")
    chat, book_title = row
    return {**_serialize_chat_summary(chat, book_title=book_title), "messages": chat.messages}


@router.put("/sessions/{session_id}")
async def update_chat_session(
    session_id: str,
    body: UpdateChatSessionRequest,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    chat = await session.scalar(
        select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == current_user.id)
    )
    if chat is None:
        raise HTTPException(status_code=404, detail="chat session not found")
    if body.title is not None:
        chat.title = body.title.strip()[:255] or chat.title
    if body.mode is not None:
        chat.mode = body.mode
    chat.messages = [item.model_dump() for item in body.messages]
    chat.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(chat)
    book = await session.get(Book, chat.book_id)
    return {
        **_serialize_chat_summary(chat, book_title=book.title if book else None),
        "messages": chat.messages,
    }


@router.delete("/sessions/{session_id}")
async def delete_chat_session(
    session_id: str,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    chat = await session.scalar(
        select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == current_user.id)
    )
    if chat is None:
        raise HTTPException(status_code=404, detail="chat session not found")
    await session.delete(chat)
    await session.commit()
    return {"deleted": True, "id": session_id}
