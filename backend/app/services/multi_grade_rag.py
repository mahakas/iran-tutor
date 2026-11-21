"""Multi-grade, multi-book textbook retrieval with concept-link expansion (Phase 4).

Flow:
1. `build_scopes` turns the student's grade filter (10/11/12) and optional
   book list into exact (book, grade, major) scopes. Only `ready` books are used.
2. `search_multi_grade` runs hybrid search over all scopes at once.
3. `expand_with_concept_links` follows admin-curated `concept_links` from the
   top hits to chapters of linked books, restricted to the selected grades.
   Expansion hits are tagged `via_concept_link` so the UI and audit log can show
   why a cross-grade citation appeared.
4. `lookup_pages` resolves chapter/printed-page references to real pages.

No outside knowledge is introduced here: every returned item is a stored
`book_pages` row with its printed page and chapter metadata.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.concepts import ConceptLink
from app.models.curriculum import Book, BookPage, BookStatus, Grade, Major, PageStatus
from app.services.retrieval_service import TextbookScope, search_textbook_scopes

MAX_GRADES = 3
MAX_BOOKS = 12


class ScopeError(ValueError):
    """Raised when a requested grade/book combination is invalid."""


async def build_scopes(
    session: AsyncSession,
    *,
    grade_numbers: Sequence[int],
    book_ids: Sequence[int] | None = None,
) -> list[TextbookScope]:
    """Resolve the allowed (book, grade, major) slices for a multi-grade request."""
    grades = sorted({int(g) for g in grade_numbers})
    if not grades:
        raise ScopeError("at least one grade is required")
    if any(g not in (10, 11, 12) for g in grades):
        raise ScopeError("grade_numbers must be within 10, 11, 12")
    if len(grades) > MAX_GRADES:
        raise ScopeError("too many grades")

    statement = (
        select(Book, Grade.number, Major.code)
        .join(Grade, Book.grade_id == Grade.id)
        .outerjoin(Major, Book.major_id == Major.id)
        .where(Grade.number.in_(grades), Book.status == BookStatus.ready)
        .order_by(Grade.number.asc(), Book.id.asc())
    )
    if book_ids:
        ids = sorted({int(b) for b in book_ids})
        if len(ids) > MAX_BOOKS:
            raise ScopeError("too many books")
        statement = statement.where(Book.id.in_(ids))
    rows = (await session.execute(statement)).all()

    if book_ids:
        found = {book.id for book, _, _ in rows}
        missing = sorted(set(book_ids) - found)
        if missing:
            raise ScopeError(f"books not available for the selected grades: {missing}")

    return [
        TextbookScope(book_id=book.id, grade_number=grade, major_code=major or "general")
        for book, grade, major in rows
    ]


async def search_multi_grade(
    session: AsyncSession,
    query: str,
    *,
    grade_numbers: Sequence[int],
    book_ids: Sequence[int] | None = None,
    top_k: int = 6,
    expand_links: bool = True,
) -> dict[str, Any]:
    """Hybrid search across grades plus optional concept-link expansion.

    Returns {"results": [...], "scopes": [...], "expanded": int}.
    """
    scopes = await build_scopes(session, grade_numbers=grade_numbers, book_ids=book_ids)
    if not scopes:
        return {"results": [], "scopes": [], "expanded": 0}

    primary = await search_textbook_scopes(query, scopes=scopes, top_k=top_k)
    for item in primary:
        item["via_concept_link"] = False

    expanded: list[dict[str, Any]] = []
    if expand_links and primary:
        seeds = [(r["book_id"], r["chapter_number"]) for r in primary if r.get("chapter_number")]
        link_scopes = await expand_with_concept_links(
            session, seeds=seeds, allowed_grades=grade_numbers
        )
        if link_scopes:
            expanded = await search_textbook_scopes(query, scopes=link_scopes, top_k=max(2, top_k // 2))
            for item in expanded:
                item["via_concept_link"] = True

    merged = _dedupe_pages(primary + expanded)
    return {"results": merged[: top_k + 2], "scopes": scopes, "expanded": len(expanded)}


async def expand_with_concept_links(
    session: AsyncSession,
    *,
    seeds: Iterable[tuple[int, int]],
    allowed_grades: Sequence[int],
) -> list[TextbookScope]:
    """Chapter-level scopes for books linked to the seed chapters.

    Links are followed in both directions. Targets outside `allowed_grades` are
    dropped so an explicit grade filter is never silently widened.
    """
    seed_set = {(int(b), int(c)) for b, c in seeds}
    if not seed_set:
        return []
    book_ids = {b for b, _ in seed_set}
    rows = (
        await session.execute(
            select(ConceptLink).where(
                or_(
                    ConceptLink.source_book_id.in_(book_ids),
                    ConceptLink.target_book_id.in_(book_ids),
                )
            )
        )
    ).scalars().all()

    targets: dict[int, set[int]] = defaultdict(set)
    for link in rows:
        if (link.source_book_id, link.source_chapter) in seed_set:
            targets[link.target_book_id].add(link.target_chapter)
        if (link.target_book_id, link.target_chapter) in seed_set:
            targets[link.source_book_id].add(link.source_chapter)
    if not targets:
        return []

    allowed = set(int(g) for g in allowed_grades)
    book_rows = (
        await session.execute(
            select(Book.id, Grade.number, Major.code)
            .join(Grade, Book.grade_id == Grade.id)
            .outerjoin(Major, Book.major_id == Major.id)
            .where(Book.id.in_(list(targets)), Book.status == BookStatus.ready)
        )
    ).all()
    scopes: list[TextbookScope] = []
    for book_id, grade, major in book_rows:
        if grade not in allowed:
            continue
        scopes.append(
            TextbookScope(
                book_id=book_id,
                grade_number=grade,
                major_code=major or "general",
                chapter_numbers=frozenset(targets[book_id]),
            )
        )
    return scopes


async def lookup_pages(
    session: AsyncSession,
    *,
    book_id: int,
    chapter_number: int | None = None,
    printed_page_number: int | None = None,
    limit: int = 20,
) -> list[BookPage]:
    """Find approved pages by chapter or printed page number (for explicit citations)."""
    if chapter_number is None and printed_page_number is None:
        raise ScopeError("chapter_number or printed_page_number is required")
    conditions = [BookPage.book_id == book_id, BookPage.status == PageStatus.done]
    if chapter_number is not None:
        conditions.append(BookPage.chapter_number == chapter_number)
    if printed_page_number is not None:
        conditions.append(BookPage.printed_page_number == printed_page_number)
    rows = (
        await session.execute(
            select(BookPage).where(*conditions).order_by(BookPage.pdf_page_index.asc()).limit(limit)
        )
    ).scalars().all()
    return list(rows)


def _dedupe_pages(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the best-scoring hit per (book, page); preserve order by score."""
    best: dict[tuple[int, int], dict[str, Any]] = {}
    for item in items:
        key = (item["book_id"], item["pdf_page_index"])
        current = best.get(key)
        if current is None or item.get("score", 0) > current.get("score", 0):
            best[key] = item
    return sorted(best.values(), key=lambda it: it.get("score", 0), reverse=True)
