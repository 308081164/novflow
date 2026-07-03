"""Require NovFlow Desktop license for AI endpoints in desktop mode."""

from __future__ import annotations

import os

from fastapi import HTTPException

from app.license_bridge import DESKTOP, LicenseService


def require_desktop_license() -> None:
    if os.environ.get("NOVFLOW_DESKTOP", "").strip() not in ("1", "true", "yes"):
        return
    svc = LicenseService(DESKTOP)
    if not svc.is_activated():
        raise HTTPException(
            403,
            detail={
                "error": "license_required",
                "message": "NovFlow Desktop 未激活。请在启动器或设置中完成授权激活。",
                "product_id": DESKTOP.product_id,
            },
        )
