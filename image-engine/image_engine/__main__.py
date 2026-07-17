"""NovFlow 本地生图引擎 entrypoint — GUI console by default."""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path


def _path_candidates() -> list[Path]:
    here = Path(__file__).resolve()
    candidates: list[Path] = []
    install = os.environ.get("NOVFLOW_INSTALL_DIR", "").strip()
    if install:
        candidates.append(Path(install))
    candidates.append(here.parents[1])
    if len(here.parents) > 2:
        candidates.append(here.parents[2])
    return candidates


def _ensure_paths() -> Path:
    """Put install/monorepo root on sys.path; return best root."""
    chosen: Path | None = None
    for root in _path_candidates():
        if (root / "shared").is_dir():
            root_str = str(root)
            if root_str not in sys.path:
                sys.path.insert(0, root_str)
            if chosen is None:
                chosen = root
    pkg_parent = Path(__file__).resolve().parents[1]
    if str(pkg_parent) not in sys.path:
        sys.path.insert(0, str(pkg_parent))
    return chosen or pkg_parent


_ROOT = _ensure_paths()


def _bundled_python() -> Path | None:
    """Prefer install-dir runtime, then local .venv."""
    for root in _path_candidates():
        for rel in ("runtime/Scripts/python.exe", ".venv/Scripts/python.exe"):
            candidate = root / rel.replace("/", os.sep)
            if candidate.is_file():
                return candidate.resolve()
    return None


def _maybe_reexec_bundled_runtime() -> None:
    """If launched with system Python missing deps, re-exec bundled runtime."""
    if os.environ.get("NOVFLOW_IMAGE_ENGINE_REEXEC", "").strip() in ("1", "true", "yes"):
        return
    try:
        import uvicorn  # noqa: F401

        return
    except ImportError:
        pass

    bundled = _bundled_python()
    if bundled is None:
        return
    current = Path(sys.executable).resolve()
    if bundled == current:
        return

    os.environ["NOVFLOW_IMAGE_ENGINE_REEXEC"] = "1"
    os.environ.setdefault("NOVFLOW_INSTALL_DIR", str(_ROOT))
    os.chdir(Path(__file__).resolve().parents[1])
    os.execv(str(bundled), [str(bundled), "-u", "-m", "image_engine", *sys.argv[1:]])


def _show_error(message: str) -> None:
    log_dir = Path(os.environ.get("NOVFLOW_DATA_DIR", "") or "")
    if not log_dir.is_dir():
        local = os.environ.get("LOCALAPPDATA")
        log_dir = Path(local) / "NovFlow" / "data" if local else Path.cwd()
    log_file = log_dir / "logs" / "image-engine.log"
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(message.rstrip() + "\n")
    except OSError:
        pass
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("NovFlow 本地生图引擎", message)
        root.destroy()
    except Exception:
        print(message, file=sys.stderr)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NovFlow 本地生图引擎")
    parser.add_argument(
        "--console",
        action="store_true",
        help="前台控制台模式（无 GUI / 托盘，关闭终端即停止）",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="同 --console",
    )
    parser.add_argument(
        "--activate",
        "-a",
        action="store_true",
        help="（兼容）控制台模式下弹出授权对话框",
    )
    return parser.parse_args(argv)


def _run_console_mode() -> None:
    """Legacy: uvicorn in foreground (CMD-friendly)."""
    import uvicorn

    from image_engine import settings_store
    from image_engine.app import app

    settings_store.ensure_stdio()
    cfg = settings_store.apply_to_environ()
    host = str(cfg.get("host") or settings_store.DEFAULT_HOST)
    port = int(cfg.get("port") or settings_store.DEFAULT_PORT)

    if os.environ.get("NOVFLOW_SKIP_LICENSE_UI", "").strip() not in ("1", "true", "yes"):
        from image_engine.license_gate import license_service

        if not license_service().is_activated():
            try:
                import tkinter as tk
                from tkinter import ttk

                desktop_dir: Path | None = None
                for root in _path_candidates():
                    candidate = root / "desktop"
                    if candidate.is_dir() and (candidate / "license_dialog.py").is_file():
                        desktop_dir = candidate
                        break
                if desktop_dir is not None:
                    if str(desktop_dir) not in sys.path:
                        sys.path.insert(0, str(desktop_dir))
                    from license_dialog import LicenseDialog

                    root = tk.Tk()
                    root.withdraw()
                    ttk.Label
                    dlg = LicenseDialog(root, license_service())
                    root.wait_window(dlg)
                    root.destroy()
            except Exception:
                pass

    print(f"NovFlow 本地生图引擎（控制台模式） http://{host}:{port}/v1", flush=True)
    print("关闭本窗口将停止引擎。推荐使用默认 GUI 模式（托盘后台运行）。", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="info", use_colors=False)


def main() -> None:
    _maybe_reexec_bundled_runtime()
    args = _parse_args()
    console_mode = bool(args.console or args.no_gui)
    if os.environ.get("NOVFLOW_IMAGE_ENGINE_CONSOLE", "").strip() in ("1", "true", "yes"):
        console_mode = True

    try:
        from image_engine import settings_store

        settings_store.ensure_stdio()
        if console_mode:
            _run_console_mode()
        else:
            from image_engine.console import run_console

            run_console()
    except OSError as exc:
        _show_error(f"启动失败：{exc}\n\n若端口 17860 已被占用，请先结束旧进程后重试。")
        raise SystemExit(1) from exc
    except Exception as exc:
        _show_error(f"启动失败：{exc}\n\n{traceback.format_exc()}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
