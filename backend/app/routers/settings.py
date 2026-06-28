from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import UserSettingsIn, UserSettingsOut
from app.services.api_key import has_api_key, has_jimeng_key

router = APIRouter(prefix="/settings", tags=["settings"])


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return key[:4] + "****" + key[-4:]


def _settings_out(user: User) -> UserSettingsOut:
    base_url = (user.jimeng_base_url or "").strip() or settings.jimeng_base_url
    model = (user.jimeng_model or "").strip() or settings.jimeng_model
    return UserSettingsOut(
        display_name=user.display_name,
        deepseek_configured=has_api_key(user),
        deepseek_api_key_masked=mask_key(user.deepseek_api_key),
        jimeng_configured=has_jimeng_key(user),
        jimeng_api_key_masked=mask_key(user.jimeng_api_key),
        jimeng_base_url=base_url,
        jimeng_model=model,
    )


@router.get("", response_model=UserSettingsOut)
def get_settings(user: User = Depends(get_current_user)):
    return _settings_out(user)


@router.put("", response_model=UserSettingsOut)
def update_settings(
    data: UserSettingsIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if data.display_name is not None:
        user.display_name = data.display_name
    if data.deepseek_api_key is not None:
        user.deepseek_api_key = data.deepseek_api_key.strip()
    if data.jimeng_api_key is not None:
        user.jimeng_api_key = data.jimeng_api_key.strip()
    if data.jimeng_base_url is not None:
        user.jimeng_base_url = data.jimeng_base_url.strip()
    if data.jimeng_model is not None:
        user.jimeng_model = data.jimeng_model.strip()
    db.commit()
    db.refresh(user)
    return _settings_out(user)
