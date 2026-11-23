"""Flashcard domain service (Phase 3): decks, cards, due queue, SM-2 reviews,
admin stats, and AI generation through the Shared Capability Runtime.

Generation path (all AI calls go through the runtime → ai_gateway):
  resolve server-owned sources → build numbered prompt → run_capability_json
  (capability + quota enforcement, audit row) → validate → persist cards with
  server-owned citations.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.curriculum import BookPage, PageStatus
from app.models.flashcards import (
    Flashcard,
    FlashcardDeck,
    FlashcardReview,
    FlashcardStudySession,
)
from app.services import capability_runtime
from app.services.flashcard_sources import ResolvedSources
from app.services.sm2 import SchedulerState, schedule_review

logger = logging.getLogger(__name__)

CAPABILITY_KEY = "flashcards"
MASTERED_INTERVAL_DAYS = 21

# Generation options (NotebookLM-style). Count is capped at 10 to stay within
# the existing quota/cost policy; the cap is enforced in the API schema and
# again here so no alternate path can bypass it.
COUNT_OPTIONS: tuple[int, ...] = (3, 5, 10)
MAX_GENERATE_COUNT = 10
CUSTOM_PROMPT_MAX_LENGTH = 1000
DIFFICULTY_LEVELS: tuple[str, ...] = ("easy", "medium", "hard")

DIFFICULTY_INSTRUCTIONS: dict[str, str] = {
    "easy": (
        "سطح دشواری: آسان (Easy). اصطلاحات و تعاریف ساده، مفاهیم پایه، "
        "سؤال‌های مستقیم، پاسخ‌های کوتاه و قابل حفظ کردن. از سؤال‌های "
        "پیچیده یا چندمرحله‌ای پرهیز کن."
    ),
    "medium": (
        "سطح دشواری: متوسط (Medium). مفاهیم اصلی فصل، روابط بین مطالب، "
        "سؤال‌های مفهومی، درک و یادآوری مطالب."
    ),
    "hard": (
        "سطح دشواری: سخت (Hard). نکات عمیق‌تر کتاب، مقایسهٔ مفاهیم، "
        "ارتباط چند مفهوم با یکدیگر، سؤال‌هایی که فهم مطلب را می‌سنجند "
        "نه صرفاً حفظ کردن آن را."
    ),
}

# NotebookLM-style binary outcome -> SM-2 rating (see sm2.py mapping).
OUTCOME_TO_RATING: dict[str, int] = {"got": 3, "missed": 1}
RATING_TO_OUTCOME: dict[int, str] = {1: "missed", 2: "missed", 3: "got", 4: "got"}


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


def normalize_difficulty(difficulty: str | None) -> str:
    value = (difficulty or "medium").strip().lower()
    if value not in DIFFICULTY_INSTRUCTIONS:
        raise HTTPException(status_code=422, detail="سطح دشواری نامعتبر است.")
    return value


def normalize_custom_prompt(custom_prompt: str | None) -> str:
    text = (custom_prompt or "").strip()
    if len(text) > CUSTOM_PROMPT_MAX_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"دستور اختصاصی حداکثر {CUSTOM_PROMPT_MAX_LENGTH} نویسه می‌تواند باشد.",
        )
    return text


def build_generation_prompt(
    sources: ResolvedSources,
    count: int,
    difficulty: str = "medium",
    custom_prompt: str | None = None,
) -> str:
    difficulty = normalize_difficulty(difficulty)
    custom = normalize_custom_prompt(custom_prompt)
    lines = [
        f"تعداد کارت‌ها: دقیقاً {count} کارت تولید کن (نه بیشتر، نه کمتر).",
        DIFFICULTY_INSTRUCTIONS[difficulty],
        "منابع (فقط از همین‌ها کارت بساز؛ دانش بیرونی ممنوع):",
    ]
    if custom:
        lines.append(
            "تمرکز درخواستی کاربر (فقط در چارچوب منابع بالا؛ دانش بیرونی یا "
            "ارجاع تازه ممنوع):\n" + custom
        )
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


def session_counts(session_obj: FlashcardStudySession) -> dict[str, int]:
    results = dict(session_obj.results_json or {})
    total = len(list(session_obj.card_ids_json or []))
    got = sum(1 for value in results.values() if value == "got")
    missed = sum(1 for value in results.values() if value == "missed")
    rated = got + missed
    return {
        "total": total,
        "got": got,
        "missed": missed,
        "rated": rated,
        "remaining": max(0, total - rated),
        "percent": round(rated / total * 100, 1) if total else 0.0,
        "success_percent": round(got / rated * 100, 1) if rated else 0.0,
    }


def serialize_session(
    session_obj: FlashcardStudySession,
    *,
    cards: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    counts = session_counts(session_obj)
    payload: dict[str, Any] = {
        "id": session_obj.id,
        "deck_id": session_obj.deck_id,
        "mode": session_obj.mode,
        "card_ids": list(session_obj.card_ids_json or []),
        "position": int(session_obj.position or 0),
        "results": dict(session_obj.results_json or {}),
        "flipped": bool(session_obj.flipped),
        "status": session_obj.status,
        "started_at": session_obj.started_at.isoformat() if session_obj.started_at else None,
        "updated_at": session_obj.updated_at.isoformat() if session_obj.updated_at else None,
        "completed_at": session_obj.completed_at.isoformat() if session_obj.completed_at else None,
        "counts": counts,
        # Flat aliases for the results screen (kept in sync with counts).
        "total": counts["total"],
        "got_count": counts["got"],
        "missed_count": counts["missed"],
        "rated_count": counts["rated"],
        "success_percent": counts["success_percent"],
    }
    if cards is not None:
        payload["cards"] = cards
    return payload


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


async def get_owned_session(
    session: AsyncSession, user: User, session_id: int
) -> FlashcardStudySession:
    obj = await session.get(FlashcardStudySession, session_id)
    if obj is None or obj.user_id != user.id:
        raise HTTPException(status_code=404, detail="جلسهٔ مطالعه یافت نشد.")
    return obj


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
    session: AsyncSession,
    user: User,
    card: Flashcard,
    rating: int,
    now: datetime | None = None,
    *,
    session_id: int | None = None,
) -> tuple[FlashcardReview, bool]:
    """Apply one SM-2 review. With ``session_id`` the call is idempotent per
    (session, card): a second submission for the same card in the same study
    run returns the existing review without incrementing ``review_count``.
    Without a session the legacy behaviour is preserved (every call counts).

    Returns ``(review, applied)``; ``applied`` is False for an idempotent
    replay inside a study session.
    """
    now = now or datetime.now(timezone.utc)
    study_session: FlashcardStudySession | None = None
    if session_id is not None:
        study_session = await get_owned_session(session, user, session_id)
        existing = (study_session.results_json or {}).get(str(card.id))
        if existing is not None:
            review = await session.scalar(
                select(FlashcardReview).where(
                    FlashcardReview.card_id == card.id, FlashcardReview.user_id == user.id
                )
            )
            if review is not None:
                return review, False
            # Inconsistent state (session says rated but no SM-2 row): fall
            # through and apply the review once so the row exists.
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
    if study_session is not None:
        results = dict(study_session.results_json or {})
        results[str(card.id)] = RATING_TO_OUTCOME.get(rating, "missed")
        study_session.results_json = results
        study_session.flipped = False
        counts = session_counts(study_session)
        if counts["total"] > 0 and counts["rated"] >= counts["total"]:
            study_session.status = "completed"
            study_session.completed_at = now
        await session.flush()
    return review, True


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


# ---------------------------------------------------------------------------
# Study sessions (persistent NotebookLM-style runs)
# ---------------------------------------------------------------------------


async def _owned_deck_ids(session: AsyncSession, user: User, deck_id: int | None) -> list[int]:
    if deck_id is not None:
        await get_owned_deck(session, user, deck_id)
        return [deck_id]
    rows = list(
        (await session.scalars(select(FlashcardDeck.id).where(FlashcardDeck.user_id == user.id))).all()
    )
    return [int(row) for row in rows]


async def build_session_card_ids(
    session: AsyncSession,
    user: User,
    *,
    deck_id: int | None,
    mode: str,
    now: datetime | None = None,
) -> list[int]:
    """Ordered card-id snapshot for a new session.

    ``full``: every card in scope (deck or all decks), by id.
    ``smart``: only SM-2-due cards in scope (new cards first, then earliest due).
    """
    if mode not in ("full", "smart"):
        raise HTTPException(status_code=422, detail="حالت مطالعه نامعتبر است.")
    now = now or datetime.now(timezone.utc)
    deck_ids = await _owned_deck_ids(session, user, deck_id)
    if not deck_ids:
        return []
    cards = list(
        (await session.scalars(select(Flashcard).where(Flashcard.deck_id.in_(deck_ids)))).all()
    )
    if mode == "full":
        return sorted(card.id for card in cards)
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
    due: list[tuple[datetime, int]] = []
    for card in cards:
        review = reviews.get(card.id)
        if review is None:
            due.append((datetime.min.replace(tzinfo=timezone.utc), card.id))
        elif _utc(review.next_review_at) <= now:
            due.append((_utc(review.next_review_at), card.id))
    due.sort(key=lambda item: (item[0], item[1]))
    return [card_id for _, card_id in due]


async def _session_cards_payload(
    session: AsyncSession, user: User, session_obj: FlashcardStudySession
) -> list[dict[str, Any]]:
    card_ids = list(session_obj.card_ids_json or [])
    if not card_ids:
        return []
    cards = {
        c.id: c
        for c in (await session.scalars(select(Flashcard).where(Flashcard.id.in_(card_ids)))).all()
    }
    reviews = {
        r.card_id: r
        for r in (
            await session.scalars(
                select(FlashcardReview).where(
                    FlashcardReview.user_id == user.id,
                    FlashcardReview.card_id.in_(card_ids),
                )
            )
        ).all()
    }
    ordered: list[dict[str, Any]] = []
    for card_id in card_ids:
        card = cards.get(card_id)
        if card is None:
            continue  # deleted card: skip in payload (cleaned on next write)
        payload = serialize_card(card, review=reviews.get(card_id))
        payload["session_result"] = (session_obj.results_json or {}).get(str(card_id))
        ordered.append(payload)
    return ordered


async def serialize_session_detail(
    session: AsyncSession, user: User, session_obj: FlashcardStudySession
) -> dict[str, Any]:
    cards = await _session_cards_payload(session, user, session_obj)
    return serialize_session(session_obj, cards=cards)


async def find_active_session(
    session: AsyncSession, user: User, *, deck_id: int | None, mode: str
) -> FlashcardStudySession | None:
    query = select(FlashcardStudySession).where(
        FlashcardStudySession.user_id == user.id,
        FlashcardStudySession.mode == mode,
        FlashcardStudySession.status == "in_progress",
    )
    if deck_id is None:
        query = query.where(FlashcardStudySession.deck_id.is_(None))
    else:
        query = query.where(FlashcardStudySession.deck_id == deck_id)
    query = query.order_by(
        FlashcardStudySession.updated_at.desc(), FlashcardStudySession.id.desc()
    ).limit(1)
    return await session.scalar(query)


async def list_active_sessions(session: AsyncSession, user: User) -> list[FlashcardStudySession]:
    rows = list(
        (
            await session.scalars(
                select(FlashcardStudySession)
                .where(
                    FlashcardStudySession.user_id == user.id,
                    FlashcardStudySession.status == "in_progress",
                )
                .order_by(FlashcardStudySession.updated_at.desc(), FlashcardStudySession.id.desc())
            )
        ).all()
    )
    return rows


async def _create_session(
    session: AsyncSession,
    user: User,
    *,
    deck_id: int | None,
    mode: str,
    card_ids: list[int],
    shuffle: bool,
) -> FlashcardStudySession:
    ordered = list(card_ids)
    if shuffle:
        random.shuffle(ordered)
    obj = FlashcardStudySession(
        user_id=user.id,
        deck_id=deck_id,
        mode=mode,
        card_ids_json=ordered,
        position=0,
        results_json={},
        flipped=False,
        status="in_progress",
    )
    session.add(obj)
    await session.flush()
    return obj


async def start_or_resume_session(
    session: AsyncSession,
    user: User,
    *,
    deck_id: int | None,
    mode: str,
    shuffle: bool = False,
    card_ids: list[int] | None = None,
    force_new: bool = False,
) -> FlashcardStudySession:
    if deck_id is not None:
        await get_owned_deck(session, user, deck_id)
    if card_ids is not None:
        # Explicit subset (e.g. "only missed"): validate ownership, keep order.
        if not card_ids:
            raise HTTPException(status_code=422, detail="کارت‌ای برای این جلسه انتخاب نشده است.")
        if len(set(card_ids)) != len(card_ids):
            raise HTTPException(status_code=422, detail="فهرست کارت‌ها تکراری است.")
        if len(card_ids) > 500:
            raise HTTPException(status_code=422, detail="تعداد کارت‌های جلسه بیش از حد مجاز است.")
        for card_id in card_ids:
            await get_owned_card(session, user, card_id)
        return await _create_session(
            session, user, deck_id=deck_id, mode=mode, card_ids=list(card_ids), shuffle=shuffle
        )
    if not force_new and not shuffle:
        active = await find_active_session(session, user, deck_id=deck_id, mode=mode)
        if active is not None:
            return active
    if force_new:
        active = await find_active_session(session, user, deck_id=deck_id, mode=mode)
        if active is not None:
            active.status = "completed"
            active.completed_at = datetime.now(timezone.utc)
            await session.flush()
    ids = await build_session_card_ids(session, user, deck_id=deck_id, mode=mode)
    if not ids:
        if mode == "smart":
            raise HTTPException(status_code=422, detail="برای مرور هوشمند کارتی در موعد نیست. آفرین!")
        raise HTTPException(status_code=422, detail="این دسته کارتی برای مطالعه ندارد.")
    return await _create_session(
        session, user, deck_id=deck_id, mode=mode, card_ids=ids, shuffle=shuffle
    )


async def update_session_progress(
    session: AsyncSession,
    session_obj: FlashcardStudySession,
    *,
    position: int | None = None,
    flipped: bool | None = None,
) -> FlashcardStudySession:
    total = len(list(session_obj.card_ids_json or []))
    if position is not None:
        if position < 0 or position > max(0, total - 1):
            # Allow position == total only for an empty session; otherwise clamp check.
            if not (total == 0 and position == 0):
                raise HTTPException(status_code=422, detail="موقعیت کارت نامعتبر است.")
        session_obj.position = position
    if flipped is not None:
        session_obj.flipped = bool(flipped)
    await session.flush()
    return session_obj


async def shuffle_session(
    session: AsyncSession, session_obj: FlashcardStudySession
) -> FlashcardStudySession:
    card_ids = list(session_obj.card_ids_json or [])
    if len(card_ids) < 2:
        return session_obj
    current_id: int | None = None
    if 0 <= int(session_obj.position or 0) < len(card_ids):
        current_id = card_ids[int(session_obj.position or 0)]
    shuffled = list(card_ids)
    random.shuffle(shuffled)
    session_obj.card_ids_json = shuffled
    if current_id is not None and current_id in shuffled:
        session_obj.position = shuffled.index(current_id)
    await session.flush()
    return session_obj


async def restart_session(
    session: AsyncSession,
    session_obj: FlashcardStudySession,
    *,
    shuffle: bool = False,
) -> FlashcardStudySession:
    # Drop cards that no longer exist (deleted since the run started).
    card_ids = list(session_obj.card_ids_json or [])
    if card_ids:
        existing = set(
            (await session.scalars(select(Flashcard.id).where(Flashcard.id.in_(card_ids)))).all()
        )
        card_ids = [cid for cid in card_ids if cid in existing]
    if not card_ids:
        raise HTTPException(status_code=422, detail="کارت فعالی برای شروع مجدد باقی نمانده است.")
    if shuffle:
        random.shuffle(card_ids)
    session_obj.card_ids_json = card_ids
    session_obj.position = 0
    session_obj.results_json = {}
    session_obj.flipped = False
    session_obj.status = "in_progress"
    session_obj.started_at = datetime.now(timezone.utc)
    session_obj.completed_at = None
    await session.flush()
    return session_obj


async def complete_session(
    session: AsyncSession, session_obj: FlashcardStudySession
) -> FlashcardStudySession:
    session_obj.status = "completed"
    session_obj.completed_at = datetime.now(timezone.utc)
    await session.flush()
    return session_obj


async def clean_card_from_sessions(session: AsyncSession, card_id: int) -> None:
    """Remove a deleted card from every study session (results + order)."""
    rows = list(
        (await session.scalars(select(FlashcardStudySession))).all()
    )
    for obj in rows:
        card_ids = list(obj.card_ids_json or [])
        if card_id not in card_ids:
            continue
        old_position = int(obj.position or 0)
        current_id = card_ids[old_position] if 0 <= old_position < len(card_ids) else None
        card_ids = [cid for cid in card_ids if cid != card_id]
        results = dict(obj.results_json or {})
        results.pop(str(card_id), None)
        obj.card_ids_json = card_ids
        obj.results_json = results
        if not card_ids:
            obj.position = 0
            obj.flipped = False
            if obj.status == "in_progress":
                obj.status = "completed"
                obj.completed_at = datetime.now(timezone.utc)
        elif current_id is not None and current_id != card_id:
            obj.position = card_ids.index(current_id) if current_id in card_ids else min(old_position, len(card_ids) - 1)
        else:
            obj.position = min(old_position, len(card_ids) - 1)
        await session.flush()


async def clean_deck_from_sessions(
    session: AsyncSession, deck_id: int, card_ids: list[int] | None = None
) -> None:
    """Delete deck-scoped sessions and strip removed cards from all-decks runs.

    ``card_ids`` should be the deck's card ids captured *before* deletion;
    they are removed from any remaining session snapshots.
    """
    scoped = list(
        (
            await session.scalars(
                select(FlashcardStudySession).where(FlashcardStudySession.deck_id == deck_id)
            )
        ).all()
    )
    for obj in scoped:
        await session.delete(obj)
    await session.flush()
    if card_ids:
        for card_id in card_ids:
            await clean_card_from_sessions(session, card_id)


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
    difficulty: str = "medium",
    custom_prompt: str | None = None,
) -> dict[str, Any]:
    """Generate cards from resolved sources via the runtime (quota + audit + gateway)."""
    difficulty = normalize_difficulty(difficulty)
    custom_prompt = normalize_custom_prompt(custom_prompt)
    if count < 1:
        raise HTTPException(status_code=422, detail="تعداد کارت باید حداقل ۱ باشد.")
    if count > MAX_GENERATE_COUNT:
        raise HTTPException(
            status_code=422, detail=f"حداکثر {MAX_GENERATE_COUNT} کارت در هر تولید مجاز است."
        )
    if deck_id is not None:
        deck = await get_owned_deck(session, user, deck_id)
    else:
        deck = None

    prompt = build_generation_prompt(sources, count, difficulty, custom_prompt or None)
    from app.services.learner_memory_service import build_memory_context

    memory_context = await build_memory_context(session, user.id, sources.book_id)
    try:
        result, _ = await capability_runtime.run_capability_json(
            extra_system=memory_context or None,
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


# ---------------------------------------------------------------------------
# Explain ("توضیح بیشتر") — textbook-grounded, through the central runtime
# ---------------------------------------------------------------------------

EXPLAIN_CONTEXT_CHARS = 6000

EXPLAIN_SYSTEM_RULES = (
    "تو معلم خصوصی فارسیِ دانش‌آموزان ایران هستی. فقط از متن کتاب و محتوای "
    "ذخیره‌شدهٔ کارت استفاده کن. هیچ اطلاعات، فرمول یا استناد جدیدی از دانش "
    "عمومی خود اضافه نکن. فرمول‌ها را با LaTeX در علامت دلار ($...$) بنویس. "
    "پاسخ را به‌صورت متن و Markdown سادهٔ فارسی بده؛ هیچ‌گاه JSON برنگردان."
)


async def _explain_context(
    session: AsyncSession, card: Flashcard
) -> tuple[str, list[dict[str, Any]], bool]:
    """Fetch the server-side textbook pages behind the card's citations.

    Returns ``(context_text, citations, source_found)``. When the cited pages
    cannot be retrieved, the context falls back to the stored card content and
    ``source_found`` is False so the caller can forbid new citations.
    """
    citations = [c for c in (card.citations_json or []) if isinstance(c, dict)]
    page_keys: list[tuple[int, int]] = []
    for citation in citations:
        book_id = citation.get("book_id")
        page_index = citation.get("pdf_page_index")
        if book_id is None or page_index is None:
            continue
        try:
            page_keys.append((int(book_id), int(page_index)))
        except (TypeError, ValueError):
            continue
    texts: list[str] = []
    used_citations: list[dict[str, Any]] = []
    if page_keys:
        for book_id, page_index in page_keys:
            page = await session.scalar(
                select(BookPage).where(
                    BookPage.book_id == book_id,
                    BookPage.pdf_page_index == page_index,
                    BookPage.status.in_([PageStatus.done, PageStatus.needs_review]),
                )
            )
            if page is None or not (page.markdown_content or "").strip():
                continue
            texts.append(page.markdown_content.strip())
            for citation in citations:
                try:
                    if (
                        int(citation.get("book_id")) == book_id  # type: ignore[arg-type]
                        and int(citation.get("pdf_page_index")) == page_index  # type: ignore[arg-type]
                    ):
                        used_citations.append(citation)
                except (TypeError, ValueError):
                    continue
            if sum(len(t) for t in texts) >= EXPLAIN_CONTEXT_CHARS:
                break
    if texts:
        context = "\n\n---\n\n".join(texts)[:EXPLAIN_CONTEXT_CHARS]
        return context, used_citations, True
    # Fallback: stored card content only. No invented citations allowed.
    parts = [f"روی کارت:\n{card.front_md}", f"پشت کارت:\n{card.back_md}"]
    if (card.hint_md or "").strip():
        parts.append(f"راهنما:\n{card.hint_md}")
    return "\n\n".join(parts), [], False


async def explain_card(
    session: AsyncSession,
    user: User,
    card: Flashcard,
    deck: FlashcardDeck,
) -> dict[str, Any]:
    context, citations, source_found = await _explain_context(session, card)
    citation_labels = [str(c.get("citation") or "") for c in citations if c.get("citation")]
    if source_found:
        cite_note = "متن کتابِ منبع را مستقیماً می‌بینی؛ در پایان توضیح، فقط به همین صفحات ارجاع بده."
    else:
        cite_note = (
            "متن اصلی کتاب قابل بازیابی نیست؛ توضیح را فقط بر اساس محتوای کارت بده "
            "و هیچ ارجاع یا استناد جدیدی ادعا نکن."
        )
    user_text = (
        "این فلش‌کارت را برای دانش‌آموز ساده و گام‌به‌گام توضیح بده. "
        "مفهوم اصلی را تشریح کن، یک مثال ساده بزن، فرمول‌های ریاضی را درست بنویس، "
        "و از اطلاعات نامرتبط خودداری کن.\n\n"
        f"{cite_note}\n\n"
        f"کارت ({card.front_md[:200]}):\nروی کارت: {card.front_md}\nپشت کارت: {card.back_md}\n\n"
        f"متن مرجع:\n{context}"
    )
    from app.services import capability_runtime as runtime

    try:
        result, _blocks, _skill = await runtime.run_capability_text(
            session=session,
            capability_key=CAPABILITY_KEY,
            feature_key=CAPABILITY_KEY,
            user_text=user_text,
            user_id=user.id,
            user=user,
            book_id=citations[0].get("book_id") if citations else None,
            textbook_strict=True,
            citations=citations,
            rag_hit_count=1 if source_found else 0,
            extra_system=EXPLAIN_SYSTEM_RULES,
            # The shared "flashcards" skill is a JSON generator; keep the
            # capability's quota/flag/audit/gateway path but not its output
            # contract for free-text explanations.
            load_skill=False,
        )
    except HTTPException:
        raise
    except Exception as error:  # noqa: BLE001 - never leak provider details
        await session.commit()
        raise HTTPException(
            status_code=502, detail="توضیح با خطا روبه‌رو شد. لطفاً دوباره تلاش کنید."
        ) from error
    await session.commit()
    return {
        "card_id": card.id,
        "deck_id": deck.id,
        "explanation": result.content,
        "source_available": source_found,
        "citations": citations,
        "citation": citation_labels[0] if citation_labels else None,
        "audit_id": result.audit_id,
    }


__all__ = [
    "CAPABILITY_KEY",
    "COUNT_OPTIONS",
    "CUSTOM_PROMPT_MAX_LENGTH",
    "DIFFICULTY_LEVELS",
    "MAX_GENERATE_COUNT",
    "OUTCOME_TO_RATING",
    "RATING_TO_OUTCOME",
    "GeneratedCardSet",
    "add_manual_card",
    "apply_review",
    "build_generation_prompt",
    "build_session_card_ids",
    "clean_card_from_sessions",
    "clean_deck_from_sessions",
    "copy_public_deck",
    "create_deck",
    "deck_detail",
    "deck_stats",
    "due_cards",
    "explain_card",
    "generate_cards",
    "get_owned_card",
    "get_owned_deck",
    "get_owned_session",
    "library_decks",
    "list_active_sessions",
    "list_user_decks",
    "normalize_custom_prompt",
    "normalize_difficulty",
    "restart_session",
    "complete_session",
    "serialize_card",
    "serialize_deck",
    "serialize_review",
    "serialize_session",
    "serialize_session_detail",
    "session_counts",
    "shuffle_session",
    "start_or_resume_session",
    "update_session_progress",
]
