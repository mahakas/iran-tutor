"""Flashcard domain service (Phase 3): decks, cards, due queue, SM-2 reviews,
admin stats, and AI generation through the Shared Capability Runtime.

Generation path (all AI calls go through the runtime → ai_gateway):
  resolve server-owned sources → build numbered prompt → run_capability_json
  (capability + quota enforcement, audit row) → validate → persist cards with
  server-owned citations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.flashcards import Flashcard, FlashcardDeck, FlashcardReview
from app.services import capability_runtime
from app.services.flashcard_sources import ResolvedSources
from app.services.sm2 import SchedulerState, schedule_review

CAPABILITY_KEY = "flashcards"
MASTERED_INTERVAL_DAYS = 21


# ---------------------------------------------------------------------------
# Structured model output
# ---------------------------------------------------------------------------


class GeneratedCard(BaseModel):
    front_md: str = Field(min_length=1, max_length=1200)
    back_md: str = Field(min_length=1, max_length=2000)
    hint_md: str = Field(default="", max_length=600)
    source_index: int = Field(ge=0)
    tags: list[str] = Field(default_factory=list, max_length=5)


class GeneratedCardSet(BaseModel):
    cards: list[GeneratedCard] = Field(min_length=1)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def build_generation_prompt(sources: ResolvedSources, count: int) -> str:
    lines = [
        f"تعداد کارت‌ها: {count}",
        "منابع (فقط از همین‌ها کارت بساز؛ دانش بیرونی ممنوع):",
    ]
    for index, item in enumerate(sources.items):
        refs = "؛ ".join(c.get("citation", "") for c in item.citations)
        lines.append(f"\n[منبع {index}] ({refs})\n{item.text}")
    lines.append(
        "\nخروجی فقط یک JSON معتبر با این شکل باشد:\n"
        '{"cards":[{"front_md":"روی کارت","back_md":"پشت کارت","hint_md":"راهنما",'
        '"source_index":0,"tags":["برچسب"]}]}\n'
        "قواعد: source_index باید شمارهٔ یکی از منابع بالا باشد؛ "
        "فرمول‌ها را با LaTeX در علامت دلار ($...$) بنویس؛ متن فارسی را دقیق نگه دار."
    )
    return "\n".join(lines)


def default_deck_title(sources: ResolvedSources) -> str:
    return (sources.title_hint or "دستهٔ جدید")[:255]


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def serialize_card(card: Flashcard, *, review: FlashcardReview | None = None) -> dict[str, Any]:
    return {
        "id": card.id,
        "deck_id": card.deck_id,
        "front_md": card.front_md,
        "back_md": card.back_md,
        "hint_md": card.hint_md or "",
        "citations": list(card.citations_json or []),
        "tags": list(card.tags_json or []),
        "review": serialize_review(review) if review else None,
    }


def serialize_review(review: FlashcardReview) -> dict[str, Any]:
    return {
        "ease_factor": review.ease_factor,
        "interval_days": review.interval_days,
        "repetitions": review.repetitions,
        "next_review_at": _utc(review.next_review_at).isoformat(),
        "last_rating": review.last_rating,
        "review_count": review.review_count,
    }


def serialize_deck(deck: FlashcardDeck, *, stats: dict[str, int] | None = None) -> dict[str, Any]:
    stats = stats or {"total": 0, "due": 0, "mastered": 0, "new": 0}
    total = stats["total"]
    return {
        "id": deck.id,
        "title": deck.title,
        "book_id": deck.book_id,
        "chapter_number": deck.chapter_number,
        "page_start": deck.page_start,
        "page_end": deck.page_end,
        "source_type": deck.source_type,
        "is_public": bool(deck.is_public),
        "admin_approved": bool(deck.admin_approved),
        "created_at": deck.created_at.isoformat() if deck.created_at else None,
        "stats": {
            **stats,
            "progress_percent": round(stats["mastered"] / total * 100, 1) if total else 0.0,
        },
    }


# ---------------------------------------------------------------------------
# Ownership helpers
# ---------------------------------------------------------------------------


async def get_owned_deck(session: AsyncSession, user: User, deck_id: int) -> FlashcardDeck:
    deck = await session.get(FlashcardDeck, deck_id)
    if deck is None or deck.user_id != user.id:
        raise HTTPException(status_code=404, detail="دسته یافت نشد.")
    return deck


async def get_owned_card(session: AsyncSession, user: User, card_id: int) -> tuple[Flashcard, FlashcardDeck]:
    card = await session.get(Flashcard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="کارت یافت نشد.")
    deck = await session.get(FlashcardDeck, card.deck_id)
    if deck is None or deck.user_id != user.id:
        raise HTTPException(status_code=404, detail="کارت یافت نشد.")
    return card, deck


# ---------------------------------------------------------------------------
# Decks & cards
# ---------------------------------------------------------------------------


async def deck_stats(session: AsyncSession, user_id: str, deck_ids: list[int], now: datetime) -> dict[int, dict[str, int]]:
    """Per-deck totals computed for one user (new = no review row yet)."""
    out: dict[int, dict[str, int]] = {d: {"total": 0, "due": 0, "mastered": 0, "new": 0} for d in deck_ids}
    if not deck_ids:
        return out
    cards = list((await session.scalars(select(Flashcard).where(Flashcard.deck_id.in_(deck_ids)))).all())
    reviews = {
        r.card_id: r
        for r in (
            await session.scalars(
                select(FlashcardReview).where(
                    FlashcardReview.user_id == user_id,
                    FlashcardReview.card_id.in_([c.id for c in cards]) if cards else False,
                )
            )
        ).all()
    }
    for card in cards:
        bucket = out[card.deck_id]
        bucket["total"] += 1
        review = reviews.get(card.id)
        if review is None:
            bucket["new"] += 1
            bucket["due"] += 1
            continue
        if _utc(review.next_review_at) <= now:
            bucket["due"] += 1
        if review.interval_days >= MASTERED_INTERVAL_DAYS:
            bucket["mastered"] += 1
    return out


async def list_user_decks(session: AsyncSession, user: User, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    decks = list(
        (
            await session.scalars(
                select(FlashcardDeck).where(FlashcardDeck.user_id == user.id).order_by(FlashcardDeck.id.desc())
            )
        ).all()
    )
    stats = await deck_stats(session, user.id, [d.id for d in decks], now)
    return [serialize_deck(d, stats=stats[d.id]) for d in decks]


async def create_deck(
    session: AsyncSession,
    user: User,
    *,
    title: str,
    source_type: str = "manual",
    book_id: int | None = None,
    chapter_number: int | None = None,
    page_start: int | None = None,
    page_end: int | None = None,
) -> FlashcardDeck:
    deck = FlashcardDeck(
        user_id=user.id,
        title=title.strip()[:255] or "دستهٔ جدید",
        source_type=source_type,
        book_id=book_id,
        chapter_number=chapter_number,
        page_start=page_start,
        page_end=page_end,
        is_public=False,
        admin_approved=False,
    )
    session.add(deck)
    await session.flush()
    return deck


async def deck_detail(session: AsyncSession, user: User, deck: FlashcardDeck, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    cards = list(
        (await session.scalars(select(Flashcard).where(Flashcard.deck_id == deck.id).order_by(Flashcard.id))).all()
    )
    reviews = {
        r.card_id: r
        for r in (
            await session.scalars(
                select(FlashcardReview).where(
                    FlashcardReview.user_id == user.id,
                    FlashcardReview.card_id.in_([c.id for c in cards]) if cards else False,
                )
            )
        ).all()
    }
    stats = await deck_stats(session, user.id, [deck.id], now)
    return {
        **serialize_deck(deck, stats=stats[deck.id]),
        "cards": [serialize_card(c, review=reviews.get(c.id)) for c in cards],
    }


async def add_manual_card(
    session: AsyncSession,
    deck: FlashcardDeck,
    *,
    front_md: str,
    back_md: str,
    hint_md: str = "",
    tags: list[str] | None = None,
    citations: list[dict[str, Any]] | None = None,
) -> Flashcard:
    card = Flashcard(
        deck_id=deck.id,
        front_md=front_md.strip(),
        back_md=back_md.strip(),
        hint_md=(hint_md or "").strip(),
        citations_json=list(citations or []),
        tags_json=list(tags or []),
    )
    session.add(card)
    await session.flush()
    return card


async def apply_review(
    session: AsyncSession, user: User, card: Flashcard, rating: int, now: datetime | None = None
) -> FlashcardReview:
    now = now or datetime.now(timezone.utc)
    review = await session.scalar(
        select(FlashcardReview).where(
            FlashcardReview.card_id == card.id, FlashcardReview.user_id == user.id
        )
    )
    state = (
        SchedulerState(review.ease_factor, review.interval_days, review.repetitions)
        if review is not None
        else SchedulerState()
    )
    result = schedule_review(state, rating, now)
    if review is None:
        review = FlashcardReview(card_id=card.id, user_id=user.id, review_count=0)
        session.add(review)
    review.ease_factor = result.ease_factor
    review.interval_days = result.interval_days
    review.repetitions = result.repetitions
    review.next_review_at = result.next_review_at
    review.last_rating = result.last_rating
    review.review_count = (review.review_count or 0) + 1
    review.reviewed_at = now
    await session.flush()
    return review


async def due_cards(session: AsyncSession, user: User, *, limit: int = 50, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    decks = {
        d.id: d
        for d in (await session.scalars(select(FlashcardDeck).where(FlashcardDeck.user_id == user.id))).all()
    }
    if not decks:
        return {"due_count": 0, "cards": []}
    cards = list(
        (await session.scalars(select(Flashcard).where(Flashcard.deck_id.in_(list(decks))))).all()
    )
    reviews = {
        r.card_id: r
        for r in (
            await session.scalars(
                select(FlashcardReview).where(
                    FlashcardReview.user_id == user.id,
                    FlashcardReview.card_id.in_([c.id for c in cards]) if cards else False,
                )
            )
        ).all()
    }
    due: list[tuple[datetime, Flashcard]] = []
    for card in cards:
        review = reviews.get(card.id)
        if review is None:
            due.append((datetime.min.replace(tzinfo=timezone.utc), card))  # new cards first
        elif _utc(review.next_review_at) <= now:
            due.append((_utc(review.next_review_at), card))
    due.sort(key=lambda item: (item[0], item[1].id))
    items = []
    for _, card in due[:limit]:
        payload = serialize_card(card, review=reviews.get(card.id))
        payload["deck_title"] = decks[card.deck_id].title
        items.append(payload)
    return {"due_count": len(due), "cards": items}


async def copy_public_deck(session: AsyncSession, user: User, source_deck: FlashcardDeck) -> FlashcardDeck:
    if not (source_deck.is_public and source_deck.admin_approved):
        raise HTTPException(status_code=404, detail="دستهٔ عمومی یافت نشد.")
    deck = await create_deck(
        session,
        user,
        title=source_deck.title,
        source_type=source_deck.source_type,
        book_id=source_deck.book_id,
        chapter_number=source_deck.chapter_number,
        page_start=source_deck.page_start,
        page_end=source_deck.page_end,
    )
    cards = list((await session.scalars(select(Flashcard).where(Flashcard.deck_id == source_deck.id))).all())
    for card in cards:
        await add_manual_card(
            session,
            deck,
            front_md=card.front_md,
            back_md=card.back_md,
            hint_md=card.hint_md,
            tags=list(card.tags_json or []),
            citations=list(card.citations_json or []),
        )
    return deck


async def library_decks(session: AsyncSession) -> list[dict[str, Any]]:
    decks = list(
        (
            await session.scalars(
                select(FlashcardDeck)
                .where(FlashcardDeck.is_public.is_(True), FlashcardDeck.admin_approved.is_(True))
                .order_by(FlashcardDeck.id.desc())
            )
        ).all()
    )
    out = []
    for deck in decks:
        count = await session.scalar(select(func.count(Flashcard.id)).where(Flashcard.deck_id == deck.id))
        payload = serialize_deck(deck)
        payload["stats"]["total"] = int(count or 0)
        out.append(payload)
    return out


# ---------------------------------------------------------------------------
# AI generation
# ---------------------------------------------------------------------------


async def generate_cards(
    session: AsyncSession,
    user: User,
    sources: ResolvedSources,
    *,
    count: int,
    deck_id: int | None,
    new_deck_title: str | None,
) -> dict[str, Any]:
    """Generate cards from resolved sources via the runtime (quota + audit + gateway)."""
    if deck_id is not None:
        deck = await get_owned_deck(session, user, deck_id)
    else:
        deck = None

    prompt = build_generation_prompt(sources, count)
    try:
        result, _ = await capability_runtime.run_capability_json(
            session=session,
            capability_key=CAPABILITY_KEY,
            feature_key=CAPABILITY_KEY,
            user_text=prompt,
            user_id=user.id,
            user=user,
            book_id=sources.book_id,
            textbook_strict=True,
            citations=sources.all_citations,
            rag_hit_count=len(sources.items),
        )
    except HTTPException:
        raise  # capability / quota gate: rejected before any model call
    except Exception as error:  # noqa: BLE001 - never leak provider details
        # The gateway's audit row (error status) lives in this session: persist it.
        await session.commit()
        raise HTTPException(status_code=502, detail="تولید فلش‌کارت با خطا روبه‌رو شد. لطفاً دوباره تلاش کنید.") from error

    # Persist the audit row + quota usage before validating the output, so a
    # bad model response is still observable and counted.
    await session.commit()
    try:
        parsed = GeneratedCardSet.model_validate(result.content)
    except ValidationError as error:
        raise HTTPException(status_code=502, detail="پاسخ مدل برای فلش‌کارت معتبر نبود. لطفاً دوباره تلاش کنید.") from error

    valid = [c for c in parsed.cards if c.source_index < len(sources.items)][:count]
    if not valid:
        raise HTTPException(status_code=502, detail="هیچ کارت معتبر و مستندی تولید نشد. لطفاً دوباره تلاش کنید.")

    if deck is None:
        deck = await create_deck(
            session,
            user,
            title=(new_deck_title or default_deck_title(sources)),
            source_type=sources.source_type,
            book_id=sources.book_id,
            chapter_number=sources.chapter_number,
            page_start=sources.page_start,
            page_end=sources.page_end,
        )
    created: list[Flashcard] = []
    for card in valid:
        created.append(
            await add_manual_card(
                session,
                deck,
                front_md=card.front_md,
                back_md=card.back_md,
                hint_md=card.hint_md,
                tags=card.tags,
                # Citations are the server-owned source items, never model-written.
                citations=sources.items[card.source_index].citations,
            )
        )
    await session.commit()
    return {
        "deck_id": deck.id,
        "created_count": len(created),
        "requested_count": count,
        "audit_id": result.audit_id,
        "cards": [serialize_card(c) for c in created],
    }


__all__ = [
    "CAPABILITY_KEY",
    "GeneratedCardSet",
    "add_manual_card",
    "apply_review",
    "build_generation_prompt",
    "copy_public_deck",
    "create_deck",
    "deck_detail",
    "deck_stats",
    "due_cards",
    "generate_cards",
    "get_owned_card",
    "get_owned_deck",
    "library_decks",
    "list_user_decks",
    "serialize_card",
    "serialize_deck",
    "serialize_review",
]
