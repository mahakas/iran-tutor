"""Phase 5 mastery path: chapter scores from exams, flashcards and solve sessions.

Score = weighted mean of the per-component accuracy (exam 0.5, flashcards 0.3,
solve 0.2), renormalised over components that have evidence. A chapter is
mastered when its score reaches the book threshold (admin-configurable). Chapters
unlock sequentially unless the admin switches the book to `open` mode or sets a
per-chapter override.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.curriculum import Book, BookPage, PageStatus
from app.models.phase5 import MasteryBookSettings, MasteryChapterProgress

WEIGHTS: dict[str, float] = {"exam": 0.5, "flash": 0.3, "solve": 0.2}
DEFAULT_THRESHOLD = 0.7
UNLOCK_MODES = ("sequential", "open")
OVERRIDE_VALUES = ("locked", "open")


async def record_component(
    session: AsyncSession,
    *,
    user_id: str,
    book_id: int,
    chapter_number: int | None,
    component: str,
    correct: int,
    total: int,
) -> MasteryChapterProgress | None:
    """Add evidence for one chapter. Silently ignores events without chapter or total."""
    if component not in WEIGHTS or chapter_number is None or total <= 0:
        return None
    row = await session.scalar(
        select(MasteryChapterProgress).where(
            MasteryChapterProgress.user_id == user_id,
            MasteryChapterProgress.book_id == book_id,
            MasteryChapterProgress.chapter_number == chapter_number,
        )
    )
    if row is None:
        row = MasteryChapterProgress(
            user_id=user_id,
            book_id=book_id,
            chapter_number=chapter_number,
            exam_correct=0,
            exam_total=0,
            flash_correct=0,
            flash_total=0,
            solve_correct=0,
            solve_total=0,
        )
        session.add(row)
    setattr(row, f"{component}_correct", int(getattr(row, f"{component}_correct") or 0) + max(0, min(correct, total)))
    setattr(row, f"{component}_total", int(getattr(row, f"{component}_total") or 0) + total)
    row.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return row


def chapter_score(row: MasteryChapterProgress | None) -> float | None:
    if row is None:
        return None
    weighted = 0.0
    weight_sum = 0.0
    for component, weight in WEIGHTS.items():
        total = int(getattr(row, f"{component}_total") or 0)
        if total <= 0:
            continue
        correct = int(getattr(row, f"{component}_correct") or 0)
        weighted += weight * (correct / total)
        weight_sum += weight
    if weight_sum == 0:
        return None
    return round(weighted / weight_sum, 4)


def _breakdown(row: MasteryChapterProgress | None) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for component in WEIGHTS:
        out[component] = {
            "correct": int(getattr(row, f"{component}_correct", 0) or 0) if row else 0,
            "total": int(getattr(row, f"{component}_total", 0) or 0) if row else 0,
        }
    return out


async def get_settings(session: AsyncSession, book_id: int) -> MasteryBookSettings:
    settings = await session.get(MasteryBookSettings, book_id)
    if settings is None:
        settings = MasteryBookSettings(
            book_id=book_id,
            threshold=DEFAULT_THRESHOLD,
            unlock_mode="sequential",
            chapter_overrides_json={},
        )
    return settings


def serialize_settings(settings: MasteryBookSettings) -> dict[str, Any]:
    return {
        "book_id": settings.book_id,
        "threshold": float(settings.threshold),
        "unlock_mode": settings.unlock_mode,
        "chapter_overrides": dict(settings.chapter_overrides_json or {}),
    }


async def _chapters(session: AsyncSession, book_id: int) -> list[dict[str, Any]]:
    pages = (
        await session.scalars(
            select(BookPage)
            .where(
                BookPage.book_id == book_id,
                BookPage.chapter_number.is_not(None),
                BookPage.status == PageStatus.done,
            )
            .order_by(BookPage.pdf_page_index.asc())
        )
    ).all()
    seen: dict[int, dict[str, Any]] = {}
    for page in pages:
        if page.chapter_number in seen:
            seen[page.chapter_number]["page_end"] = page.pdf_page_index
            continue
        seen[page.chapter_number] = {
            "chapter_number": page.chapter_number,
            "chapter_title": page.chapter_title or f"فصل {page.chapter_number}",
            "page_start": page.pdf_page_index,
            "page_end": page.pdf_page_index,
        }
    return list(seen.values())


async def book_tree(session: AsyncSession, *, user_id: str, book_id: int) -> dict[str, Any]:
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="کتاب یافت نشد.")
    settings = await get_settings(session, book_id)
    threshold = float(settings.threshold)
    overrides = dict(settings.chapter_overrides_json or {})
    progress = {
        row.chapter_number: row
        for row in (
            await session.scalars(
                select(MasteryChapterProgress).where(
                    MasteryChapterProgress.user_id == user_id,
                    MasteryChapterProgress.book_id == book_id,
                )
            )
        ).all()
    }
    nodes: list[dict[str, Any]] = []
    previous_mastered = True
    for index, chapter in enumerate(await _chapters(session, book_id)):
        number = chapter["chapter_number"]
        row = progress.get(number)
        score = chapter_score(row)
        mastered = score is not None and score >= threshold
        override = overrides.get(str(number))
        locked_reason: str | None = None
        if override == "locked":
            locked_reason = "admin_locked"
        elif override == "open":
            locked_reason = None
        elif settings.unlock_mode == "sequential" and index > 0 and not previous_mastered:
            locked_reason = "previous_chapter_not_mastered"
        if locked_reason:
            status = "locked"
        elif mastered:
            status = "mastered"
        elif score is None:
            status = "not_started"
        else:
            status = "in_progress"
        nodes.append(
            {
                **chapter,
                "score": score,
                "threshold": threshold,
                "status": status,
                "locked_reason": locked_reason,
                "override": override,
                "evidence": _breakdown(row),
            }
        )
        previous_mastered = mastered
    return {
        "book": {"id": book.id, "title": book.title},
        "threshold": threshold,
        "unlock_mode": settings.unlock_mode,
        "mastered_count": sum(1 for node in nodes if node["status"] == "mastered"),
        "chapters": nodes,
    }


async def update_settings(
    session: AsyncSession,
    *,
    book_id: int,
    threshold: float | None = None,
    unlock_mode: str | None = None,
    actor: str = "admin",
) -> MasteryBookSettings:
    if await session.get(Book, book_id) is None:
        raise HTTPException(status_code=404, detail="کتاب یافت نشد.")
    settings = await session.get(MasteryBookSettings, book_id)
    if settings is None:
        settings = MasteryBookSettings(
            book_id=book_id, threshold=DEFAULT_THRESHOLD, unlock_mode="sequential", chapter_overrides_json={}
        )
        session.add(settings)
    if threshold is not None:
        if not 0.3 <= threshold <= 1.0:
            raise HTTPException(status_code=422, detail="آستانهٔ تسلط باید بین ۰٫۳ و ۱ باشد.")
        settings.threshold = float(threshold)
    if unlock_mode is not None:
        if unlock_mode not in UNLOCK_MODES:
            raise HTTPException(status_code=422, detail="حالت باز شدن نامعتبر است.")
        settings.unlock_mode = unlock_mode
    settings.updated_by = actor
    settings.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return settings


async def set_chapter_override(
    session: AsyncSession, *, book_id: int, chapter_number: int, override: str | None, actor: str = "admin"
) -> MasteryBookSettings:
    if override is not None and override not in OVERRIDE_VALUES:
        raise HTTPException(status_code=422, detail="مقدار قفل فصل نامعتبر است.")
    settings = await update_settings(session, book_id=book_id, actor=actor)
    overrides = dict(settings.chapter_overrides_json or {})
    if override is None:
        overrides.pop(str(chapter_number), None)
    else:
        overrides[str(chapter_number)] = override
    settings.chapter_overrides_json = overrides
    await session.flush()
    return settings
