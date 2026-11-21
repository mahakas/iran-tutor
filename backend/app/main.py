"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.llm_client import close_llm_clients
from app.core.runtime_config import load_runtime_overrides_from_db
from app.db.seed import seed_database
from app.db.session import engine, get_session
from app.services.retrieval_service import close_qdrant


@asynccontextmanager
async def lifespan(_: FastAPI):
    _warn_insecure_admin_defaults()
    await seed_database()
    await load_runtime_overrides_from_db()
    try:
        yield
    finally:
        await close_qdrant()
        await close_llm_clients()
        await engine.dispose()


_INSECURE_ADMIN_PASSWORDS = {"", "123", "admin", "password", "change_me", "changeme"}


def _warn_insecure_admin_defaults() -> None:
    """Log loudly when the admin login still uses a known-weak default (never blocks startup)."""
    import logging

    from app.core.config import get_settings

    settings = get_settings()
    if (settings.admin_password or "").strip().lower() in _INSECURE_ADMIN_PASSWORDS:
        logging.getLogger("app.security").warning(
            "ADMIN_PASSWORD is a known-weak default; set a strong value in .env before any real use."
        )


app = FastAPI(title="Iran AI Tutor", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ok", "mode": "demo" if get_settings().demo_mode else "production"}


@app.get("/api/v1/system/status")
async def system_status(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    """Expose non-secret diagnostics useful for the local test harness."""
    await session.execute(text("SELECT 1"))
    settings = get_settings()
    return {
        "status": "ok",
        "mode": "demo" if settings.demo_mode else "production",
        "database": "sqlite" if settings.database_url.startswith("sqlite") else "postgresql",
        "vector_backend": settings.vector_backend,
        "vector_search": not settings.demo_mode,
        "external_models": not settings.demo_mode,
    }


from app.api.account import router as account_router  # noqa: E402
from app.api.admin import router as admin_router  # noqa: E402
from app.api.auth import router as auth_router  # noqa: E402
from app.api.capabilities import admin_router as capabilities_admin_router  # noqa: E402
from app.api.capabilities import router as capabilities_router  # noqa: E402
from app.api.curriculum import router as curriculum_router  # noqa: E402
from app.api.exams import router as exams_router  # noqa: E402
from app.api.flashcards import admin_router as flashcards_admin_router  # noqa: E402
from app.api.flashcards import router as flashcards_router  # noqa: E402
from app.api.phase4_admin import router as phase4_admin_router  # noqa: E402
from app.api.phase5 import router as phase5_router  # noqa: E402
from app.api.phase5_admin import router as phase5_admin_router  # noqa: E402
from app.api.phase6 import router as phase6_router  # noqa: E402
from app.api.phase6_admin import router as phase6_admin_router  # noqa: E402
from app.api.feedback import router as feedback_router  # noqa: E402
from app.api.kb import router as kb_router  # noqa: E402
from app.api.plans import router as plans_router  # noqa: E402
from app.api.skills import router as skills_router  # noqa: E402
from app.api.tutor import router as tutor_router  # noqa: E402

app.include_router(account_router)
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(curriculum_router)
app.include_router(plans_router)
app.include_router(tutor_router)
app.include_router(exams_router)
app.include_router(feedback_router)
app.include_router(capabilities_router)
app.include_router(capabilities_admin_router)
app.include_router(skills_router)
app.include_router(kb_router)
app.include_router(flashcards_router)
app.include_router(flashcards_admin_router)
app.include_router(phase4_admin_router)
app.include_router(phase5_router)
app.include_router(phase5_admin_router)
app.include_router(phase6_router)
app.include_router(phase6_admin_router)
