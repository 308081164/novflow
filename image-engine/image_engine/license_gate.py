"""DLC license gate for Image Engine stub."""



from __future__ import annotations



import os

import sys

from pathlib import Path





def _path_candidates() -> list[Path]:

    """Roots that may contain shared/ (install dir or monorepo novflow/)."""

    here = Path(__file__).resolve()

    candidates: list[Path] = []

    install = os.environ.get("NOVFLOW_INSTALL_DIR", "").strip()

    if install:

        candidates.append(Path(install))

    # install: {app}/image_engine/license_gate.py -> parents[1] == {app}

    # monorepo: image-engine/image_engine/license_gate.py -> parents[2] == novflow/

    candidates.append(here.parents[1])

    if len(here.parents) > 2:

        candidates.append(here.parents[2])

    return candidates





def ensure_shared_path() -> Path | None:

    for root in _path_candidates():

        if (root / "shared").is_dir():

            root_str = str(root)

            if root_str not in sys.path:

                sys.path.insert(0, root_str)

            return root

    return None





_ROOT = ensure_shared_path()



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

                "message": "NovFlow 本地生图引擎未激活。请在引擎控制台「授权」页完成激活。",

                "product_id": IMAGE_DLC.product_id,

            },

        )


