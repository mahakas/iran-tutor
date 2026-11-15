"""Shared API-level validation and student authentication dependencies."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models.auth import User, UserSession
from app.models.curriculum import Book, Grade, Major
from app.services.auth_billing_service import USER_COOKIE_NAME, parse_user_session_token
from app.services.validation import validate_major_code


def extract_user_token(request: Request) -> str | None:
    token_header = request.headers.get("x-user-token", "").strip()
    if token_header:
        return token_header
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        bearer = auth_header[7:].strip()
        if bearer:
            return bearer
    cookie_token = request.cookies.get(USER_COOKIE_NAME)
    if cookie_token:
        return cookie_token
    return None


async def _resolve_user_from_request(
    request: Request,
    session: AsyncSession,
) -> User | None:
    token = extract_user_token(request)
    parsed = parse_user_session_token(token)
    if parsed is None:
        return None
    user_id, nonce, _ = parsed

    # Verify session has not been revoked on the server
    session_row = await session.scalar(
        select(UserSession).where(
            UserSession.user_id == user_id,
            UserSession.token_nonce == nonce,
        )
    )
    if session_row is not None and session_row.revoked_at is not None:
        return None

    user = await session.get(User, user_id)
    if user is None:
        return None

    request.state.user_session_nonce = nonce
    if session_row is not None:
        now = datetime.now(timezone.utc)
        last_seen = session_row.last_seen_at
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        if (now - last_seen).total_seconds() >= 60:
            session_row.last_seen_at = now
            await session.commit()
    return user


async def get_optional_student(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User | None:
    return await _resolve_user_from_request(request, session)


async def require_student(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    user = await _resolve_user_from_request(request, session)
    if user is None:
        raise HTTPException(status_code=401, detail="برای ادامه لطفاً با شماره موبایل وارد شوید.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="حساب کاربری شما غیرفعال شده است.")
    return user


async def resolve_book_scope(
    session: AsyncSession, *, book_id: int, grade_number: int, major_code: str | None
) -> tuple[Book, Grade, str | None]:
    """Resolve a book while strictly checking the caller's grade and major."""
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="book not found")
    grade = await session.get(Grade, book.grade_id)
    if grade is None or grade.number != grade_number:
        raise HTTPException(status_code=422, detail="book does not belong to the selected grade")

    major_error = validate_major_code(grade.has_major, major_code)
    if major_error:
        raise HTTPException(status_code=422, detail=major_error)

    book_major = await session.get(Major, book.major_id) if book.major_id is not None else None
    expected_major = book_major.code if book_major is not None else None
    if major_code != expected_major:
        raise HTTPException(status_code=422, detail="book does not belong to the selected major")
    return book, grade, expected_major
