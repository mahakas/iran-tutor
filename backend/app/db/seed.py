"""Idempotent seeding of curriculum reference data."""

from __future__ import annotations

from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import BACKEND_DIR, get_settings
from app.db.base import Base
from app.db.session import async_session_factory, engine
from app.models.auth import BillingSettings, Plan
from app.models.curriculum import Book, BookPage, BookStatus, Grade, Major, PageStatus

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

DEFAULT_PLANS: list[dict[str, object]] = [
    {
        "code": "normal",
        "name": "اقتصادی",
        "description": "مناسب مرور روزانه درس‌ها و حل تمرین — ۵۰۰٬۰۰۰ تومان برای ۳۰ روز",
        "price_toman": 500_000,
        "token_quota": 500_000,
        "storage_quota_bytes": 100 * 1024 * 1024,
        "duration_days": 30,
        "sort_order": 1,
    },
    {
        "code": "pro",
        "name": "حرفه‌ای",
        "description": "سهمیهٔ توکن بیشتر برای پرسش تصویری، صوتی و آزمون — ۹۰۰٬۰۰۰ تومان برای ۳۰ روز",
        "price_toman": 900_000,
        "token_quota": 1_200_000,
        "storage_quota_bytes": 250 * 1024 * 1024,
        "duration_days": 30,
        "sort_order": 2,
    },
    {
        "code": "vip",
        "name": "هوشمندانه",
        "description": "بیشترین سهمیهٔ توکن برای آمادگی مستمر و کنکور — ۲٬۷۵۰٬۰۰۰ تومان برای ۹۰ روز",
        "price_toman": 2_750_000,
        "token_quota": 4_000_000,
        "storage_quota_bytes": 1024 * 1024 * 1024,
        "duration_days": 90,
        "sort_order": 3,
    },
]


async def seed_plans(session: AsyncSession) -> None:
    existing = set((await session.scalars(select(Plan.code))).all())
    for item in DEFAULT_PLANS:
        if item["code"] not in existing:
            session.add(
                Plan(
                    code=str(item["code"]),
                    name=str(item["name"]),
                    description=str(item["description"]),
                    price_toman=int(item["price_toman"]),  # type: ignore[arg-type]
                    token_quota=int(item["token_quota"]),  # type: ignore[arg-type]
                    storage_quota_bytes=int(item["storage_quota_bytes"]),  # type: ignore[arg-type]
                    duration_days=int(item["duration_days"]),  # type: ignore[arg-type]
                    sort_order=int(item["sort_order"]),  # type: ignore[arg-type]
                    is_active=True,
                )
            )


async def seed_billing_settings(session: AsyncSession) -> None:
    existing = await session.get(BillingSettings, 1)
    if existing is None:
        session.add(
            BillingSettings(
                id=1,
                token_price_per_1k_toman=1000,
                starter_tokens=15_000,
                starter_duration_days=7,
                starter_storage_bytes=25 * 1024 * 1024,
            )
        )


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


DEMO_BOOK_TITLE = "فیزیک ۳ — کتاب آزمایشی"
DEMO_PAGES = [
    {
        "printed_page_number": 8,
        "chapter_number": 1,
        "chapter_title": "حرکت بر خط راست",
        "markdown_content": (
            "# حرکت یکنواخت\n\nدر حرکت یکنواخت، سرعت ثابت است و مکان با زمان تغییر می‌کند. "
            "رابطهٔ سرعت متوسط برابر است با $v_{avg}=\\frac{\\Delta x}{\\Delta t}$.\n\n"
            "اگر جسم در هر بازهٔ زمانی مساوی، جابه‌جایی مساوی داشته باشد، حرکت یکنواخت است."
        ),
        "visual_elements": [],
    },
    {
        "printed_page_number": 9,
        "chapter_number": 1,
        "chapter_title": "حرکت بر خط راست",
        "markdown_content": (
            "# شتاب متوسط\n\nشتاب متوسط از تقسیم تغییرات سرعت بر بازهٔ زمانی به دست می‌آید: "
            "$a_{avg}=\\frac{\\Delta v}{\\Delta t}$.\n\n"
            "واحد شتاب در دستگاه SI، متر بر مجذور ثانیه است."
        ),
        "visual_elements": [],
    },
    {
        "printed_page_number": 10,
        "chapter_number": 1,
        "chapter_title": "حرکت بر خط راست",
        "markdown_content": (
            "# نمودار مکان ـ زمان\n\nشیب نمودار مکان ـ زمان، سرعت را نشان می‌دهد. "
            "شیب خط راست برابر نسبت تغییر مکان به تغییر زمان است.\n\n"
            "در نمودار مکان بر حسب زمان، محور افقی زمان و محور عمودی مکان را نشان می‌دهد."
        ),
        "visual_elements": [
            {"label": "نمودار مکان ـ زمان", "type": "graph", "scientific_description": "خط راست؛ شیب خط بیانگر سرعت است."}
        ],
    },
]


def _ensure_demo_assets() -> tuple[str, list[str]]:
    """Create clearly labelled synthetic PDF/page images; never real textbook content."""
    storage = BACKEND_DIR / "storage" / "demo"
    storage.mkdir(parents=True, exist_ok=True)
    pdf_path = storage / "sample_physics.pdf"
    page_paths: list[str] = []
    document = pymupdf.open()
    for index, page_data in enumerate(DEMO_PAGES, start=1):
        page = document.new_page(width=595, height=842)
        page.insert_text((48, 70), "Iran AI Tutor - DEMO SAMPLE", fontsize=16)
        page.insert_text((48, 110), f"Synthetic page {index} (not an official textbook)", fontsize=12)
        page.insert_text((48, 165), f"Sample lesson page {index}", fontsize=18)
        page.insert_text((48, 205), "Static demo asset; educational responses use the seeded database fixture.", fontsize=11)
        image_path = storage / f"sample_physics_page_{index}.png"
        image = Image.new("RGB", (595, 842), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((20, 20, 575, 822), outline="#4d9a84", width=3)
        draw.text((45, 60), "DEMO ONLY - synthetic sample, not textbook content", fill="#177e77")
        draw.text((45, 115), f"Sample page {index}: {page_data['chapter_title']}", fill="#33443c")
        image.save(image_path)
        page_paths.append(str(image_path))
    document.save(pdf_path)
    document.close()
    return str(pdf_path), page_paths


async def _seed_demo_book(session: AsyncSession, *, grade: Grade, major: Major) -> None:
    existing = await session.scalar(select(Book).where(Book.title == DEMO_BOOK_TITLE))
    if existing is not None:
        return
    pdf_path, image_paths = _ensure_demo_assets()
    book = Book(
        title=DEMO_BOOK_TITLE,
        grade_id=grade.id,
        major_id=major.id,
        pdf_file_path=pdf_path,
        total_pdf_pages=len(DEMO_PAGES),
        status=BookStatus.ready,
    )
    session.add(book)
    await session.flush()
    for index, page_data in enumerate(DEMO_PAGES, start=1):
        session.add(
            BookPage(
                book_id=book.id,
                pdf_page_index=index,
                printed_page_number=page_data["printed_page_number"],
                chapter_number=page_data["chapter_number"],
                chapter_title=page_data["chapter_title"],
                markdown_content=page_data["markdown_content"],
                visual_elements=page_data["visual_elements"],
                page_image_path=image_paths[index - 1],
                status=PageStatus.done,
                warnings=[],
                extraction_model="deterministic-demo-fixture",
            )
        )


async def _ensure_sqlite_demo_columns(connection) -> None:
    """Safely add newly introduced columns when upgrading an existing SQLite demo DB."""
    if connection.dialect.name != "sqlite":
        return
    billing_cols = {
        row[1]
        for row in (await connection.execute(text("PRAGMA table_info(billing_settings)"))).fetchall()
    }
    if billing_cols and "admin_preferences" not in billing_cols:
        await connection.execute(
            text("ALTER TABLE billing_settings ADD COLUMN admin_preferences JSON NOT NULL DEFAULT '{}'")
        )
    if billing_cols and "system_config" not in billing_cols:
        await connection.execute(
            text("ALTER TABLE billing_settings ADD COLUMN system_config JSON NOT NULL DEFAULT '{}'")
        )
    page_cols = {
        row[1]
        for row in (await connection.execute(text("PRAGMA table_info(book_pages)"))).fetchall()
    }
    if page_cols and "original_markdown_content" not in page_cols:
        await connection.execute(
            text("ALTER TABLE book_pages ADD COLUMN original_markdown_content TEXT")
        )
    # Phase 1 RBAC columns on `users` (existing demo SQLite files).
    user_cols = {
        row[1]
        for row in (await connection.execute(text("PRAGMA table_info(users)"))).fetchall()
    }
    if user_cols:
        if "grade_level" not in user_cols:
            await connection.execute(text("ALTER TABLE users ADD COLUMN grade_level INTEGER"))
        if "major" not in user_cols:
            await connection.execute(text("ALTER TABLE users ADD COLUMN major VARCHAR(64)"))
        if "plan_id" not in user_cols:
            await connection.execute(text("ALTER TABLE users ADD COLUMN plan_id INTEGER"))


async def seed_database() -> None:
    """Create demo schema when requested and seed curriculum reference data."""
    settings = get_settings()
    if settings.demo_mode:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await _ensure_sqlite_demo_columns(connection)
    async with async_session_factory() as session:
        await seed_grades(session)
        await seed_majors(session)
        await seed_plans(session)
        await seed_billing_settings(session)
        # Phase 2: capability registry + skills (idempotent, admin-safe).
        from app.services.capability_service import seed_capabilities
        from app.services.skill_seed import seed_skills

        await seed_capabilities(session)
        await seed_skills(session)
        await session.flush()
        if settings.demo_mode:
            grade = await session.scalar(select(Grade).where(Grade.number == 12))
            major = await session.scalar(select(Major).where(Major.code == "math_physics"))
            if grade is not None and major is not None:
                await _seed_demo_book(session, grade=grade, major=major)
        await session.commit()
