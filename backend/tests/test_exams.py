"""Exam generation validation, answer-key privacy, and scoring tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models.exam import ExamStatus
from app.services.exam_service import grade_exam, public_exam, submit_exam, validate_questions


def _question(question_id: str, correct: str = "A") -> dict:
    return {
        "id": question_id,
        "prompt": "کدام گزینه درست است؟",
        "choices": {"A": "گزینه الف", "B": "گزینه ب", "C": "گزینه پ", "D": "گزینه ت"},
        "correct_option": correct,
        "explanation": "این توضیح از متن کتاب است.",
        "points": 1.0,
        "source": {"book_title": "فیزیک ۳", "printed_page_number": 14},
    }


def test_questions_require_exact_count_and_source_indexes():
    raw = {
        "questions": [
            {
                "prompt": "پرسش",
                "choices": {"A": "الف", "B": "ب", "C": "پ", "D": "ت"},
                "correct_option": "B",
                "explanation": "توضیح",
                "source_index": 0,
            }
        ]
    }
    assert len(validate_questions(raw, expected_count=1, source_count=1)) == 1
    with pytest.raises(ValueError, match="expected 2"):
        validate_questions(raw, expected_count=2, source_count=1)
    raw["questions"][0]["source_index"] = 2
    with pytest.raises(ValueError, match="source"):
        validate_questions(raw, expected_count=1, source_count=1)


def test_public_exam_never_leaks_answer_key_or_explanation():
    exam = SimpleNamespace(
        id="uuid",
        book_id=1,
        grade_number=12,
        major_code="math_physics",
        title="آزمون فصل ۱",
        exam_type="konkoor",
        time_limit_seconds=900,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        status=ExamStatus.active,
        questions=[_question("q1")],
    )

    result = public_exam(exam)

    assert "correct_option" not in result["questions"][0]
    assert "explanation" not in result["questions"][0]
    assert result["questions"][0]["choices"]["A"] == "گزینه الف"


def test_konkoor_scoring_applies_one_third_negative_marking():
    questions = [_question("q1"), _question("q2"), _question("q3"), _question("q4")]

    report = grade_exam(
        questions,
        {"q1": "A", "q2": "A", "q3": "B"},
        exam_type="konkoor",
    )

    assert report["correct"] == 2
    assert report["wrong"] == 1
    assert report["unanswered"] == 1
    assert report["scale"] == "percent"
    assert report["score"] == 41.67


def test_final_exam_score_is_scaled_to_twenty():
    questions = [_question("q1"), _question("q2"), _question("q3"), _question("q4")]
    report = grade_exam(questions, {"q1": "A", "q2": "B"}, exam_type="final")
    assert report["scale"] == "out_of_20"
    assert report["score"] == 5.0


def test_submit_exam_persists_answers_report_and_status():
    exam = SimpleNamespace(
        status=ExamStatus.active,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        questions=[_question("q1")],
        exam_type="final",
        submitted_at=None,
        submitted_answers=None,
        report_card=None,
    )

    report = submit_exam(exam, {"q1": "A"})

    assert exam.status == ExamStatus.submitted
    assert exam.submitted_answers == {"q1": "A"}
    assert exam.report_card == report
    assert report["score"] == 20.0


def test_submit_exam_rejects_unknown_question_ids():
    exam = SimpleNamespace(
        status=ExamStatus.active,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        questions=[_question("q1")],
        exam_type="final",
    )
    with pytest.raises(ValueError, match="unknown question"):
        submit_exam(exam, {"q99": "A"})


def test_expired_exam_is_marked_expired_and_rejected():
    exam = SimpleNamespace(
        status=ExamStatus.active,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        questions=[_question("q1")],
        exam_type="final",
    )
    with pytest.raises(TimeoutError):
        submit_exam(exam, {"q1": "A"})
    assert exam.status == ExamStatus.expired


def test_public_exam_always_includes_utc_offset_for_naive_datetimes():
    naive_expires = datetime(2026, 11, 14, 22, 30, 0)
    exam = SimpleNamespace(
        id="uuid",
        book_id=1,
        grade_number=12,
        major_code="math_physics",
        title="آزمون فصل ۱",
        exam_type="konkoor",
        time_limit_seconds=900,
        expires_at=naive_expires,
        status=ExamStatus.active,
        questions=[_question("q1")],
    )

    result = public_exam(exam)

    assert result["expires_at"].endswith("+00:00")
    assert datetime.fromisoformat(result["expires_at"]).tzinfo == timezone.utc

