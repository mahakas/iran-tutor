"""Add ordered multi-provider failover chains to feature routes.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column(
        "feature_model_routes",
        sa.Column("fallback_provider_ids", JSON_TYPE, nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "feature_model_routes",
        sa.Column("fallback_model_names", JSON_TYPE, nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    op.drop_column("feature_model_routes", "fallback_model_names")
    op.drop_column("feature_model_routes", "fallback_provider_ids")
