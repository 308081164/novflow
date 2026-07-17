"""Optional CLI license gate (Tk dialog). Electron startup does not call this."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _install_dir() -> Path:
    if os.environ.get("NOVFLOW_INSTALL_DIR"):
        return Path(os.environ["NOVFLOW_INSTALL_DIR"]).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _ensure_import_path() -> None:
    root = _install_dir()
    if (root / "shared").is_dir() and str(root) not in sys.path:
        sys.path.insert(0, str(root))
    desktop = root / "desktop"
    if desktop.is_dir() and str(desktop) not in sys.path:
        sys.path.insert(0, str(desktop))


def main() -> int:
    parser = argparse.ArgumentParser(description="NovFlow desktop license gate (CLI only)")
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="Print activation status and exit without showing a dialog",
    )
    args = parser.parse_args()

    if os.environ.get("NOVFLOW_SKIP_LICENSE_GATE", "").strip().lower() in ("1", "true", "yes"):
        print("license gate skipped: NOVFLOW_SKIP_LICENSE_GATE", flush=True)
        return 0

    _ensure_import_path()
    try:
        from shared.license import DESKTOP, LicenseService
        from license_dialog import show_license_dialog
    except ImportError as exc:
        print(f"license gate skipped: {exc}", file=sys.stderr)
        return 0

    svc = LicenseService(DESKTOP)
    if svc.is_activated():
        print("license gate: already activated", flush=True)
        return 0

    if args.status_only:
        status = svc.status()
        err = status.get("error", "未激活")
        print(f"license gate: not activated ({err})", flush=True)
        return 0

    print("license gate: showing activation dialog", flush=True)
    show_license_dialog(svc)
    print("license gate: dialog closed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
