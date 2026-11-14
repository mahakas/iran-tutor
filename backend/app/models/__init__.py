"""ORM models. Imported so Alembic autogenerate sees every table."""

from app.models.curriculum import Book, BookPage, Grade, Major  # noqa: F401

__all__ = ["Grade", "Major", "Book", "BookPage"]
