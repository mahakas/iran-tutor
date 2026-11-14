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


def test_single_preview_handles_missing_image_gracefully(tmp_path):
    out = render_single_preview(
        1,
        "demo-vision",
        [
            {
                "pdf_page_index": 1,
                "image_path": str(tmp_path / "does_not_exist.png"),
                "markdown": "صفحه بدون تصویر",
                "status": "failed",
                "warnings": [],
                "visual_elements": [],
            }
        ],
        tmp_path / "preview.html",
    )
    html_text = out.read_text(encoding="utf-8")
    assert "تصویر صفحه موجود نیست" in html_text


@pytest.mark.asyncio
async def test_fix_page_clears_warnings_supports_null_and_serves_admin_lists(monkeypatch, tmp_path):
    from PIL import Image
    from app.api import admin as admin_api

    img_path = tmp_path / "page_0015.png"
    Image.new("RGB", (12, 12), "white").save(img_path)

    book_obj = SimpleNamespace(
        id=2,
        title="فیزیک ۳",
        grade_id=12,
        major_id=1,
        total_pdf_pages=1,
        status="ready",
    )
    page_obj = SimpleNamespace(
        book_id=2,
        pdf_page_index=15,
        printed_page_number=99,
        chapter_number=1,
        chapter_title="حرکت",
        markdown_content="متن قبلی",
        visual_elements=[],
        page_image_path=str(img_path),
        status="needs_review",
        error_message="خطای قدیمی",
        extraction_model="demo-vision",
        warnings=["DEMO_MODE: OCR واقعی اجرا نشده"],
        edited_by_human=False,
    )

    class FakeExecResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class FakeScalarsResult:
        def __init__(self, items):
            self._items = items

        def all(self):
            return self._items

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, model, key):
            if key == 2:
                return book_obj
            return None

        async def scalar(self, stmt):
            return page_obj

        async def scalars(self, stmt):
            return FakeScalarsResult([page_obj])

        async def execute(self, stmt):
            sql = str(stmt)
            if "COUNT" in sql.upper() or "count(" in sql.lower():
                return FakeExecResult([(2, page_obj.status, 1)])
            return FakeExecResult([(book_obj, 12, "math_physics")])

        async def commit(self):
            return None

    monkeypatch.setattr(admin_api, "async_session_factory", lambda: FakeSession())
    monkeypatch.setattr("app.services.ingestion_service.STORAGE_DIR", tmp_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        books_resp = await client.get("/api/v1/admin/books")
        assert books_resp.status_code == 200
        assert books_resp.json()[0]["id"] == 2
        assert books_resp.json()[0]["pages"] == {"needs_review": 1}

        pages_resp = await client.get("/api/v1/admin/books/2/pages")
        assert pages_resp.status_code == 200
        assert pages_resp.json()[0]["image_url"] == "/api/v1/admin/books/2/pages/15/image"

        img_resp = await client.get("/api/v1/admin/books/2/pages/15/image")
        assert img_resp.status_code == 200
        assert img_resp.headers["content-type"].startswith("image/png")

        fix_resp = await client.put(
            "/api/v1/admin/books/2/pages/15",
            json={
                "printed_page_number": None,
                "chapter_number": 1,
                "chapter_title": "حرکت بر خط راست",
                "markdown_content": "# مثال اصلاح‌شده",
            },
        )
        assert fix_resp.status_code == 200
        assert fix_resp.json()["status"] == "done"
        assert fix_resp.json()["edited_by_human"] is True

    assert page_obj.printed_page_number is None
    assert page_obj.chapter_title == "حرکت بر خط راست"
    assert page_obj.markdown_content == "# مثال اصلاح‌شده"
    assert page_obj.warnings == []
    assert page_obj.error_message is None
    assert (tmp_path / "books" / "2" / "book.md").is_file()
    assert (tmp_path / "books" / "2" / "book.json").is_file()


def test_unbalanced_dollars_warning_ignores_escaped_currency():
    from app.services.ingestion_service import _unbalanced_dollars_warning

    assert _unbalanced_dollars_warning(r"قیمت \$10 و فرمول $v = \frac{\Delta x}{\Delta t}$") is None
    assert _unbalanced_dollars_warning("فرمول ناقص $v = at") is not None
