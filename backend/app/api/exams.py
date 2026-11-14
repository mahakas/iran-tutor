"""Timed, persistent multiple-choice exam API."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import resolve_book_scope
from app.db.session import get_session
from app.models.curriculum import Book
from app.models.exam import ExamSession
from app.services.exam_service import create_exam, exam_summary, public_exam, submit_exam

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/exams", tags=["exams"])


class CreateExamRequest(BaseModel):
    grade_number: int = Field(ge=1, le=12)
    major_code: str | None = Field(default=None, max_length=64)
    book_id: int = Field(gt=0)
    chapter_title: str | None = Field(default=None, max_length=255)
    question_count: int = Field(default=5, ge=3, le=20)
    time_limit_minutes: int = Field(default=15, ge=5, le=120)
    exam_type: Literal["konkoor", "final"] = "konkoor"


class SubmitExamRequest(BaseModel):
    answers: dict[str, str | None] = Field(default_factory=dict, max_length=20)


@router.post("")
async def start_exam(
    body: CreateExamRequest, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    book, grade, major_code = await resolve_book_scope(
        session,
        book_id=body.book_id,
        grade_number=body.grade_number,
        major_code=body.major_code,
    )
    try:
        exam = await create_exam(
            session,
            book_id=book.id,
            grade_number=grade.number,
            major_code=major_code,
            question_count=body.question_count,
            time_limit_minutes=body.time_limit_minutes,
            exam_type=body.exam_type,
            chapter_title=body.chapter_title,
        )
        return public_exam(exam)
    except LookupError as error:
        raise HTTPException(status_code=409, detail="no approved pages found for this exam scope") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        if "TUTOR_MODEL" in str(error):
            raise HTTPException(status_code=503, detail="question-generation model is not configured") from error
        logger.exception("exam creation failed")
        raise HTTPException(status_code=503, detail="exam service is temporarily unavailable") from error
    except Exception as error:  # noqa: BLE001
        logger.exception("exam creation failed")
        raise HTTPException(status_code=503, detail="exam service is temporarily unavailable") from error


@router.get("")
async def list_exams(
    book_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=30, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    query = (
        select(ExamSession, Book.title)
        .outerjoin(Book, ExamSession.book_id == Book.id)
        .order_by(ExamSession.created_at.desc())
        .limit(limit)
    )
    if book_id is not None:
        query = query.where(ExamSession.book_id == book_id)
    rows = (await session.execute(query)).all()
    return [exam_summary(exam, book_title=book_title) for exam, book_title in rows]


@router.get("/{exam_id}")
async def get_exam(exam_id: str, session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    exam = await session.get(ExamSession, exam_id)
    if exam is None:
        raise HTTPException(status_code=404, detail="exam not found")
    return public_exam(exam, include_report=True)


@router.post("/{exam_id}/submit")
async def finish_exam(
    exam_id: str,
    body: SubmitExamRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    exam = await session.get(ExamSession, exam_id)
    if exam is None:
        raise HTTPException(status_code=404, detail="exam not found")
    try:
        report = submit_exam(exam, body.answers)
    except TimeoutError as error:
        await session.commit()
        raise HTTPException(status_code=410, detail="exam time has expired") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    await session.commit()
    return {"exam_id": exam.id, "status": "submitted", "report_card": report}
