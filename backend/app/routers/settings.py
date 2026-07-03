from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import (
    ImageEngineEulaIn,
    ImageEngineStatusOut,
    ImageEngineTestOut,
    UserSettingsIn,
    UserSettingsOut,
)
from app.services.api_key import has_api_key, has_jimeng_key
from app.services.image_providers.base import ImageEngineError, has_local_dlc, resolve_image_backend
from app.services.image_providers.local_dlc import LocalDlcProvider, resolve_local_dlc_base_url

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
        image_backend=resolve_image_backend(user),
        local_dlc_base_url=resolve_local_dlc_base_url(user),
        local_dlc_tier=(user.local_dlc_tier or "auto").strip() or "auto",
        local_dlc_prompt_mode=(user.local_dlc_prompt_mode or "raw").strip() or "raw",
        local_dlc_eula_accepted=user.local_dlc_eula_accepted_at is not None,
        local_dlc_eula_accepted_at=user.local_dlc_eula_accepted_at,
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
    if data.image_backend is not None:
        backend = data.image_backend.strip().lower()
        if backend not in ("jimeng", "local_dlc", "off"):
            raise HTTPException(400, "无效的生图后端")
        if backend == "local_dlc" and not user.local_dlc_eula_accepted_at:
            raise HTTPException(400, "启用本地 DLC 前须先确认免责声明")
        user.image_backend = backend
    if data.local_dlc_base_url is not None:
        user.local_dlc_base_url = data.local_dlc_base_url.strip()
    if data.local_dlc_tier is not None:
        user.local_dlc_tier = data.local_dlc_tier.strip()
    if data.local_dlc_prompt_mode is not None:
        mode = data.local_dlc_prompt_mode.strip().lower()
        if mode not in ("raw", "assist"):
            raise HTTPException(400, "无效的提示词模式")
        user.local_dlc_prompt_mode = mode
    db.commit()
    db.refresh(user)
    return _settings_out(user)


@router.get("/image-engine/status", response_model=ImageEngineStatusOut)
async def image_engine_status(user: User = Depends(get_current_user)):
    backend = resolve_image_backend(user)
    out = ImageEngineStatusOut(backend=backend, reachable=False, status="not_configured")
    if backend != "local_dlc":
        out.message = "当前未使用本地 DLC 后端"
        return out
    if not has_local_dlc(user):
        out.status = "eula_pending"
        out.message = "请先确认本地生图免责声明"
        return out
    provider = LocalDlcProvider(user)
    try:
        health = await provider.health()
        out.reachable = True
        out.status = str(health.get("status") or "ok")
        out.tier = str(health.get("tier") or "")
        out.model = str(health.get("model") or "")
        out.vram_mb = int(health.get("vram_mb") or 0)
        out.message = "本地引擎运行中"
    except ImageEngineError as exc:
        out.status = "unreachable"
        out.message = str(exc)
    return out


@router.post("/image-engine/test", response_model=ImageEngineTestOut)
async def image_engine_test(user: User = Depends(get_current_user)):
    if resolve_image_backend(user) != "local_dlc":
        raise HTTPException(400, "请先将生图后端切换为「本地 DLC」")
    if not has_local_dlc(user):
        raise HTTPException(400, "请先确认本地生图免责声明")
    provider = LocalDlcProvider(user)
    try:
        await provider.health()
        await provider.test_generate()
        return ImageEngineTestOut(ok=True, message="连接成功，测试图已生成")
    except ImageEngineError as exc:
        raise HTTPException(400, str(exc))


@router.post("/image-engine/eula", response_model=UserSettingsOut)
def accept_image_engine_eula(
    data: ImageEngineEulaIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not data.accepted:
        raise HTTPException(400, "须勾选同意方可启用本地生图")
    if not user.local_dlc_eula_accepted_at:
        user.local_dlc_eula_accepted_at = datetime.utcnow()
        db.commit()
        db.refresh(user)
    return _settings_out(user)
