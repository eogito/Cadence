from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import text
from src.config import settings
from src.database import engine, Base
from src.api.auth import router as auth_router
from src.api.webhook import router as webhook_router
from src.api.approval import router as approval_router
from src.api.test import router as test_router
from src.api.briefing import router as briefing_router
from src.api.calendar import router as calendar_router
from src.api.meeting_prep import router as meeting_prep_router
from src.api.tasks import router as tasks_list_router
from src.api.context import router as context_router
from src.api.daily_schedule import router as daily_schedule_router
from src.api.settings import router as settings_router
from src.api.schedule import router as schedule_router
from src.services.scheduler_service import scheduler, load_all_rules
from src.services.user_context_service import rebuild_chroma_from_db
# Import models so SQLAlchemy registers them before create_all
import src.models.contact       # noqa: F401
import src.models.task          # noqa: F401
import src.models.recurring_rule  # noqa: F401
import src.models.user_context    # noqa: F401
import src.models.email_preferences  # noqa: F401
import src.models.schedule_block  # noqa: F401
import os

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # create_all does not add columns to pre-existing tables; backfill new columns idempotently
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS timezone VARCHAR(64) DEFAULT 'UTC'"))
    # Start scheduler and load saved recurring rules (single-process only)
    if settings.run_scheduler:
        scheduler.start()
        await load_all_rules()
    await rebuild_chroma_from_db()
    yield
    if settings.run_scheduler:
        scheduler.shutdown(wait=False)
    await engine.dispose()

app = FastAPI(
    title="AI Task Secretary API",
    version="0.1.0",
    lifespan=lifespan
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret.get_secret_value(),
    same_site="lax",
    https_only=(settings.environment == "production"),
)

app.include_router(auth_router)
app.include_router(webhook_router)
app.include_router(approval_router)
app.include_router(test_router)
app.include_router(briefing_router)
app.include_router(calendar_router)
app.include_router(meeting_prep_router)
app.include_router(tasks_list_router)
app.include_router(context_router)
app.include_router(daily_schedule_router)
app.include_router(settings_router)
app.include_router(schedule_router)

# Serve the frontend
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def serve_frontend():
    return FileResponse(os.path.join(static_dir, "index.html"))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}