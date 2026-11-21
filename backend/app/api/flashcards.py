"""Phase 3 flashcard routes.

Student routes (`/api/v1/flashcards`) and admin routes (`/api/v1/admin/flashcards`).
Every student route is gated by the `flashcards` capability, so when an admin
disables it the API returns 403 and the UI hides the feature.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import require_admin
from app.api.dependencies import require_student
from app.db.session import get_session
from app.models.auth import User
from app.models.curriculum import Book
from app.models.flashcards import Flashcard, FlashcardDeck, FlashcardReview
from app.services import flashcard_service as fs
from app.services.learner_memory_service import record_review_outcome
from app.services.anki_export import build_apkg_bytes
from app.services.capability_service import require_capability_enabled
from app.services.flashcard_sources import (
    ResolvedSources,
    resolve_book_source,
    resolve_chat_source,
    resolve_mistake_source,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/flashcards", tags=["flashcards"])
admin_router = APIRouter(
    prefix="/api/v1/admin/flashcards",
    tags=["admin-flashcards"],
    dependencies=[Depends(require_admin)],
)


async def require_flashcards_enabled(
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Close every student route when the `flashcards` capability is disabled."""
    await require_capability_enabled(session, fs.CAPABILITY_KEY, current_user)
    return current_user


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class DeckCreateBody(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class DeckUpdateBody(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class CardCreateBody(BaseModel):
    front_md: str = Field(min_length=1, max_length=1200)
    back_md: str = Field(min_length=1, max_length=2000)
    hint_md: str = Field(default="", max_length=600)
    tags: list[str] = Field(default_factory=list, max_length=10)


class CardUpdateBody(BaseModel):
    front_md: str | None = Field(default=None, min_length=1, max_length=1200)
    back_md: str | None = Field(default=None, min_length=1, max_length=2000)
    hint_md: str | None = Field(default=None, max_length=600)
    tags: list[str] | None = Field(default=None, max_length=10)


class GenerateBody(BaseModel):
    source: Literal["book", "chat", "mistake"]
    count: int = Field(default=5, ge=1, le=10)
    deck_id: int | None = None
    new_deck_title: str | None = Field(default=None, max_length=255)
    # book
    book_id: int | None = None
    chapter_number: int | None = Field(default=None, ge=1, le=99)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    # chat
    chat_session_id: str | None = Field(default=None, max_length=36)
    message_ids: list[str] = Field(default_factory=list, max_length=10)
    # mistake
    exam_id: str | None = Field(default=None, max_length=36)
    question_ids: list[str] | None = Field(default=None, max_length=50)


class ReviewBody(BaseModel):
    rating: int = Field(ge=1, le=4)


class ModerationBody(BaseModel):
    is_public: bool
    admin_approved: bool


# ---------------------------------------------------------------------------
# Student: decks & cards
# ---------------------------------------------------------------------------


@router.get("/decks")
async def list_decks(
    current_user: User = Depends(require_flashcards_enabled),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    return await fs.list_user_decks(session, current_user)


@router.post("/decks", status_code=201)
async def create_deck(
    body: DeckCreateBody,
    current_user: User = Depends(require_flashcards_enabled),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    deck = await fs.create_deck(session, current_user, title=body.title)
    await session.commit()
    return fs.serialize_deck(deck)


@router.get("/decks/{deck_id}")
async def get_deck(
    deck_id: int,
    current_user: User = Depends(require_flashcards_enabled),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    deck = await fs.get_owned_deck(session, current_user, deck_id)
    return await fs.deck_detail(session, current_user, deck)


@router.patch("/decks/{deck_id}")
async def rename_deck(
    deck_id: int,
    body: DeckUpdateBody,
    current_user: User = Depends(require_flashcards_enabled),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    deck = await fs.get_owned_deck(session, current_user, deck_id)
    deck.title = body.title.strip()
    await session.commit()
    return fs.serialize_deck(deck)


@router.delete("/decks/{deck_id}", status_code=204)
async def delete_deck(
    deck_id: int,
    current_user: User = Depends(require_flashcards_enabled),
    session: AsyncSession = Depends(get_session),
) -> Response:
    deck = await fs.get_owned_deck(session, current_user, deck_id)
    card_ids = list((await session.scalars(select(Flashcard.id).where(Flashcard.deck_id == deck.id))).all())
    if card_ids:
        for review in (
            await session.scalars(select(FlashcardReview).where(FlashcardReview.card_id.in_(card_ids)))
        ).all():
            await session.delete(review)
    for card in (await session.scalars(select(Flashcard).where(Flashcard.deck_id == deck.id))).all():
        await session.delete(card)
    await session.delete(deck)
    await session.commit()
    return Response(status_code=204)


@router.post("/decks/{deck_id}/cards", status_code=201)
async def add_card(
    deck_id: int,
    body: CardCreateBody,
    current_user: User = Depends(require_flashcards_enabled),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    deck = await fs.get_owned_deck(session, current_user, deck_id)
    card = await fs.add_manual_card(
        session,
        deck,
        front_md=body.front_md,
        back_md=body.back_md,
        hint_md=body.hint_md,
        tags=body.tags,
    )
    await session.commit()
    return fs.serialize_card(card)


@router.patch("/cards/{card_id}")
async def update_card(
    card_id: int,
    body: CardUpdateBody,
    current_user: User = Depends(require_flashcards_enabled),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    card, _ = await fs.get_owned_card(session, current_user, card_id)
    if body.front_md is not None:
        card.front_md = body.front_md.strip()
    if body.back_md is not None:
        card.back_md = body.back_md.strip()
    if body.hint_md is not None:
        card.hint_md = body.hint_md.strip()
    if body.tags is not None:
        card.tags_json = [t.strip() for t in body.tags if t.strip()]
    await session.commit()
    return fs.serialize_card(card)


@router.delete("/cards/{card_id}", status_code=204)
async def delete_card(
    card_id: int,
    current_user: User = Depends(require_flashcards_enabled),
    session: AsyncSession = Depends(get_session),
) -> Response:
    card, _ = await fs.get_owned_card(session, current_user, card_id)
    for review in (await session.scalars(select(FlashcardReview).where(FlashcardReview.card_id == card.id))).all():
        await session.delete(review)
    await session.delete(card)
    await session.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Student: generation, review queue, SM-2, export
# ---------------------------------------------------------------------------


async def _resolve_generate_sources(
    session: AsyncSession, user: User, body: GenerateBody
) -> ResolvedSources:
    if body.source == "book":
        if body.book_id is None:
            raise HTTPException(status_code=422, detail="کتاب را انتخاب کنید.")
        book = await session.get(Book, body.book_id)
        if book is None:
            raise HTTPException(status_code=404, detail="کتاب یافت نشد.")
        return await resolve_book_source(
            session,
            book=book,
            chapter_number=body.chapter_number,
            page_start=body.page_start,
            page_end=body.page_end,
        )
    if body.source == "chat":
        if not body.chat_session_id:
            raise HTTPException(status_code=422, detail="گفت‌وگو را مشخص کنید.")
        return await resolve_chat_source(
            session,
            user_id=user.id,
            chat_session_id=body.chat_session_id,
            message_ids=body.message_ids,
        )
    if not body.exam_id:
        raise HTTPException(status_code=422, detail="آزمون را مشخص کنید.")
    return await resolve_mistake_source(
        session, user_id=user.id, exam_id=body.exam_id, question_ids=body.question_ids
    )


@router.post("/generate", status_code=201)
async def generate(
    body: GenerateBody,
    current_user: User = Depends(require_flashcards_enabled),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if body.deck_id is not None:
        await fs.get_owned_deck(session, current_user, body.deck_id)
    sources = await _resolve_generate_sources(session, current_user, body)
    return await fs.generate_cards(
        session,
        current_user,
        sources,
        count=body.count,
        deck_id=body.deck_id,
        new_deck_title=body.new_deck_title,
    )


@router.get("/due")
async def due(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(require_flashcards_enabled),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await fs.due_cards(session, current_user, limit=limit)


@router.post("/{card_id}/review")
async def review_card(
    card_id: int,
    body: ReviewBody,
    current_user: User = Depends(require_flashcards_enabled),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    card, _ = await fs.get_owned_card(session, current_user, card_id)
    review = await fs.apply_review(session, current_user, card, body.rating)
    # Phase 4: review outcomes feed the learner's L2/L3 memory (same transaction).
    first = (card.citations_json or [{}])[0] if card.citations_json else {}
    try:
        await record_review_outcome(
            session,
            user_id=current_user.id,
            book_id=first.get("book_id"),
            chapter_number=first.get("chapter_number"),
            topic=first.get("chapter_title") or card.front_md[:60],
            correct=body.rating >= 3,
        )
    except Exception:  # noqa: BLE001 - memory is best-effort, never blocks a review
        logger.exception("flashcards.memory_update_failed card=%s", card.id)
    await session.commit()
    return {"card_id": card.id, "review": fs.serialize_review(review)}


@router.get("/decks/{deck_id}/export/anki")
async def export_anki(
    deck_id: int,
    current_user: User = Depends(require_flashcards_enabled),
    session: AsyncSession = Depends(get_session),
) -> Response:
    deck = await fs.get_owned_deck(session, current_user, deck_id)
    detail = await fs.deck_detail(session, current_user, deck)
    if not detail["cards"]:
        raise HTTPException(status_code=422, detail="این دسته کارتی برای خروجی ندارد.")
    payload = build_apkg_bytes(deck.id, deck.title, detail["cards"])
    filename = f"darsyar-deck-{deck.id}.apkg"
    return Response(
        content=payload,
        media_type="application/apkg",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/library")
async def library(
    current_user: User = Depends(require_flashcards_enabled),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    return await fs.library_decks(session)


@router.post("/library/{deck_id}/copy", status_code=201)
async def copy_library_deck(
    deck_id: int,
    current_user: User = Depends(require_flashcards_enabled),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    source = await session.get(FlashcardDeck, deck_id)
    if source is None:
        raise HTTPException(status_code=404, detail="دستهٔ عمومی یافت نشد.")
    deck = await fs.copy_public_deck(session, current_user, source)
    await session.commit()
    stats = await fs.deck_stats(session, current_user.id, [deck.id], datetime.now(timezone.utc))
    return fs.serialize_deck(deck, stats=stats[deck.id])


# ---------------------------------------------------------------------------
# Admin: oversight & moderation
# ---------------------------------------------------------------------------


@admin_router.get("/stats")
async def admin_stats(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    decks = await session.scalar(select(func.count(FlashcardDeck.id))) or 0
    cards = await session.scalar(select(func.count(Flashcard.id))) or 0
    reviews = await session.scalar(select(func.count(FlashcardReview.id))) or 0
    public = await session.scalar(
        select(func.count(FlashcardDeck.id)).where(
            FlashcardDeck.is_public.is_(True), FlashcardDeck.admin_approved.is_(True)
        )
    ) or 0
    rating_rows = (
        await session.execute(
            select(FlashcardReview.last_rating, func.count(FlashcardReview.id)).group_by(FlashcardReview.last_rating)
        )
    ).all()
    avg_ease = await session.scalar(select(func.avg(FlashcardReview.ease_factor)))
    due_now = await session.scalar(
        select(func.count(FlashcardReview.id)).where(FlashcardReview.next_review_at <= now)
    ) or 0
    return {
        "decks": int(decks),
        "cards": int(cards),
        "reviews": int(reviews),
        "public_decks": int(public),
        "due_reviews_now": int(due_now),
        "average_ease_factor": round(float(avg_ease), 2) if avg_ease is not None else None,
        "rating_distribution": {str(r): int(c) for r, c in rating_rows if r is not None},
    }


@admin_router.get("/decks")
async def admin_list_decks(
    source_type: str | None = Query(default=None, max_length=16),
    public_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    query = select(FlashcardDeck, User).join(User, User.id == FlashcardDeck.user_id)
    if source_type:
        query = query.where(FlashcardDeck.source_type == source_type)
    if public_only:
        query = query.where(FlashcardDeck.is_public.is_(True))
    rows = (await session.execute(query.order_by(FlashcardDeck.id.desc()).limit(limit))).all()
    out = []
    for deck, owner in rows:
        card_count = await session.scalar(select(func.count(Flashcard.id)).where(Flashcard.deck_id == deck.id))
        review_count = await session.scalar(
            select(func.count(FlashcardReview.id))
            .join(Flashcard, Flashcard.id == FlashcardReview.card_id)
            .where(Flashcard.deck_id == deck.id)
        )
        out.append(
            {
                **fs.serialize_deck(deck),
                "owner": {"id": owner.id, "name": owner.full_name or owner.phone_number},
                "card_count": int(card_count or 0),
                "review_count": int(review_count or 0),
            }
        )
    return out


@admin_router.get("/decks/{deck_id}")
async def admin_deck_detail(deck_id: int, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    deck = await session.get(FlashcardDeck, deck_id)
    if deck is None:
        raise HTTPException(status_code=404, detail="دسته یافت نشد.")
    owner = await session.get(User, deck.user_id)
    cards = list((await session.scalars(select(Flashcard).where(Flashcard.deck_id == deck.id).order_by(Flashcard.id))).all())
    return {
        **fs.serialize_deck(deck),
        "owner": {"id": deck.user_id, "name": (owner.full_name or owner.phone_number) if owner else None},
        "cards": [fs.serialize_card(c) for c in cards],
    }


@admin_router.patch("/decks/{deck_id}/moderation")
async def admin_moderate_deck(
    deck_id: int,
    body: ModerationBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    deck = await session.get(FlashcardDeck, deck_id)
    if deck is None:
        raise HTTPException(status_code=404, detail="دسته یافت نشد.")
    if body.is_public and not body.admin_approved:
        raise HTTPException(status_code=422, detail="برای انتشار عمومی باید دسته تأیید شود.")
    deck.is_public = body.is_public
    deck.admin_approved = body.admin_approved
    await session.commit()
    return fs.serialize_deck(deck)


@admin_router.delete("/decks/{deck_id}", status_code=204)
async def admin_delete_deck(deck_id: int, session: AsyncSession = Depends(get_session)) -> Response:
    deck = await session.get(FlashcardDeck, deck_id)
    if deck is None:
        raise HTTPException(status_code=404, detail="دسته یافت نشد.")
    card_ids = list((await session.scalars(select(Flashcard.id).where(Flashcard.deck_id == deck.id))).all())
    if card_ids:
        for review in (
            await session.scalars(select(FlashcardReview).where(FlashcardReview.card_id.in_(card_ids)))
        ).all():
            await session.delete(review)
    for card in (await session.scalars(select(Flashcard).where(Flashcard.deck_id == deck.id))).all():
        await session.delete(card)
    await session.delete(deck)
    await session.commit()
    return Response(status_code=204)
