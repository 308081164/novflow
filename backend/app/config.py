import os
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, "")
    if not value:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


IS_DESKTOP = _env_bool("NOVFLOW_DESKTOP") or _is_frozen()
DESKTOP_DEFAULT_PORT = 18765


def _resolve_install_dir() -> Path:
    if os.environ.get("NOVFLOW_INSTALL_DIR"):
        return Path(os.environ["NOVFLOW_INSTALL_DIR"]).resolve()
    if _is_frozen():
        return Path(sys.executable).parent.resolve()
    project_root = BACKEND_ROOT.parent
    if (project_root / "frontend").exists():
        return project_root.resolve()
    return BACKEND_ROOT.resolve()


def _resolve_data_dir() -> Path:
    if os.environ.get("NOVFLOW_DATA_DIR"):
        return Path(os.environ["NOVFLOW_DATA_DIR"]).resolve()
    if IS_DESKTOP:
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return (base / "NovFlow" / "data").resolve()
    project_root = BACKEND_ROOT.parent
    if (project_root / "frontend").exists():
        return (project_root / "data").resolve()
    return (BACKEND_ROOT / "data").resolve()


INSTALL_DIR = _resolve_install_dir()
DATA_DIR = _resolve_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "novflow.db"

if IS_DESKTOP:
    ROOT = INSTALL_DIR
else:
    ROOT = BACKEND_ROOT.parent if (BACKEND_ROOT.parent / "frontend").exists() else BACKEND_ROOT

ENV_FILE = ROOT / ".env" if (ROOT / ".env").exists() else BACKEND_ROOT / ".env"
if IS_DESKTOP and not ENV_FILE.exists():
    ENV_FILE = DATA_DIR / ".env"


if ENV_FILE.exists():
    _settings_config = SettingsConfigDict(env_file=str(ENV_FILE), extra="ignore")
else:
    _settings_config = SettingsConfigDict(extra="ignore")


class Settings(BaseSettings):
    model_config = _settings_config

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    jwt_secret: str = "novflow-dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 72
    database_url: str = f"sqlite:///{DB_PATH.as_posix()}"
    demo_email: str = "demo@example.com"
    demo_password: str = "demo123456"
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,"
        f"http://127.0.0.1:{DESKTOP_DEFAULT_PORT},http://localhost:{DESKTOP_DEFAULT_PORT}"
        if IS_DESKTOP
        else "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000"
    )

    use_minio: bool = False
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "novflow"
    minio_secret_key: str = "novflowsecret"
    minio_bucket: str = "novflow-chapters"
    minio_secure: bool = False

    jimeng_api_key: str = ""
    jimeng_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    jimeng_model: str = "doubao-seedream-4-0-250828"
    jimeng_default_size: str = "2K"
    jimeng_character_size: str = "1440x2560"


settings = Settings()
