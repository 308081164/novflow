from __future__ import annotations

from app.config import settings
from app.models import User
from app.services.jimeng_image import DEFAULT_SEEDREAM_MODEL


def resolve_api_key(user: User | None = None) -> str:
    if user and user.deepseek_api_key:
        return user.deepseek_api_key
    return settings.deepseek_api_key


def has_api_key(user: User | None = None) -> bool:
    return bool(resolve_api_key(user))


def resolve_jimeng_config(user: User | None = None) -> dict[str, str]:
    api_key = ""
    if user and user.jimeng_api_key:
        api_key = user.jimeng_api_key.strip()
    if not api_key:
        api_key = settings.jimeng_api_key.strip()

    base_url = ""
    if user and user.jimeng_base_url:
        base_url = user.jimeng_base_url.strip()
    if not base_url:
        base_url = settings.jimeng_base_url

    model = ""
    if user and user.jimeng_model:
        model = user.jimeng_model.strip()
    if not model:
        model = settings.jimeng_model or DEFAULT_SEEDREAM_MODEL

    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "size": settings.jimeng_default_size,
    }


def has_jimeng_key(user: User | None = None) -> bool:
    return bool(resolve_jimeng_config(user)["api_key"])
