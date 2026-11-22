"""Regression tests for curriculum-scoped mastery and evidence validation."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.auth import User  # noqa: F401 - register referenced auth tables
from app.models.curriculum import (
    AcademicYear,
    Book,
    BookCurriculumLink,
    BookPage,
    BookStatus,
    CurriculumUnit,
    EducationBranch,
    FieldOfStudy,
    Grade,
    LearningEvidence,
    LearningObjective,
    ObjectivePrerequisite,
    PageStatus,
    Subject,
)
from app.models.phase5 import MasteryBookSettings, MasteryChapterProgress  # noqa: F401
from app.services import mastery_service


@pytest.fixture
async def curriculum_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _create_curriculum(session: AsyncSession):
    grade = Grade(number=10, title="دهم", has_major=True)
    branch = EducationBranch(
        code="theoretical",
        title="نظری",
        min_grade=10,
        max_grade=12,
        is_active=True,
    )
    year = AcademicYear(code="1405", title="۱۴۰۵–۱۴۰۶", is_active=True)
    subject = Subject(code="physics", title="فیزیک", is_active=True)
    session.add_all([grade, branch, year, subject])
    await session.flush()
    field = FieldOfStudy(
        branch_id=branch.id,
        code="math_physics",
        title="ریاضی‌فیزیک",
        is_active=True,
    )
    session.add(field)
    await session.flush()

    book = Book(
        title="فیزیک دهم",
        grade_id=grade.id,
        academic_year_id=year.id,
        edition_label="چاپ ۱۴۰۵",
        print_year=1405,
        status=BookStatus.ready,
        catalog_status="approved",
        pdf_file_path="/tmp/physics.pdf",
        total_pdf_pages=10,
    )
    session.add(book)
    await session.flush()
    session.add(
        BookCurriculumLink(
            book_id=book.id,
            branch_id=branch.id,
            field_of_study_id=field.id,
            subject_id=subject.id,
            scope_code="field:math_physics:physics",
        )
    )
    await session.flush()
    return grade, branch, field, year, subject, book


@pytest.mark.asyncio
async def test_objective_tree_handles_prerequisites_and_scoped_units(curriculum_session):
    session = curriculum_session
    grade, branch, field, year, subject, book = await _create_curriculum(session)
    unit = CurriculumUnit(
        grade_id=grade.id,
        subject_id=subject.id,
        branch_id=branch.id,
        field_of_study_id=field.id,
        academic_year_id=year.id,
        scope_code=year.code,
        code="unit-1",
        title="حرکت",
    )
    session.add(unit)
    await session.flush()
    first = LearningObjective(
        unit_id=unit.id,
        code="physics.motion.basic",
        title="شناخت حرکت",
        assessment_profile="written",
    )
    second = LearningObjective(
        unit_id=unit.id,
        code="physics.motion.velocity",
        title="شناخت سرعت",
        assessment_profile="written",
    )
    other_branch = EducationBranch(
        code="technical_vocational",
        title="فنی‌وحرفه‌ای",
        min_grade=10,
        max_grade=12,
        is_active=True,
    )
    session.add(other_branch)
    await session.flush()
    other_field = FieldOfStudy(
        branch_id=other_branch.id,
        code="electronics",
        title="الکترونیک",
        is_active=True,
    )
    session.add(other_field)
    await session.flush()
    other_unit = CurriculumUnit(
        grade_id=grade.id,
        subject_id=subject.id,
        branch_id=other_branch.id,
        field_of_study_id=other_field.id,
        academic_year_id=year.id,
        scope_code=year.code,
        code="unit-other-branch",
        title="واحد خارج از شاخه",
    )
    session.add(other_unit)
    await session.flush()
    other_objective = LearningObjective(
        unit_id=other_unit.id,
        code="physics.electronics.basic",
        title="هدف خارج از شاخهٔ کتاب",
        assessment_profile="written",
    )
    session.add_all([first, second, other_objective])
    await session.flush()
    session.add(
        ObjectivePrerequisite(
            objective_id=second.id,
            prerequisite_id=first.id,
        )
    )
    await session.commit()

    result = await mastery_service.objective_tree(
        session,
        user_id="student-1",
        book_id=book.id,
    )

    by_code = {item["code"]: item for item in result["objectives"]}
    assert set(by_code) == {"physics.motion.basic", "physics.motion.velocity"}
    assert "physics.electronics.basic" not in by_code
    assert by_code["physics.motion.basic"]["status"] == "not_started"
    assert by_code["physics.motion.velocity"]["status"] == "locked"
    assert by_code["physics.motion.velocity"]["prerequisites"][0]["code"] == "physics.motion.basic"


@pytest.mark.asyncio
async def test_legacy_unverified_book_is_not_exposed_by_chapter_mastery_tree(curriculum_session):
    session = curriculum_session
    grade = Grade(number=5, title="پنجم", has_major=False)
    session.add(grade)
    await session.flush()
    book = Book(
        title="کتاب تأییدنشده",
        grade_id=grade.id,
        status=BookStatus.ready,
        catalog_status="legacy_unverified",
        pdf_file_path="/tmp/unverified.pdf",
        total_pdf_pages=1,
    )
    session.add(book)
    await session.commit()

    with pytest.raises(HTTPException) as error:
        await mastery_service.book_tree(session, user_id="student-1", book_id=book.id)

    assert error.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["subject", "branch_field", "academic_year"])
async def test_evidence_rejects_objectives_outside_selected_book_scope(
    curriculum_session,
    mismatch: str,
):
    session = curriculum_session
    grade, branch, field, year, subject, book = await _create_curriculum(session)

    unit_subject = subject
    unit_branch = branch
    unit_field = field
    unit_year = year
    unit_scope = year.code

    if mismatch == "subject":
        unit_subject = Subject(code="chemistry", title="شیمی", is_active=True)
        session.add(unit_subject)
        await session.flush()
    elif mismatch == "branch_field":
        unit_branch = EducationBranch(
            code="technical_vocational",
            title="فنی‌وحرفه‌ای",
            min_grade=10,
            max_grade=12,
            is_active=True,
        )
        session.add(unit_branch)
        await session.flush()
        unit_field = FieldOfStudy(
            branch_id=unit_branch.id,
            code="electronics",
            title="الکترونیک",
            is_active=True,
        )
        session.add(unit_field)
        await session.flush()
    else:
        unit_year = AcademicYear(code="1404", title="۱۴۰۴–۱۴۰۵", is_active=False)
        session.add(unit_year)
        await session.flush()
        unit_scope = unit_year.code

    unit = CurriculumUnit(
        grade_id=grade.id,
        subject_id=unit_subject.id,
        branch_id=unit_branch.id,
        field_of_study_id=unit_field.id,
        academic_year_id=unit_year.id,
        scope_code=unit_scope,
        code=f"unit-{mismatch}",
        title="واحد ناسازگار",
    )
    session.add(unit)
    await session.flush()
    objective = LearningObjective(
        unit_id=unit.id,
        code=f"objective.{mismatch}",
        title="هدف ناسازگار",
        assessment_profile="written",
    )
    session.add(objective)
    await session.commit()

    with pytest.raises(HTTPException) as error:
        await mastery_service.record_objective_evidence(
            session,
            user_id="student-1",
            objective_id=objective.id,
            source_type="self_assessment",
            source_ref=f"test-{mismatch}",
            score=80,
            qualitative_level=None,
            rubric={},
            feedback=None,
            book_id=book.id,
        )

    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_evidence_with_page_rejects_objective_not_mapped_to_that_page(curriculum_session):
    session = curriculum_session
    grade, branch, field, year, subject, book = await _create_curriculum(session)
    unit = CurriculumUnit(
        grade_id=grade.id,
        subject_id=subject.id,
        branch_id=branch.id,
        field_of_study_id=field.id,
        academic_year_id=year.id,
        scope_code=year.code,
        code="unit-page-map",
        title="صفحه‌نگاری",
    )
    session.add(unit)
    await session.flush()
    objective = LearningObjective(
        unit_id=unit.id,
        code="objective.page-map",
        title="هدف خارج از صفحه",
        assessment_profile="written",
    )
    page = BookPage(
        book_id=book.id,
        pdf_page_index=1,
        printed_page_number=10,
        markdown_content="متن آزمایشی",
        page_image_path="/tmp/page.png",
        status=PageStatus.done,
    )
    other_objective = LearningObjective(
        unit_id=unit.id,
        code="objective.other",
        title="هدف دیگر",
        assessment_profile="written",
    )
    session.add_all([objective, other_objective, page])
    await session.flush()
    from app.models.curriculum import BookPageObjective

    session.add(
        BookPageObjective(
            book_page_id=page.id,
            objective_id=other_objective.id,
            relevance=100,
        )
    )
    await session.commit()

    with pytest.raises(HTTPException) as error:
        await mastery_service.record_objective_evidence(
            session,
            user_id="student-1",
            objective_id=objective.id,
            source_type="reading",
            source_ref="page-1",
            score=None,
            qualitative_level="developing",
            rubric={},
            feedback=None,
            book_id=book.id,
            pdf_page_index=1,
        )

    assert error.value.status_code == 422
