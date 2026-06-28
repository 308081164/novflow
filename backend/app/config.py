from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]
# 本地：novflow/backend → 项目根 novflow/；Docker 单容器：/app
ROOT = BACKEND_ROOT.parent if (BACKEND_ROOT.parent / "frontend").exists() else BACKEND_ROOT
ENV_FILE = ROOT / ".env" if (ROOT / ".env").exists() else BACKEND_ROOT / ".env"
DATA_DIR = ROOT / "data" if ROOT != BACKEND_ROOT else BACKEND_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "novflow.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ENV_FILE), extra="ignore")

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    jwt_secret: str = "novflow-dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 72
    database_url: str = f"sqlite:///{DB_PATH.as_posix()}"
    demo_email: str = "demo@example.com"
    demo_password: str = "demo123456"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000"

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
