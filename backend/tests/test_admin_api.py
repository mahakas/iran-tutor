"""Admin API validation tests (no LLM calls)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_preview_rejects_unknown_status():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/admin/books/1/preview?status=bogus")
    assert response.status_code == 422
    assert "invalid status filter" in response.json()["detail"]


@pytest.mark.asyncio
async def test_preview_rejects_inverted_page_range():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/admin/books/1/preview?page_from=5&page_to=2"
        )
    assert response.status_code == 422
    assert "invalid page range" in response.json()["detail"]


@pytest.mark.asyncio
async def test_preview_rejects_negative_page_index():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/admin/books/1/preview?page_from=0")
    assert response.status_code == 422
