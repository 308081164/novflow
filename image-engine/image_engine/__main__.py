"""NovFlow Image Engine stub entrypoint."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure novflow root on path for shared.license
_root = Path(__file__).resolve().parents[2]
if (_root / "shared").is_dir() and str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import uvicorn

from image_engine.app import HOST, PORT, app
from image_engine.license_gate import license_service


def _maybe_activate_cli() -> None:
    if os.environ.get("NOVFLOW_SKIP_LICENSE_UI", "").strip() in ("1", "true", "yes"):
        return
    if license_service().is_activated():
        return
    if len(sys.argv) > 1 and sys.argv[1] in ("--activate", "-a"):
        sys.argv.pop(1)
    try:
        import tkinter as tk
        from tkinter import ttk

        desktop_dir = _root / "desktop"
        if desktop_dir.is_dir() and str(desktop_dir) not in sys.path:
            sys.path.insert(0, str(desktop_dir))
        from license_dialog import LicenseDialog

        root = tk.Tk()
        root.withdraw()
        ttk.Label
        dlg = LicenseDialog(root, license_service())
        root.wait_window(dlg)
        root.destroy()
    except ImportError:
        pass


def main() -> None:
    _maybe_activate_cli()
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
