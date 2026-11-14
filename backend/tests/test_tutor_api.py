"""Tutor endpoint enforces the selected book's grade and major."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import get_session
from app.main import app
from app.models.curriculum import Book, Grade, Major


class FakeSession:
    async def get(self, model, identity):
        if model is Book and identity == 1:
            return SimpleNamespace(id=1, grade_id=12, major_id=2)
        if model is Grade and identity == 12:
            return SimpleNamespace(number=12, has_major=True)
        if model is Major and identity == 2:
            return SimpleNamespace(code="math_physics")
        return None


@pytest.mark.asyncio
async def test_tutor_rejects_major_that_does_not_match_selected_book(monkeypatch):
    async def fake_session():
        yield FakeSession()

    async def should_not_answer(**kwargs):
        raise AssertionError("must reject before retrieval")

    app.dependency_overrides[get_session] = fake_session
    monkeypatch.setattr("app.api.tutor.answer_from_textbook", should_not_answer)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/tutor/ask",
                json={
                    "query": "سوال فیزیک",
                    "grade_number": 12,
                    "major_code": "experimental",
                    "book_id": 1,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "selected major" in response.json()["detail"]


@pytest.mark.asyncio
async def test_tutor_passes_server_verified_curriculum_to_rag(monkeypatch):
    async def fake_session():
        yield FakeSession()

    async def fake_answer(**kwargs):
        assert kwargs["grade_number"] == 12
        assert kwargs["major_code"] == "math_physics"
        assert kwargs["book_id"] == 1
        return {"answer": "پاسخ مستند", "sources": [], "retrieved_count": 0}

    app.dependency_overrides[get_session] = fake_session
    monkeypatch.setattr("app.api.tutor.answer_from_textbook", fake_answer)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/tutor/ask",
                json={
                    "query": "سوال فیزیک",
                    "grade_number": 12,
                    "major_code": "math_physics",
                    "book_id": 1,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["answer"] == "پاسخ مستند"
