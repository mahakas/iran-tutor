"""The PostgreSQL lexical query can be compiled without a running database."""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql

from app.services import retrieval_service


@pytest.mark.asyncio
async def test_postgres_search_query_is_scoped_and_uses_full_text_search(monkeypatch):
    class FakeResult:
        @staticmethod
        def all():
            return []

    class FakeSession:
        statement = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, statement):
            self.statement = statement
            return FakeResult()

    fake_session = FakeSession()
    monkeypatch.setattr(retrieval_service, "async_session_factory", lambda: fake_session)

    result = await retrieval_service._search_postgres(
        "شتاب",
        grade_number=12,
        major_code="math_physics",
        book_id=5,
        limit=20,
    )

    compiled = str(fake_session.statement.compile(dialect=postgresql.dialect()))
    assert result == []
    assert "to_tsvector" in compiled
    assert "plainto_tsquery" in compiled
    assert "book_pages.status" in compiled
    assert "books.id" in compiled
    assert "grades.number" in compiled
    assert "majors.code" in compiled
