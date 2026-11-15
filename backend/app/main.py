"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.llm_client import close_llm_clients
from app.db.seed import seed_database
from app.db.session import engine, get_session
from app.services.retrieval_service import close_qdrant


@asynccontextmanager
async def lifespan(_: FastAPI):
    await seed_database()
    try:
        yield
    finally:
        await close_qdrant()
        await close_llm_clients()
        await engine.dispose()


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
from app.api.curriculum import router as curriculum_router  # noqa: E402
from app.api.exams import router as exams_router  # noqa: E402
from app.api.plans import router as plans_router  # noqa: E402
from app.api.tutor import router as tutor_router  # noqa: E402

app.include_router(account_router)
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(curriculum_router)
app.include_router(plans_router)
app.include_router(tutor_router)
app.include_router(exams_router)
