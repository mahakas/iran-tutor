"""Image and voice question understanding before textbook-grounded tutoring."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.config import get_settings
from app.core.llm_client import transcribe_audio, vision_json
from app.services.tutor_service import answer_from_textbook


class ImageQuestionExtraction(BaseModel):
    question_text: str = Field(min_length=1)
    visual_description: str = ""
    uncertain_parts: list[str] = Field(default_factory=list)


IMAGE_QUESTION_SYSTEM_PROMPT = """تصویر ارسالی دانش‌آموز را برای فهم صورت سؤال بخوان.
فقط محتوای قابل‌مشاهده را استخراج کن؛ چیزی را حدس نزن یا حل نکن.
متن فارسی، اعداد، واحدها و نمادها را با دقت حفظ کن و فرمول‌ها را به LaTeX استاندارد تبدیل کن.
اگر شکل یا نمودار برای فهم سؤال لازم است، محور‌ها، برچسب‌ها و ویژگی‌های مهمش را کوتاه توصیف کن.
هر بخش ناخوانا یا مبهم را در uncertain_parts بنویس.
فقط JSON مطابق این ساختار بده:
{"question_text":"...", "visual_description":"...", "uncertain_parts":[]}
"""


def _validate_image_extraction(parsed: dict[str, Any]) -> ImageQuestionExtraction:
    try:
        return ImageQuestionExtraction.model_validate(parsed)
    except ValidationError as error:
        raise ValueError("vision model did not return a valid question extraction") from error


async def answer_image_question(
    *,
    image_bytes: bytes,
    image_mime_type: str,
    grade_number: int,
    major_code: str | None,
    book_id: int,
    top_k: int = 5,
) -> dict[str, Any]:
    """Read a photographed question and solve it using the selected textbook only."""
    settings = get_settings()
    parsed, _usage = await vision_json(
        settings.vision_model_primary,
        IMAGE_QUESTION_SYSTEM_PROMPT,
        "صورت سؤال و اطلاعات درسی لازم را از تصویر استخراج کن.",
        image_bytes,
        image_mime_type,
    )
    extraction = _validate_image_extraction(parsed)
    query = extraction.question_text.strip()
    if extraction.visual_description.strip():
        query += "\n\nتوصیف شکل سؤال: " + extraction.visual_description.strip()
    result = await answer_from_textbook(
        query=query,
        grade_number=grade_number,
        major_code=major_code,
        book_id=book_id,
        top_k=top_k,
    )
    result["recognized_question"] = extraction.question_text
    result["visual_description"] = extraction.visual_description
    result["uncertain_parts"] = extraction.uncertain_parts
    return result


async def answer_audio_question(
    *,
    audio_bytes: bytes,
    filename: str,
    content_type: str,
    grade_number: int,
    major_code: str | None,
    book_id: int,
    top_k: int = 5,
) -> dict[str, Any]:
    """Transcribe a Persian voice question, then answer from the selected book."""
    transcript = await transcribe_audio(
        audio_bytes,
        filename=filename,
        content_type=content_type,
    )
    result = await answer_from_textbook(
        query=transcript,
        grade_number=grade_number,
        major_code=major_code,
        book_id=book_id,
        top_k=top_k,
    )
    result["transcript"] = transcript
    return result
