"""DLC license gate for Image Engine stub."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def ensure_shared_path() -> None:
    candidates: list[Path] = []
    here = Path(__file__).resolve()
    candidates.append(here.parents[2])  # novflow root
    install = os.environ.get("NOVFLOW_INSTALL_DIR", "").strip()
    if install:
        candidates.append(Path(install))
    for root in candidates:
        if (root / "shared").is_dir():
            root_str = str(root)
            if root_str not in sys.path:
                sys.path.insert(0, root_str)
            return


ensure_shared_path()

from shared.license import IMAGE_DLC, LicenseService  # noqa: E402

_svc: LicenseService | None = None


def license_service() -> LicenseService:
    global _svc
    if _svc is None:
        _svc = LicenseService(IMAGE_DLC)
    return _svc


def require_dlc_license() -> None:
    if not license_service().is_activated():
        from fastapi import HTTPException

        raise HTTPException(
            403,
            detail={
                "error": "license_required",
                "message": "NovFlow Image Engine DLC 未激活。请运行激活工具或安装器完成授权。",
                "product_id": IMAGE_DLC.product_id,
            },
        )
