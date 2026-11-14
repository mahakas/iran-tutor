"""Qdrant-backed textbook indexing and strictly scoped page retrieval."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import AsyncQdrantClient, models
from sqlalchemy import select

from app.core.config import get_settings
from app.core.llm_client import embed_texts
from app.db.session import async_session_factory
from app.models.curriculum import Book, BookPage, Grade, Major, PageStatus

logger = logging.getLogger(__name__)

_qdrant: AsyncQdrantClient | None = None


def page_embedding_text(markdown: str, visual_elements: Sequence[dict[str, Any]] | None) -> str:
    """Combine page text and figure descriptions into the searchable document."""
    parts = [markdown.strip()] if markdown and markdown.strip() else []
    for element in visual_elements or []:
        label = str(element.get("label") or "شکل")
        kind = str(element.get("type") or "")
        description = str(element.get("scientific_description") or "")
        visual = " — ".join(part for part in (label, kind, description) if part)
        if visual:
            parts.append(f"توضیح شکل: {visual}")
    return "\n\n".join(parts)


def make_textbook_filter(
    *, grade_number: int, major_code: str | None, book_id: int | None = None
) -> models.Filter:
    """Build mandatory curriculum filters (grades 1-9 use the `general` key)."""
    conditions = [
        models.FieldCondition(key="grade_number", match=models.MatchValue(value=grade_number)),
        models.FieldCondition(
            key="major_code", match=models.MatchValue(value=major_code or "general")
        ),
    ]
    if book_id is not None:
        conditions.append(models.FieldCondition(key="book_id", match=models.MatchValue(value=book_id)))
    return models.Filter(must=conditions)


def _point_id(book_id: int, pdf_page_index: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"iran-ai-tutor:book:{book_id}:pdf-page:{pdf_page_index}"))


def _get_qdrant() -> AsyncQdrantClient:
    global _qdrant
    if _qdrant is None:
        _qdrant = AsyncQdrantClient(url=get_settings().qdrant_url, timeout=20)
    return _qdrant


async def close_qdrant() -> None:
    """Close the process-wide Qdrant connection on application shutdown."""
    global _qdrant
    if _qdrant is not None:
        await _qdrant.close()
        _qdrant = None


async def ensure_collection() -> None:
    settings = get_settings()
    client = _get_qdrant()
    if not await client.collection_exists(settings.qdrant_collection):
        await client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=models.VectorParams(
                size=settings.embedding_dimension,
                distance=models.Distance.COSINE,
            ),
        )
    # Exact metadata filters are used for every search; index those payload keys.
    for field_name, field_schema in (
        ("grade_number", models.PayloadSchemaType.INTEGER),
        ("major_code", models.PayloadSchemaType.KEYWORD),
        ("book_id", models.PayloadSchemaType.INTEGER),
    ):
        await client.create_payload_index(
            collection_name=settings.qdrant_collection,
            field_name=field_name,
            field_schema=field_schema,
            wait=True,
        )


async def index_book(book_id: int, batch_size: int = 32) -> dict[str, int]:
    """Index only accepted (`done`) pages for one curriculum book in Qdrant."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    async with async_session_factory() as session:
        book = await session.get(Book, book_id)
        if book is None:
            raise ValueError(f"book {book_id} does not exist")
        grade = await session.get(Grade, book.grade_id)
        if grade is None:
            raise ValueError(f"book {book_id} has no valid grade")
        major = await session.get(Major, book.major_id) if book.major_id is not None else None
        pages = list(
            (
                await session.scalars(
                    select(BookPage)
                    .where(BookPage.book_id == book_id, BookPage.status == PageStatus.done)
                    .order_by(BookPage.pdf_page_index)
                )
            ).all()
        )
        documents: list[tuple[BookPage, str]] = []
        for page in pages:
            text = page_embedding_text(page.markdown_content, page.visual_elements)
            if text:
                documents.append((page, text))

        payload_base = {
            "book_id": book.id,
            "book_title": book.title,
            "grade_number": grade.number,
            "major_code": major.code if major else "general",
        }
        points: list[models.PointStruct] = []
        for start in range(0, len(documents), batch_size):
            batch = documents[start : start + batch_size]
            vectors = await embed_texts([text for _, text in batch])
            for (page, text), vector in zip(batch, vectors, strict=True):
                points.append(
                    models.PointStruct(
                        id=_point_id(book_id, page.pdf_page_index),
                        vector=vector,
                        payload={
                            **payload_base,
                            "pdf_page_index": page.pdf_page_index,
                            "printed_page_number": page.printed_page_number,
                            "chapter_number": page.chapter_number,
                            "chapter_title": page.chapter_title,
                            "full_text": text,
                            "markdown_content": page.markdown_content,
                            "visual_elements": page.visual_elements or [],
                        },
                    )
                )

    if not points:
        return {"book_id": book_id, "indexed_pages": 0, "skipped_empty_pages": len(pages)}

    await ensure_collection()
    await _get_qdrant().upsert(
        collection_name=get_settings().qdrant_collection,
        points=points,
        wait=True,
    )
    logger.info("indexed %s pages for book %s", len(points), book_id)
    return {
        "book_id": book_id,
        "indexed_pages": len(points),
        "skipped_empty_pages": len(pages) - len(documents),
    }


async def search_textbook(
    query: str,
    *,
    grade_number: int,
    major_code: str | None,
    book_id: int,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Search only within the exact selected grade, major, and book."""
    if not query.strip():
        raise ValueError("query must not be empty")
    if top_k < 1 or top_k > 20:
        raise ValueError("top_k must be between 1 and 20")

    vector = (await embed_texts([query]))[0]
    settings = get_settings()
    response = await _get_qdrant().query_points(
        collection_name=settings.qdrant_collection,
        query=vector,
        query_filter=make_textbook_filter(
            grade_number=grade_number, major_code=major_code, book_id=book_id
        ),
        limit=top_k,
        with_payload=True,
        score_threshold=0.15,
    )
    results: list[dict[str, Any]] = []
    for point in response.points:
        payload = point.payload or {}
        results.append({**payload, "score": float(point.score)})
    return results
