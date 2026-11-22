"""Opt-in local QA account seed. Never enabled in production or staging."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.production_guard import is_production
from app.db.session import async_session_factory
from app.models.auth import User
from app.services.auth_billing_service import apply_plan_to_user, get_or_init_billing_settings
from app.services.passwords import hash_password

logger = logging.getLogger(__name__)

_TEST_PHONE = "09134303348"


async def seed_mahdi_test_user() -> None:
    """Create the requested fixed QA identity only in explicitly opted-in local/dev/test DBs."""
    settings = get_settings()
    if not settings.seed_mahdi_test_user:
        return
    if is_production(settings) or str(settings.app_env).strip().lower() not in {"local", "development", "dev", "test"}:
        raise RuntimeError("SEED_MAHDI_TEST_USER is allowed only in local/development/test environments")

    async with async_session_factory() as session:
        existing = await session.scalar(select(User).where(User.phone_number == _TEST_PHONE))
        if existing is not None:
            # Preserve any name, password changes, quota adjustments or account state made by the operator.
            return

        now = datetime.now(timezone.utc)
        billing = await get_or_init_billing_settings(session)
        user = User(
            phone_number=_TEST_PHONE,
            full_name="mahdi",
            role="student",
            grade_level=12,
            major="math_physics",
            is_active=True,
            phone_verified_at=now,
            password_hash=hash_password("123"),
            created_at=now,
            updated_at=now,
        )
        apply_plan_to_user(
            user,
            plan_code="trial",
            plan_name="حساب آزمایشی",
            tokens_granted=billing.starter_tokens,
            duration_days=billing.starter_duration_days,
            carry_over_valid=False,
            now=now,
        )
        session.add(user)
        try:
            await session.commit()
            logger.warning("Local QA account mahdi was seeded; never expose this account publicly.")
        except IntegrityError:
            await session.rollback()
            # Another process may have inserted it concurrently during startup.
            logger.info("Local QA account already exists; keeping the existing record.")
