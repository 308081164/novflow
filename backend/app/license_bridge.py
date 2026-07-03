"""Import shared license module from repo root or install dir."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def ensure_shared_path() -> None:
    candidates: list[Path] = []
    here = Path(__file__).resolve()
    candidates.append(here.parents[2])  # repo or staging root (backend/../)
    install = os.environ.get("NOVFLOW_INSTALL_DIR", "").strip()
    if install:
        candidates.append(Path(install))
    for root in candidates:
        shared = root / "shared"
        if shared.is_dir():
            root_str = str(root)
            if root_str not in sys.path:
                sys.path.insert(0, root_str)
            return


ensure_shared_path()

from shared.license import DESKTOP, IMAGE_DLC, LicenseService  # noqa: E402

__all__ = ["DESKTOP", "IMAGE_DLC", "LicenseService"]
