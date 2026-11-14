"""Idempotent seeding of curriculum reference data."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.models.curriculum import Grade, Major

GRADE_TITLES: dict[int, str] = {
    1: "اول دبستان",
    2: "دوم دبستان",
    3: "سوم دبستان",
    4: "چهارم دبستان",
    5: "پنجم دبستان",
    6: "ششم دبستان",
    7: "هفتم (دوره اول متوسطه)",
    8: "هشتم (دوره اول متوسطه)",
    9: "نهم (دوره اول متوسطه)",
    10: "دهم (دوره دوم متوسطه)",
    11: "یازدهم (دوره دوم متوسطه)",
    12: "دوازدهم (دوره دوم متوسطه)",
}

MAJORS: list[tuple[str, str]] = [
    ("math_physics", "ریاضی‌فیزیک"),
    ("experimental", "علوم تجربی"),
    ("humanities", "علوم انسانی"),
]


async def seed_grades(session: AsyncSession) -> None:
    existing = set((await session.scalars(select(Grade.number))).all())
    for number in range(1, 13):
        if number not in existing:
            session.add(
                Grade(number=number, title=GRADE_TITLES[number], has_major=number >= 10)
            )


async def seed_majors(session: AsyncSession) -> None:
    existing = set((await session.scalars(select(Major.code))).all())
    for code, title in MAJORS:
        if code not in existing:
            session.add(Major(title=title, code=code))


async def seed_database() -> None:
    """Insert grades 1-12 and majors if absent. Safe to call repeatedly."""
    async with async_session_factory() as session:
        await seed_grades(session)
        await seed_majors(session)
        await session.commit()
