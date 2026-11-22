"""Add password authentication, phone verification and one-time signup challenges."""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "a4b5c6d7e8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(length=512), nullable=True))
    op.add_column("users", sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("otp_codes", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("otp_codes", sa.Column("verification_token_hash", sa.String(length=128), nullable=True))
    op.add_column("otp_codes", sa.Column("verification_token_expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("otp_codes", "verification_token_expires_at")
    op.drop_column("otp_codes", "verification_token_hash")
    op.drop_column("otp_codes", "verified_at")
    op.drop_column("users", "deleted_at")
    op.drop_column("users", "phone_verified_at")
    op.drop_column("users", "password_hash")
