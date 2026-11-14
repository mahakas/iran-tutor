"""Student tutoring API backed by curriculum-filtered textbook retrieval."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models.curriculum import Book, Grade, Major
from app.services.tutor_service import answer_from_textbook
from app.services.validation import validate_major_code

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/tutor", tags=["tutor"])


class AskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    grade_number: int = Field(ge=1, le=12)
    major_code: str | None = Field(default=None, max_length=64)
    book_id: int = Field(gt=0)
    top_k: int = Field(default=5, ge=1, le=20)


@router.post("/ask")
async def ask_tutor(
    body: AskRequest, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    book = await session.get(Book, body.book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="book not found")
    grade = await session.get(Grade, book.grade_id)
    if grade is None or grade.number != body.grade_number:
        raise HTTPException(status_code=422, detail="book does not belong to the selected grade")

    major_error = validate_major_code(grade.has_major, body.major_code)
    if major_error:
        raise HTTPException(status_code=422, detail=major_error)

    book_major = await session.get(Major, book.major_id) if book.major_id is not None else None
    expected_major = book_major.code if book_major is not None else None
    if body.major_code != expected_major:
        raise HTTPException(status_code=422, detail="book does not belong to the selected major")

    try:
        return await answer_from_textbook(
            query=body.query,
            grade_number=grade.number,
            major_code=expected_major,
            book_id=book.id,
            top_k=body.top_k,
        )
    except RuntimeError as error:
        if "TUTOR_MODEL" in str(error):
            raise HTTPException(status_code=503, detail="tutor model is not configured") from error
        logger.exception("tutor service is unavailable")
        raise HTTPException(status_code=503, detail="textbook retrieval service is unavailable") from error
    except Exception as error:  # noqa: BLE001 - do not expose provider/DB details to clients
        logger.exception("tutor request failed")
        raise HTTPException(status_code=503, detail="tutor service is temporarily unavailable") from error
