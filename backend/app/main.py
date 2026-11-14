"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
    return {"status": "ok"}


from app.api.admin import router as admin_router  # noqa: E402
from app.api.tutor import router as tutor_router  # noqa: E402

app.include_router(admin_router)
app.include_router(tutor_router)
