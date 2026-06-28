"""数据库初始化：带重试，避免 Docker 启动时 PostgreSQL 尚未就绪导致进程退出。"""
from __future__ import annotations

import logging
import time

from sqlalchemy.exc import OperationalError

from app.database import Base, engine
from app.migrate import migrate

logger = logging.getLogger(__name__)


def init_database(max_attempts: int = 30, delay: float = 2.0) -> None:
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            Base.metadata.create_all(bind=engine)
            migrate()
            logger.info("Database schema ready")
            return
        except OperationalError as exc:
            last_error = exc
            logger.warning("Database not ready (%s/%s): %s", attempt, max_attempts, exc)
            if attempt < max_attempts:
                time.sleep(delay)
    raise RuntimeError(f"Database initialization failed after {max_attempts} attempts") from last_error
