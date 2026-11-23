"""Phase 4 flashcards tests: NotebookLM-style generation options (count /
difficulty / custom prompt), explain, persistent study sessions, CSV export,
and delete cleanup.

No network I/O: the model calls are replaced by deterministic fakes; the
gateway, quota enforcement, audit logging and grounding checks still run.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import require_student
from app.db.base import Base
from app.db.seed import seed_billing_settings, seed_curriculum_taxonomy, seed_grades, seed_majors, seed_plans
from app.db.session import get_session
from app.main import app
from app.models.auth import User
from app.models.capabilities import Capability
from app.models.curriculum import Book, BookPage, BookStatus, Grade, Major, PageStatus
from app.models.flashcards import Flashcard, FlashcardDeck, FlashcardReview, FlashcardStudySession
from app.models.governance import AiAuditLog
from app.services import capability_service, flashcard_service, skill_seed
from app.services import ai_gateway

ADMIN_HEADERS = {"X-Admin-Username": "admin", "X-Admin-Password": "123"}
NOW = datetime(2026, 11, 21, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
async def env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'phase4.sqlite3'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    ids: dict[str, object] = {}
    async with factory() as session:
        await seed_grades(session)
        await seed_majors(session)
        await seed_curriculum_taxonomy(session)
        await seed_plans(session)
        await seed_billing_settings(session)
        await capability_service.seed_capabilities(session)
        await skill_seed.seed_skills(session)
        grade = await session.scalar(select(Grade).where(Grade.number == 10))
        major = await session.scalar(select(Major).limit(1))
        book = Book(
            title="ریاضی دهم",
            grade_id=grade.id,
            major_id=major.id if major else None,
            pdf_file_path="/tmp/none.pdf",
            total_pdf_pages=10,
            status=BookStatus.ready,
            catalog_status="approved",
        )
        session.add(book)
        await session.flush()
        for index, printed in ((1, 10), (2, 11), (3, 12)):
            session.add(
                BookPage(
                    book_id=book.id,
                    pdf_page_index=index,
                    printed_page_number=printed,
                    chapter_number=3,
                    chapter_title="توان",
                    markdown_content=f"متن صفحهٔ {printed} با فرمول $x^2$",
                    page_image_path="/tmp/none.png",
                    status=PageStatus.done,
                )
            )
        student = User(
            phone_number="09120000011",
            full_name="دانش‌آموز چهار",
            role="student",
            tokens_remaining=1_000_000,
            plan_expires_at=NOW + timedelta(days=30),
            is_active=True,
        )
        other = User(
            phone_number="09120000012",
            full_name="دیگری چهار",
            role="student",
            tokens_remaining=1_000_000,
            plan_expires_at=NOW + timedelta(days=30),
            is_active=True,
        )
        session.add_all([student, other])
        await session.flush()
        await session.commit()
        ids.update(book_id=book.id, student_id=student.id, other_id=other.id)

    async def override_get_session():
        async with factory() as session:
            yield session

    async def override_student():
        async with factory() as session:
            return await session.get(User, ids["student_id"])

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[require_student] = override_student
    from app.db import session as db_session_mod

    monkeypatch.setattr(db_session_mod, "async_session_factory", factory)
    monkeypatch.setattr(ai_gateway, "async_session_factory", factory)
    monkeypatch.setattr(ai_gateway, "get_settings",
                        lambda: SimpleNamespace(tutor_model="test-model", llm_timeout=5))

    calls: list[list[dict[str, str]]] = []
    text_calls: list[list[dict[str, str]]] = []

    async def fake_complete_json(model, messages):
        calls.append(messages)
        return {
            "cards": [
                {"front_md": "توان دوم یعنی چه؟", "back_md": "ضرب عدد در خودش، مثل $x^2$",
                 "hint_md": "به ضرب فکر کنید", "source_index": 0, "tags": ["توان"]},
                {"front_md": "جذر یعنی چه؟", "back_md": "عمل معکوس توان دوم",
                 "hint_md": "", "source_index": 0, "tags": ["جذر"]},
                {"front_md": "کارت بدون منبع معتبر", "back_md": "x", "hint_md": "",
                 "source_index": 99, "tags": []},
            ]
        }

    async def fake_complete_text(model, messages):
        text_calls.append(messages)
        return "توان دوم یعنی ضرب عدد در خودش؛ مثال: $3^2 = 9$. این مفهوم پایه‌ایِ فصل است."

    monkeypatch.setattr(ai_gateway, "complete_json", fake_complete_json)
    monkeypatch.setattr(ai_gateway, "complete_text", fake_complete_text)

    env_obj = SimpleNamespace(factory=factory, ids=ids, calls=calls, text_calls=text_calls)
    yield env_obj
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(require_student, None)
    await engine.dispose()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _make_deck_with_cards(env, n: int = 3, *, with_citations: bool = False) -> tuple[int, list[int]]:
    async with env.factory() as session:
        deck = FlashcardDeck(user_id=env.ids["student_id"], title="دستهٔ تست", source_type="manual")
        session.add(deck)
        await session.flush()
        card_ids: list[int] = []
        for index in range(n):
            citations = []
            if with_citations:
                citations = [
                    {
                        "book_id": env.ids["book_id"],
                        "book_title": "ریاضی دهم",
                        "grade_number": 10,
                        "chapter_number": 3,
                        "chapter_title": "توان",
                        "pdf_page_index": 1,
                        "printed_page_number": 10,
                        "citation": "ریاضی دهم، فصل ۳، صفحهٔ ۱۰",
                    }
                ]
            card = await flashcard_service.add_manual_card(
                session,
                deck,
                front_md=f"روی کارت {index}",
                back_md=f"پشت کارت {index}",
                hint_md=f"راهنمای {index}" if index == 0 else "",
                tags=["تست", f"برچسب{index}"],
                citations=citations,
            )
            card_ids.append(card.id)
        await session.commit()
        return deck.id, card_ids


async def _start_session(client: AsyncClient, deck_id: int | None, mode: str = "full",
                         **extra) -> dict:
    body = {"deck_id": deck_id, "mode": mode, **extra}
    resp = await client.post("/api/v1/flashcards/sessions", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Generation: difficulty, custom prompt, count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "difficulty,expected",
    [("easy", "سطح دشواری: آسان"), ("medium", "سطح دشواری: متوسط"), ("hard", "سطح دشواری: سخت")],
)
async def test_generate_difficulty_levels_reach_model_prompt(env, difficulty, expected):
    async with _client() as client:
        resp = await client.post(
            "/api/v1/flashcards/generate",
            json={"source": "book", "book_id": env.ids["book_id"], "chapter_number": 3,
                  "count": 5, "difficulty": difficulty},
        )
    assert resp.status_code == 201, resp.text
    user_msg = env.calls[0][-1]["content"]
    assert expected in user_msg


@pytest.mark.asyncio
async def test_generate_custom_prompt_reaches_model_and_stays_within_sources(env):
    async with _client() as client:
        resp = await client.post(
            "/api/v1/flashcards/generate",
            json={"source": "book", "book_id": env.ids["book_id"], "chapter_number": 3,
                  "count": 5, "custom_prompt": "فقط قوانین و فرمول‌های فصل را پوشش بده"},
        )
    assert resp.status_code == 201, resp.text
    user_msg = env.calls[0][-1]["content"]
    assert "تمرکز درخواستی کاربر" in user_msg
    assert "فقط قوانین و فرمول‌های فصل را پوشش بده" in user_msg
    # Still source-grounded: no external knowledge is allowed in the prompt.
    assert "دانش بیرونی" in user_msg


@pytest.mark.asyncio
async def test_generate_custom_prompt_over_limit_rejected_without_model_call(env):
    async with _client() as client:
        resp = await client.post(
            "/api/v1/flashcards/generate",
            json={"source": "book", "book_id": env.ids["book_id"], "chapter_number": 3,
                  "count": 5, "custom_prompt": "x" * 1001},
        )
    assert resp.status_code == 422
    assert env.calls == []


@pytest.mark.asyncio
async def test_generate_custom_prompt_at_limit_accepted(env):
    async with _client() as client:
        resp = await client.post(
            "/api/v1/flashcards/generate",
            json={"source": "book", "book_id": env.ids["book_id"], "chapter_number": 3,
                  "count": 5, "custom_prompt": "x" * 1000},
        )
    assert resp.status_code == 201
    assert "x" * 100 in env.calls[0][-1]["content"]


@pytest.mark.asyncio
async def test_generate_count_cap_and_requested_count(env):
    async with _client() as client:
        too_many = await client.post(
            "/api/v1/flashcards/generate",
            json={"source": "book", "book_id": env.ids["book_id"], "chapter_number": 3, "count": 11},
        )
        assert too_many.status_code == 422
        none = await client.post(
            "/api/v1/flashcards/generate",
            json={"source": "book", "book_id": env.ids["book_id"], "chapter_number": 3, "count": 0},
        )
        assert none.status_code == 422
        assert env.calls == []  # nothing reached the model

        resp = await client.post(
            "/api/v1/flashcards/generate",
            json={"source": "book", "book_id": env.ids["book_id"], "chapter_number": 3, "count": 10},
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["requested_count"] == 10
    assert body["created_count"] <= 10  # fake model yields 2 valid cards
    assert "دقیقاً 10 کارت" in env.calls[0][-1]["content"]


@pytest.mark.asyncio
async def test_generate_without_valid_source_makes_no_model_call(env):
    async with _client() as client:
        resp = await client.post(
            "/api/v1/flashcards/generate",
            json={"source": "book", "book_id": env.ids["book_id"], "chapter_number": 99, "count": 5},
        )
    assert resp.status_code == 422
    assert env.calls == []


@pytest.mark.asyncio
async def test_generate_difficulty_keeps_server_citations(env):
    async with _client() as client:
        resp = await client.post(
            "/api/v1/flashcards/generate",
            json={"source": "book", "book_id": env.ids["book_id"], "chapter_number": 3,
                  "count": 3, "difficulty": "hard", "custom_prompt": "مقایسهٔ مفاهیم"},
        )
    assert resp.status_code == 201
    for card in resp.json()["cards"]:
        assert card["citations"]
        assert all("ریاضی دهم" in c["citation"] for c in card["citations"])


# ---------------------------------------------------------------------------
# Explain («توضیح بیشتر»)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_explain_returns_grounded_text_with_citation_and_audit(env):
    deck_id, card_ids = await _make_deck_with_cards(env, 1, with_citations=True)
    async with env.factory() as session:
        before = await session.scalar(select(func.count(AiAuditLog.id)))
    async with _client() as client:
        resp = await client.post(f"/api/v1/flashcards/cards/{card_ids[0]}/explain")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "ضرب عدد در خودش" in body["explanation"]
    assert body["source_available"] is True
    assert body["citation"] and "ریاضی دهم" in body["citation"]
    async with env.factory() as session:
        after = await session.scalar(select(func.count(AiAuditLog.id)))
    assert after == before + 1
    # The textbook pages were actually passed to the model.
    explain_msg = env.text_calls[0][-1]["content"]
    assert "متن صفحهٔ 10" in explain_msg


@pytest.mark.asyncio
async def test_explain_without_recoverable_source_uses_card_only_and_no_invented_citation(env):
    async with env.factory() as session:
        deck = FlashcardDeck(user_id=env.ids["student_id"], title="کارت بدون منبع", source_type="manual")
        session.add(deck)
        await session.flush()
        card = await flashcard_service.add_manual_card(
            session, deck,
            front_md="سؤال کارت", back_md="پاسخ ذخیره‌شده",
            citations=[{"book_id": 999, "pdf_page_index": 77, "printed_page_number": 5,
                        "citation": "ارجاع غیرقابل بازیابی"}],
        )
        await session.commit()
        card_id = card.id
    async with _client() as client:
        resp = await client.post(f"/api/v1/flashcards/cards/{card_id}/explain")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source_available"] is False
    assert body["citations"] == []
    assert body["citation"] is None
    # The prompt must explicitly forbid inventing citations in the fallback path.
    assert "استناد جدیدی ادعا نکن" in env.text_calls[0][-1]["content"]
    assert "پاسخ ذخیره‌شده" in env.text_calls[0][-1]["content"]


@pytest.mark.asyncio
async def test_explain_requires_ownership(env):
    deck_id, card_ids = await _make_deck_with_cards(env, 1)
    async with env.factory() as session:
        owner = await session.get(User, env.ids["student_id"])
        other = await session.get(User, env.ids["other_id"])
    original = app.dependency_overrides[require_student]

    async def other_student():
        return other

    app.dependency_overrides[require_student] = other_student
    try:
        async with _client() as client:
            resp = await client.post(f"/api/v1/flashcards/cards/{card_ids[0]}/explain")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides[require_student] = original


# ---------------------------------------------------------------------------
# Study sessions: create / restore / shuffle / restart / complete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_create_patch_and_restore(env):
    deck_id, card_ids = await _make_deck_with_cards(env, 3)
    async with _client() as client:
        created = await _start_session(client, deck_id, "full")
        assert created["status"] == "in_progress"
        assert created["position"] == 0
        assert created["total"] == 3
        assert created["card_ids"] == card_ids

        patch = await client.patch(
            f"/api/v1/flashcards/sessions/{created['id']}",
            json={"position": 1, "flipped": True},
        )
        assert patch.status_code == 200
        assert patch.json()["position"] == 1
        assert patch.json()["flipped"] is True

        # Simulate a browser reload: all state comes from the backend.
        restored = await client.get(f"/api/v1/flashcards/sessions/{created['id']}")
        assert restored.status_code == 200
        body = restored.json()
        assert body["position"] == 1
        assert body["flipped"] is True
        assert [c["id"] for c in body["cards"]] == card_ids

        active = await client.get("/api/v1/flashcards/sessions/active")
        assert active.status_code == 200
        assert any(row["id"] == created["id"] for row in active.json())

        bad_position = await client.patch(
            f"/api/v1/flashcards/sessions/{created['id']}", json={"position": 99}
        )
        assert bad_position.status_code == 422


@pytest.mark.asyncio
async def test_session_isolation_between_users(env):
    deck_id, card_ids = await _make_deck_with_cards(env, 2)
    async with _client() as client:
        created = await _start_session(client, deck_id, "full")

    original = app.dependency_overrides[require_student]

    async def other_student():
        async with env.factory() as session:
            return await session.get(User, env.ids["other_id"])

    app.dependency_overrides[require_student] = other_student
    try:
        async with _client() as client:
            session_id = created["id"]
            assert (await client.get(f"/api/v1/flashcards/sessions/{session_id}")).status_code == 404
            assert (await client.patch(
                f"/api/v1/flashcards/sessions/{session_id}", json={"position": 0})).status_code == 404
            assert (await client.post(f"/api/v1/flashcards/sessions/{session_id}/shuffle")).status_code == 404
            assert (await client.post(f"/api/v1/flashcards/sessions/{session_id}/restart",
                                      json={})).status_code == 404
            assert (await client.post(
                f"/api/v1/flashcards/sessions/{session_id}/complete")).status_code == 404
            # Cannot start a session on another user's deck either.
            other_start = await client.post(
                "/api/v1/flashcards/sessions", json={"deck_id": deck_id, "mode": "full"})
            assert other_start.status_code == 404
    finally:
        app.dependency_overrides[require_student] = original


@pytest.mark.asyncio
async def test_smart_session_contains_only_due_cards_full_contains_all(env):
    deck_id, card_ids = await _make_deck_with_cards(env, 2)
    async with _client() as client:
        # Rate card 0 three days' worth of success so it is not due anymore.
        first = await client.post(f"/api/v1/flashcards/{card_ids[0]}/review", json={"rating": 4})
        assert first.status_code == 200

        smart = await _start_session(client, deck_id, "smart")
        assert smart["card_ids"] == [card_ids[1]]
        full = await _start_session(client, deck_id, "full")
        assert full["card_ids"] == card_ids


@pytest.mark.asyncio
async def test_rate_got_and_missed_and_duplicate_replay_prevention(env):
    deck_id, card_ids = await _make_deck_with_cards(env, 2)
    async with _client() as client:
        created = await _start_session(client, deck_id, "full")
        session_id = created["id"]
        got = await client.post(
            f"/api/v1/flashcards/{card_ids[0]}/review",
            json={"rating": 3, "session_id": session_id},
        )
        assert got.status_code == 200
        assert got.json()["applied"] is True
        assert got.json()["session"]["results"][str(card_ids[0])] == "got"
        # Replay: same card + session must not double-count.
        replay = await client.post(
            f"/api/v1/flashcards/{card_ids[0]}/review",
            json={"rating": 3, "session_id": session_id},
        )
        assert replay.status_code == 200
        assert replay.json()["applied"] is False
        missed = await client.post(
            f"/api/v1/flashcards/{card_ids[1]}/review",
            json={"rating": 1, "session_id": session_id},
        )
        assert missed.json()["session"]["results"][str(card_ids[1])] == "missed"

    async with env.factory() as session:
        review = await session.scalar(
            select(FlashcardReview).where(FlashcardReview.card_id == card_ids[0])
        )
        assert review.review_count == 1
        review2 = await session.scalar(
            select(FlashcardReview).where(FlashcardReview.card_id == card_ids[1])
        )
        assert review2.review_count == 1


@pytest.mark.asyncio
async def test_session_auto_completes_and_missed_subset_and_restart(env):
    deck_id, card_ids = await _make_deck_with_cards(env, 3)
    async with _client() as client:
        created = await _start_session(client, deck_id, "full")
        session_id = created["id"]
        await client.post(f"/api/v1/flashcards/{card_ids[0]}/review",
                          json={"rating": 3, "session_id": session_id})
        await client.post(f"/api/v1/flashcards/{card_ids[1]}/review",
                          json={"rating": 1, "session_id": session_id})
        last = await client.post(f"/api/v1/flashcards/{card_ids[2]}/review",
                                 json={"rating": 3, "session_id": session_id})
        assert last.json()["session"]["status"] == "completed"
        assert last.json()["session"]["got_count"] == 2
        assert last.json()["session"]["missed_count"] == 1
        assert last.json()["session"]["success_percent"] == pytest.approx(66.666, abs=0.1)

        # Only-missed subset for the same session.
        missed_only = await client.post(
            "/api/v1/flashcards/sessions",
            json={"deck_id": deck_id, "mode": "full", "card_ids": [card_ids[1]]},
        )
        assert missed_only.status_code == 201
        assert missed_only.json()["card_ids"] == [card_ids[1]]
        assert missed_only.json()["total"] == 1

        # Duplicated subset is rejected.
        dup = await client.post(
            "/api/v1/flashcards/sessions",
            json={"deck_id": deck_id, "mode": "full", "card_ids": [card_ids[1], card_ids[1]]},
        )
        assert dup.status_code == 422

        # Restart the completed session: progress resets, SM-2 rows stay.
        restart = await client.post(f"/api/v1/flashcards/sessions/{session_id}/restart", json={})
        assert restart.status_code == 200
        body = restart.json()
        assert body["status"] == "in_progress"
        assert body["results"] == {}
        assert body["position"] == 0

    async with env.factory() as session:
        total_reviews = await session.scalar(select(func.count(FlashcardReview.id)))
        assert total_reviews == 3  # SM-2 history preserved
        row = await session.scalar(
            select(FlashcardStudySession).where(FlashcardStudySession.id == session_id)
        )
        assert row.status == "in_progress"


@pytest.mark.asyncio
async def test_only_missed_rejects_cards_of_another_user(env):
    deck_id, card_ids = await _make_deck_with_cards(env, 1)
    async with env.factory() as session:
        other_deck = FlashcardDeck(user_id=env.ids["other_id"], title="خصوصی", source_type="manual")
        session.add(other_deck)
        await session.flush()
        foreign = await flashcard_service.add_manual_card(session, other_deck, front_md="x", back_md="y")
        await session.commit()
        foreign_id = foreign.id
    async with _client() as client:
        resp = await client.post(
            "/api/v1/flashcards/sessions",
            json={"deck_id": None, "mode": "full", "card_ids": [foreign_id]},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_shuffle_keeps_all_cards_and_current_position_owner(env):
    deck_id, card_ids = await _make_deck_with_cards(env, 5)
    async with _client() as client:
        created = await _start_session(client, deck_id, "full")
        session_id = created["id"]
        await client.patch(f"/api/v1/flashcards/sessions/{session_id}",
                           json={"position": 2, "flipped": True})
        shuffled = await client.post(f"/api/v1/flashcards/sessions/{session_id}/shuffle")
        assert shuffled.status_code == 200
        body = shuffled.json()
        assert sorted(body["card_ids"]) == sorted(card_ids)  # none lost, none duplicated
        assert body["cards"][body["position"]]["id"] == card_ids[2]  # current card preserved


@pytest.mark.asyncio
async def test_delete_card_cleans_session_results_and_order(env):
    deck_id, card_ids = await _make_deck_with_cards(env, 3)
    async with _client() as client:
        created = await _start_session(client, deck_id, "full")
        session_id = created["id"]
        await client.post(f"/api/v1/flashcards/{card_ids[0]}/review",
                          json={"rating": 3, "session_id": session_id})
        await client.patch(f"/api/v1/flashcards/sessions/{session_id}", json={"position": 1})

        deleted = await client.delete(f"/api/v1/flashcards/cards/{card_ids[1]}")
        assert deleted.status_code == 204

        restored = await client.get(f"/api/v1/flashcards/sessions/{session_id}")
        body = restored.json()
        assert card_ids[1] not in body["card_ids"]
        assert str(card_ids[1]) not in body["results"]
        assert body["total"] == 2
        assert body["results"][str(card_ids[0])] == "got"
        # Deck counts reflect the deletion.
        deck = await client.get(f"/api/v1/flashcards/decks/{deck_id}")
        assert deck.json()["stats"]["total"] == 2


@pytest.mark.asyncio
async def test_deck_delete_removes_deck_scoped_sessions(env):
    deck_id, card_ids = await _make_deck_with_cards(env, 2)
    async with _client() as client:
        created = await _start_session(client, deck_id, "full")
        session_id = created["id"]
        deleted = await client.delete(f"/api/v1/flashcards/decks/{deck_id}")
        assert deleted.status_code == 204
        assert (await client.get(f"/api/v1/flashcards/sessions/{session_id}")).status_code == 404


# ---------------------------------------------------------------------------
# CSV export (Anki APKG covered by Phase 3 suite)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_csv_export_utf8_bom_escaping_and_formula_injection(env):
    async with env.factory() as session:
        deck = FlashcardDeck(user_id=env.ids["student_id"], title="دستهٔ CSV", source_type="manual")
        session.add(deck)
        await session.flush()
        await flashcard_service.add_manual_card(
            session, deck,
            front_md='=SUM(1;2)',
            back_md='پاسخ "quoted", با ویرگول\nو خط جدید',
            hint_md="راهنما", tags=["آزمون"], citations=[],
        )
        await flashcard_service.add_manual_card(
            session, deck,
            front_md="+۱+۱",
            back_md="دو",
            hint_md="", tags=[],
            citations=[{"book_id": env.ids["book_id"], "pdf_page_index": 1,
                        "printed_page_number": 10, "citation": "ریاضی دهم، صفحهٔ ۱۰"}],
        )
        await session.commit()
        deck_id = deck.id
    async with _client() as client:
        resp = await client.get(f"/api/v1/flashcards/decks/{deck_id}/export/csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    content = resp.content
    assert content.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM for Excel
    text = content.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert list(rows[0].keys()) == ["Front", "Back", "Hint", "Tags", "Citations"]
    fronts = [row["Front"] for row in rows]
    assert fronts[0].startswith("'=")  # formula injection neutralized
    assert fronts[1].startswith("'+")
    assert rows[0]["Back"] == 'پاسخ "quoted", با ویرگول\nو خط جدید'
    assert rows[0]["Tags"] == "آزمون"
    assert rows[1]["Citations"] == "ریاضی دهم، صفحهٔ ۱۰"
    assert "filename" in resp.headers["content-disposition"]


@pytest.mark.asyncio
async def test_csv_export_empty_deck_rejected_and_apkg_route_untouched(env):
    async with _client() as client:
        created = await client.post("/api/v1/flashcards/decks", json={"title": "خالی"})
        deck_id = created.json()["id"]
        assert (await client.get(f"/api/v1/flashcards/decks/{deck_id}/export/csv")).status_code == 422
        assert (await client.get(f"/api/v1/flashcards/decks/{deck_id}/export/anki")).status_code == 422


# ---------------------------------------------------------------------------
# Feature flag: everything new is also closed when flashcards are disabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_endpoints_closed_when_capability_disabled(env):
    deck_id, card_ids = await _make_deck_with_cards(env, 1, with_citations=True)
    async with _client() as client:
        off = await client.put("/api/v1/admin/capabilities/flashcards", headers=ADMIN_HEADERS,
                               json={"is_enabled": False})
        assert off.status_code == 200
        try:
            assert (await client.post("/api/v1/flashcards/sessions",
                                      json={"deck_id": deck_id, "mode": "full"})).status_code == 403
            assert (await client.get("/api/v1/flashcards/sessions/active")).status_code == 403
            assert (await client.post(f"/api/v1/flashcards/cards/{card_ids[0]}/explain")).status_code == 403
            assert (await client.get(f"/api/v1/flashcards/decks/{deck_id}/export/csv")).status_code == 403
            assert env.text_calls == []  # no model call while the flag is off
        finally:
            on = await client.put("/api/v1/admin/capabilities/flashcards", headers=ADMIN_HEADERS,
                                  json={"is_enabled": True})
            assert on.status_code == 200


@pytest.mark.asyncio
async def test_admin_flashcards_stats_still_available(env):
    async with _client() as client:
        resp = await client.get("/api/v1/admin/flashcards/stats", headers=ADMIN_HEADERS)
    assert resp.status_code == 200
    assert {"decks", "cards", "reviews"} <= set(resp.json())


@pytest.mark.asyncio
async def test_explain_model_failure_returns_502_and_still_audits(env, monkeypatch):
    deck_id, card_ids = await _make_deck_with_cards(env, 1, with_citations=True)

    async def boom(model, messages):
        raise RuntimeError("provider down")

    monkeypatch.setattr(ai_gateway, "complete_text", boom)
    async with env.factory() as session:
        before = await session.scalar(select(func.count(AiAuditLog.id)))
    async with _client() as client:
        resp = await client.post(f"/api/v1/flashcards/cards/{card_ids[0]}/explain")
    assert resp.status_code == 502
    assert "توضیح با خطا" in resp.json()["detail"]
    # The error is still recorded in the audit trail (no silent failures).
    async with env.factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(AiAuditLog).where(AiAuditLog.status == "error").order_by(AiAuditLog.id.desc())
                )
            ).all()
        )
    assert rows, "error path must persist an audit row"


@pytest.mark.asyncio
async def test_generate_invalid_difficulty_rejected_without_model_call(env):
    async with _client() as client:
        resp = await client.post(
            "/api/v1/flashcards/generate",
            json={"source": "book", "book_id": env.ids["book_id"], "chapter_number": 3,
                  "count": 3, "difficulty": "extreme"},
        )
    assert resp.status_code == 422
    assert env.calls == []


@pytest.mark.asyncio
async def test_smart_session_with_nothing_due_returns_422(env):
    deck_id, card_ids = await _make_deck_with_cards(env, 1)
    async with _client() as client:
        reviewed = await client.post(f"/api/v1/flashcards/{card_ids[0]}/review", json={"rating": 4})
        assert reviewed.status_code == 200
        resp = await client.post(
            "/api/v1/flashcards/sessions", json={"deck_id": deck_id, "mode": "smart"}
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_full_session_all_decks_scope_excludes_other_users(env):
    own_deck, own_card_ids = await _make_deck_with_cards(env, 2)
    async with env.factory() as session:
        other_deck = FlashcardDeck(user_id=env.ids["other_id"], title="خصوصی", source_type="manual")
        session.add(other_deck)
        await session.flush()
        foreign = await flashcard_service.add_manual_card(session, other_deck, front_md="x", back_md="y")
        foreign_id = foreign.id
        await session.commit()
    async with _client() as client:
        created = await _start_session(client, None, "full")
    assert set(created["card_ids"]) == set(own_card_ids)
    assert foreign_id not in created["card_ids"]
