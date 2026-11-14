"""Admin API validation tests (no LLM calls)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.preview import render_single_preview


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


@pytest.mark.asyncio
async def test_upload_rejects_invalid_pdf_and_out_of_bounds_page_range(monkeypatch, tmp_path):
    class FakeResult:
        def __init__(self, value):
            self._value = value

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def scalar(self, stmt):
            sql = str(stmt)
            if "grades" in sql:
                return SimpleNamespace(id=12, number=12, has_major=True)
            if "majors" in sql:
                return SimpleNamespace(id=1, code="math_physics")
            return None

    from app.api import admin as admin_api

    monkeypatch.setattr(admin_api, "async_session_factory", lambda: FakeSession())
    monkeypatch.setattr(admin_api, "UPLOAD_DIR", tmp_path)

    doc = pymupdf.open()
    doc.new_page()
    pdf_bytes = doc.tobytes()
    doc.close()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        bad_pdf = await client.post(
            "/api/v1/admin/books/upload-and-ingest",
            data={
                "grade_number": "12",
                "major_code": "math_physics",
                "book_title": "کتاب آزمایشی",
                "start_page": "1",
                "end_page": "1",
            },
            files={"pdf_file": ("not_a_pdf.pdf", b"not-valid-pdf-bytes", "application/pdf")},
        )
        assert bad_pdf.status_code == 422
        assert "not a valid PDF" in bad_pdf.json()["detail"]

        too_many_pages = await client.post(
            "/api/v1/admin/books/upload-and-ingest",
            data={
                "grade_number": "12",
                "major_code": "math_physics",
                "book_title": "کتاب آزمایشی",
                "start_page": "1",
                "end_page": "3",
            },
            files={"pdf_file": ("one_page.pdf", pdf_bytes, "application/pdf")},
        )
        assert too_many_pages.status_code == 422
        assert "only 1 pages" in too_many_pages.json()["detail"]


def test_single_preview_renders_each_page_without_single_queryselector_collision(tmp_path):
    from PIL import Image

    img1 = tmp_path / "p1.png"
    img2 = tmp_path / "p2.png"
    Image.new("RGB", (20, 20), "white").save(img1)
    Image.new("RGB", (20, 20), "white").save(img2)

    out = render_single_preview(
        1,
        "demo-vision",
        [
            {"pdf_page_index": 1, "image_path": str(img1), "markdown": "صفحه اول", "status": "done", "warnings": [], "visual_elements": []},
            {"pdf_page_index": 2, "image_path": str(img2), "markdown": "صفحه دوم", "status": "done", "warnings": [], "visual_elements": []},
        ],
        tmp_path / "preview.html",
    )
    html_text = out.read_text(encoding="utf-8")
    assert html_text.count('class="md-body"') == 2
    assert "t.nextElementSibling" in html_text
    assert "document.querySelector('.md-body[data-model=" not in html_text

