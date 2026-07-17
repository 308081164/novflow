"""Desktop license API (offline Ed25519, desktop mode only)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import IS_DESKTOP
from app.license_bridge import DESKTOP, LicenseService

router = APIRouter(prefix="/license", tags=["license"])


def _desktop_mode() -> bool:
    return IS_DESKTOP


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
    if st.get("activated") and st.get("valid_until"):
        st.setdefault("license_mode", st.get("license_mode") or "time_limited")
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
