"""Require NovFlow Desktop license for AI endpoints in desktop mode."""

from __future__ import annotations

from fastapi import HTTPException

from app.config import IS_DESKTOP
from app.license_bridge import DESKTOP, LicenseService


def require_desktop_license() -> None:
    if not IS_DESKTOP:
        return
    st = LicenseService(DESKTOP).status()
    if st.get("activated"):
        return
    err = str(st.get("error") or "请前往设置完成授权激活")
    expired = "过期" in err
    raise HTTPException(
        403,
        detail={
            "error": "license_expired" if expired else "license_required",
            "message": err,
            "product_id": DESKTOP.product_id,
            "valid_until": st.get("valid_until"),
        },
    )
