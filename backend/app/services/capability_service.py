"""Capability Registry & Feature Flags (Phase 2).

The registry is the single source of truth for which learning features exist,
whether they are enabled, and which roles/plans may use them. The student menu
is rendered from ``GET /api/v1/capabilities/me`` and every feature endpoint
re-checks the registry server-side via :func:`require_capability_enabled`.

Seeding is idempotent: existing rows are left untouched so admin edits survive
restarts.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.capabilities import Capability

logger = logging.getLogger(__name__)

# Roles recognised by the RBAC layer (see app.services.rbac).
KNOWN_ROLES = ("admin", "teacher", "student", "guardian")

# Seed catalogue: key -> (title_fa, description_fa, icon, is_enabled,
# default_route_key, sort_order). `flashcards` ships disabled until Phase 3.
SEED_CAPABILITIES: tuple[dict[str, Any], ...] = (
    {
        "key": "chat",
        "title_fa": "معلم خصوصی",
        "description_fa": "پرسش و پاسخ گام‌به‌گام بر اساس کتاب‌های درسی رسمی با ارجاع به فصل و صفحهٔ چاپی.",
        "icon": "BookOpen",
        "is_enabled": True,
        "default_route_key": "chat",
        "sort_order": 1,
    },
    {
        "key": "solve",
        "title_fa": "حل تمرین",
        "description_fa": "حل مرحله‌به‌مرحلهٔ تمرین‌ها با داده‌ها، رابطهٔ مناسب و پاسخ نهایی.",
        "icon": "Calculator",
        "is_enabled": True,
        "default_route_key": "solve",
        "sort_order": 2,
    },
    {
        "key": "quiz",
        "title_fa": "آزمون و سؤال",
        "description_fa": "طراحی سؤال و آزمون واقعی با زمان‌بندی و کارنامه، فقط از منابع کتاب درسی.",
        "icon": "GraduationCap",
        "is_enabled": True,
        "default_route_key": "quiz",
        "sort_order": 3,
    },
    {
        "key": "multimodal",
        "title_fa": "پرسش تصویری و صوتی",
        "description_fa": "ارسال عکس از تمرین یا فایل صوتی و دریافت پاسخ بر اساس کتاب درسی.",
        "icon": "ImagePlus",
        "is_enabled": True,
        "default_route_key": "vision_ocr",
        "sort_order": 4,
    },
    {
        "key": "flashcards",
        "title_fa": "فلش‌کارت هوشمند",
        "description_fa": "فلش‌کارت‌های تکرار فاصله‌دار (SM-2) ساخته‌شده از فصل‌های کتاب. در فاز ۳ فعال می‌شود.",
        "icon": "Layers",
        "is_enabled": False,
        "default_route_key": "flashcards",
        "sort_order": 5,
    },
)


def serialize_capability(capability: Capability) -> dict[str, Any]:
    return {
        "key": capability.key,
        "title_fa": capability.title_fa,
        "description_fa": capability.description_fa,
        "icon": capability.icon,
        "is_enabled": bool(capability.is_enabled),
        "allowed_roles": list(capability.allowed_roles_json or []),
        "allowed_plans": list(capability.allowed_plans_json or []),
        "default_route_key": capability.default_route_key,
        "config": dict(capability.config_json or {}),
        "sort_order": capability.sort_order,
    }


async def seed_capabilities(session: AsyncSession) -> None:
    """Insert the seed catalogue; never overwrite admin edits."""
    for spec in SEED_CAPABILITIES:
        existing = await session.get(Capability, spec["key"])
        if existing is not None:
            continue
        session.add(
            Capability(
                key=spec["key"],
                title_fa=spec["title_fa"],
                description_fa=spec["description_fa"],
                icon=spec["icon"],
                is_enabled=spec["is_enabled"],
                allowed_roles_json=[],
                allowed_plans_json=[],
                default_route_key=spec["default_route_key"],
                config_json={},
                sort_order=spec["sort_order"],
            )
        )
    await session.flush()


async def get_capability(session: AsyncSession, key: str) -> Capability | None:
    return await session.get(Capability, key)


async def list_capabilities(session: AsyncSession) -> list[Capability]:
    rows = await session.scalars(
        select(Capability).order_by(Capability.sort_order.asc(), Capability.key.asc())
    )
    return list(rows)


def is_capability_allowed(
    capability: Capability, *, role: str | None, plan_code: str | None
) -> bool:
    """Pure allow-list check: empty allow-list means "everyone"."""
    if not capability.is_enabled:
        return False
    roles = list(capability.allowed_roles_json or [])
    if roles and role not in roles:
        return False
    plans = list(capability.allowed_plans_json or [])
    if plans and plan_code not in plans:
        return False
    return True


def _user_role(user: Any) -> str | None:
    if user is None:
        return None
    role = getattr(user, "role", None)
    return str(role) if role else "student"


def _user_plan_code(user: Any) -> str | None:
    if user is None:
        return None
    plan_code = getattr(user, "plan_code", None)
    if plan_code:
        return str(plan_code)
    plan = getattr(user, "plan", None)
    if plan is not None:
        code = getattr(plan, "code", None)
        if code:
            return str(code)
    plan_id = getattr(user, "plan_id", None)
    return str(plan_id) if plan_id is not None else None


async def capabilities_for_user(
    session: AsyncSession, user: Any
) -> list[Capability]:
    """Enabled capabilities visible to this user (role + plan filtered)."""
    role = _user_role(user)
    plan_code = _user_plan_code(user)
    all_caps = await list_capabilities(session)
    return [
        cap
        for cap in all_caps
        if is_capability_allowed(cap, role=role, plan_code=plan_code)
    ]


async def require_capability_enabled(
    session: AsyncSession, key: str, user: Any = None
) -> Capability:
    """Raise 403 when the capability is unknown, disabled, or not allowed."""
    capability = await get_capability(session, key)
    if capability is None:
        raise HTTPException(status_code=404, detail=f"قابلیت «{key}» یافت نشد.")
    role = _user_role(user)
    plan_code = _user_plan_code(user)
    if not is_capability_allowed(capability, role=role, plan_code=plan_code):
        raise HTTPException(
            status_code=403,
            detail="این قابلیت در حال حاضر برای حساب شما فعال نیست.",
        )
    return capability


async def check_capability_access(
    session: AsyncSession, key: str, user: Any = None
) -> Capability | None:
    """Gate a feature endpoint against the registry (fail-open pre-seed).

    When the capability row exists, disabled / not-allowed states raise 403.
    When the row is absent (registry not seeded yet — e.g. legacy test DBs),
    the call is allowed so existing behaviour never breaks.
    """
    capability = await get_capability(session, key)
    if capability is None:
        return None
    role = _user_role(user)
    plan_code = _user_plan_code(user)
    if not is_capability_allowed(capability, role=role, plan_code=plan_code):
        raise HTTPException(
            status_code=403,
            detail="این قابلیت در حال حاضر برای حساب شما فعال نیست.",
        )
    return capability
