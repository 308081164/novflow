import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import ROOT, settings
from app.database import SessionLocal
from app.db_init import init_database
from app.routers import ai, auth, books, chapters, characters, images, settings as settings_router, setup_chat, worldview, write_agent
from app.services.pipeline import ensure_demo_user
from app.services.storage import storage

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    if storage.enabled:
        storage.ensure_bucket()
    db = SessionLocal()
    try:
        ensure_demo_user(db, settings.demo_email, settings.demo_password, "演示作者")
    finally:
        db.close()
    logger.info("NovFlow backend started")
    yield


app = FastAPI(
    title="NovFlow",
    description="AI 长篇网文工作台",
    version="0.2.0",
    lifespan=lifespan,
)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins + ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(settings_router.router, prefix="/api/v1")
app.include_router(books.router, prefix="/api/v1")
app.include_router(characters.router, prefix="/api/v1")
app.include_router(worldview.router, prefix="/api/v1")
app.include_router(setup_chat.router, prefix="/api/v1")
app.include_router(ai.router, prefix="/api/v1")
app.include_router(chapters.router, prefix="/api/v1")
app.include_router(write_agent.router, prefix="/api/v1")
app.include_router(images.router, prefix="/api/v1")


@app.get("/api/v1/health")
def health():
    return {
        "status": "ok",
        "deepseek_configured": bool(settings.deepseek_api_key),
        "database": "postgresql" if settings.database_url.startswith("postgresql") else "sqlite",
        "minio_enabled": settings.use_minio,
        "minio_bucket": settings.minio_bucket if settings.use_minio else None,
        "jimeng_configured": bool(settings.jimeng_api_key),
    }


STATIC_DIR = ROOT / "frontend" / "dist"
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return {"detail": "Not Found"}
        index = STATIC_DIR / "index.html"
        if index.exists():
            return FileResponse(index)
        return {"detail": "frontend not built"}

else:

    @app.get("/")
    def root():
        return {
            "message": "NovFlow API 运行中",
            "docs": "/docs",
        }
