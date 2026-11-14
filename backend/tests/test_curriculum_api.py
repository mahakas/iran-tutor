"""Curriculum endpoints enforce grade/major selection rules."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.curriculum import list_books
from app.models.curriculum import BookStatus


class FakeSession:
    def __init__(self, grade, major=None, books=()):
        self.grade = grade
        self.major = major
        self.books = list(books)
        self.scalar_calls = 0

    async def scalar(self, statement):
        self.scalar_calls += 1
        return self.grade if self.scalar_calls == 1 else self.major

    async def scalars(self, statement):
        return SimpleNamespace(all=lambda: self.books)


@pytest.mark.asyncio
async def test_list_books_for_high_school_requires_and_scopes_major():
    grade = SimpleNamespace(id=12, number=12, has_major=True)
    major = SimpleNamespace(id=2, code="math_physics")
    book = SimpleNamespace(
        id=5,
        title="فیزیک ۳",
        status=BookStatus.ready,
    )
    session = FakeSession(grade, major, [book])

    response = await list_books(12, "math_physics", session)

    assert response == [
        {
            "id": 5,
            "title": "فیزیک ۳",
            "grade_number": 12,
            "major_code": "math_physics",
            "status": "ready",
        }
    ]


@pytest.mark.asyncio
async def test_list_books_rejects_high_school_without_major():
    grade = SimpleNamespace(id=12, number=12, has_major=True)
    session = FakeSession(grade)

    with pytest.raises(HTTPException) as error:
        await list_books(12, None, session)

    assert error.value.status_code == 422
    assert session.scalar_calls == 1
