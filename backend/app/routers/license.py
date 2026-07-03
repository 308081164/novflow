"""Desktop license API (offline Ed25519, desktop mode only)."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.license_bridge import DESKTOP, LicenseService

router = APIRouter(prefix="/license", tags=["license"])


def _desktop_mode() -> bool:
    return os.environ.get("NOVFLOW_DESKTOP", "").strip() in ("1", "true", "yes")


def _svc() -> LicenseService:
    return LicenseService(DESKTOP)


class ActivateIn(BaseModel):
    license_code: str = Field(min_length=8)


@router.get("/status")
def license_status():
    if not _desktop_mode():
        return {"desktop_mode": False, "activated": True, "note": "非桌面模式，跳过产品许可校验"}
    svc = _svc()
    st = svc.status()
    st["desktop_mode"] = True
    return st


@router.get("/device")
def license_device():
    if not _desktop_mode():
        raise HTTPException(400, "仅桌面模式可用")
    return _svc().device_info()


@router.post("/activate")
def license_activate(body: ActivateIn):
    if not _desktop_mode():
        raise HTTPException(400, "仅桌面模式可用")
    result = _svc().activate(body.license_code)
    if not result.get("ok"):
        raise HTTPException(400, detail=str(result.get("error", "激活失败")))
    return result


@router.post("/deactivate")
def license_deactivate():
    if not _desktop_mode():
        raise HTTPException(400, "仅桌面模式可用")
    _svc().deactivate()
    return {"ok": True}
