"""Shared API-level validation and student authentication dependencies."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models.auth import User, UserSession
from app.models.curriculum import Book, BookCurriculumLink, BookStatus, EducationBranch, FieldOfStudy, Grade, Major
from app.services.auth_billing_service import USER_COOKIE_NAME, parse_user_session_token
from app.services.validation import validate_major_code
from app.services.curriculum_access import is_student_visible_book


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


def enforce_student_grade_level(user: User, grade_number: int) -> None:
    """Prevent a profiled student from accessing content above their assigned grade.

    A missing grade_level is deliberately not guessed here; deployments should
    complete student grade profiles to activate this restriction.
    """
    if user.grade_level is not None and grade_number > user.grade_level:
        raise HTTPException(
            status_code=422,
            detail="the selected textbook is above the student's assigned grade level",
        )


async def resolve_book_scope(
    session: AsyncSession,
    *,
    book_id: int,
    grade_number: int,
    major_code: str | None,
    branch_code: str | None = None,
) -> tuple[Book, Grade, str | None]:
    """Resolve a textbook in either legacy major mode or the normalized K-12 context.

    For new high-school requests, branch_code is mandatory and major_code is the
    field-of-study code (when that branch has fields). The selected Book row is
    always checked against its explicit applicability links.
    """
    book = await session.get(Book, book_id)
    if not is_student_visible_book(book):
        raise HTTPException(status_code=404, detail="book not found")
    grade = await session.get(Grade, book.grade_id)
    if grade is None or grade.number != grade_number:
        raise HTTPException(status_code=422, detail="book does not belong to the selected grade")

    book_major = await session.get(Major, book.major_id) if book.major_id is not None else None
    expected_major = book_major.code if book_major is not None else None

    if branch_code is None:
        major_error = validate_major_code(grade.has_major, major_code)
        if major_error:
            raise HTTPException(status_code=422, detail=major_error)
        if major_code != expected_major:
            raise HTTPException(status_code=422, detail="book does not belong to the selected major")
        return book, grade, expected_major

    if grade.number < 10:
        raise HTTPException(status_code=422, detail="branch selection is only valid for grades 10-12")

    branch = await session.scalar(
        select(EducationBranch).where(
            EducationBranch.code == branch_code,
            EducationBranch.is_active.is_(True),
        )
    )
    if branch is None or not branch.min_grade <= grade.number <= branch.max_grade:
        raise HTTPException(status_code=422, detail="invalid education branch for this grade")

    selected_field = None
    if major_code:
        selected_field = await session.scalar(
            select(FieldOfStudy).where(
                FieldOfStudy.code == major_code,
                FieldOfStudy.branch_id == branch.id,
                FieldOfStudy.is_active.is_(True),
            )
        )
        if selected_field is None or selected_field.branch_id != branch.id:
            raise HTTPException(status_code=422, detail="field of study does not belong to the selected branch")
    elif branch.code == "theoretical":
        raise HTTPException(status_code=422, detail="a theoretical field of study is required")

    if expected_major is not None and expected_major != major_code:
        raise HTTPException(status_code=422, detail="book does not belong to the selected field")

    selected_field_id = selected_field.id if selected_field is not None else -1
    applicability = await session.scalar(
        select(BookCurriculumLink.id).where(
            BookCurriculumLink.book_id == book.id,
            or_(
                and_(
                    BookCurriculumLink.branch_id == branch.id,
                    BookCurriculumLink.field_of_study_id.is_(None),
                ),
                and_(
                    BookCurriculumLink.branch_id == branch.id,
                    BookCurriculumLink.field_of_study_id == selected_field_id,
                ),
                and_(
                    BookCurriculumLink.branch_id.is_(None),
                    BookCurriculumLink.field_of_study_id.is_(None),
                ),
            ),
        ).limit(1)
    )
    if applicability is None:
        # Compatibility for older theoretical books that still only have major_id.
        if expected_major is None or expected_major != major_code:
            raise HTTPException(status_code=422, detail="book is not available for the selected curriculum")
    return book, grade, selected_field.code if selected_field is not None else expected_major
