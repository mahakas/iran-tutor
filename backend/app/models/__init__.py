"""ORM models. Imported so Alembic autogenerate sees every table."""

from app.models.auth import (  # noqa: F401
    BillingSettings,
    OtpCode,
    PaymentTransaction,
    Plan,
    TokenUsageLog,
    User,
    UserFile,
    UserSession,
)
from app.models.chat import ChatSession  # noqa: F401
from app.models.curriculum import Book, BookPage, Grade, Major  # noqa: F401
from app.models.exam import ExamSession  # noqa: F401

__all__ = [
    "Grade",
    "Major",
    "Book",
    "BookPage",
    "ExamSession",
    "ChatSession",
    "Plan",
    "BillingSettings",
    "User",
    "OtpCode",
    "PaymentTransaction",
    "TokenUsageLog",
    "UserSession",
    "UserFile",
]
