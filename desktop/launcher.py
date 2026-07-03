"""NovFlow Windows desktop launcher — single instance, hidden uvicorn, embedded WebView."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


def _ensure_shared_import_path() -> None:
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    else:
        roots.append(Path(__file__).resolve().parent.parent)
    for root in roots:
        if (root / "shared").is_dir() and str(root) not in sys.path:
            sys.path.insert(0, str(root))


_ensure_shared_import_path()

DEFAULT_PORT = 18765
MUTEX_NAME = "Global\\NovFlowDesktopLauncher"
CREATE_NO_WINDOW = 0x08000000
ERROR_ALREADY_EXISTS = 183
STATE_FILE = "server.json"
WINDOW_TITLE = "NovFlow"
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 800


def _install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    if os.environ.get("NOVFLOW_DATA_DIR"):
        return Path(os.environ["NOVFLOW_DATA_DIR"]).resolve()
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return (base / "NovFlow" / "data").resolve()


def _state_path(data_dir: Path) -> Path:
    return data_dir / STATE_FILE


def _read_state(data_dir: Path) -> dict | None:
    path = _state_path(data_dir)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_state(data_dir: Path, port: int, pid: int) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "port": port,
        "pid": pid,
        "url": f"http://127.0.0.1:{port}",
        "started_at": int(time.time()),
    }
    _state_path(data_dir).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _health_ok(port: int) -> bool:
    url = f"http://127.0.0.1:{port}/api/v1/health"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and exit_code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _runtime_python(install_dir: Path) -> Path:
    runtime = install_dir / "runtime"
    for rel in ("Scripts/python.exe", "bin/python.exe"):
        candidate = runtime / rel.replace("/", os.sep)
        if candidate.is_file():
            return candidate
    return runtime / "Scripts" / "python.exe"


def _runtime_uvicorn(install_dir: Path) -> Path:
    runtime = install_dir / "runtime"
    for rel in ("Scripts/uvicorn.exe", "bin/uvicorn"):
        candidate = runtime / rel.replace("/", os.sep)
        if candidate.is_file():
            return candidate
    return runtime / "Scripts" / "uvicorn.exe"


def _backend_log_path(data_dir: Path) -> Path:
    return data_dir / "backend.log"


def _read_log_tail(data_dir: Path, limit: int = 1200) -> str:
    path = _backend_log_path(data_dir)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:].strip()
    except OSError:
        return ""


def _clear_stale_state(data_dir: Path) -> None:
    path = _state_path(data_dir)
    if path.is_file():
        try:
            path.unlink()
        except OSError:
            pass


def _show_error(message: str) -> None:
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(0, message, WINDOW_TITLE, 0x10)
    else:
        print(message, file=sys.stderr)


def _start_server(install_dir: Path, data_dir: Path, port: int) -> subprocess.Popen:
    python = _runtime_python(install_dir)
    uvicorn = _runtime_uvicorn(install_dir)
    backend_dir = install_dir / "backend"
    if not backend_dir.is_dir():
        raise FileNotFoundError(f"未找到 backend 目录：{backend_dir}")
    assets_dir = install_dir / "frontend" / "dist" / "assets"
    if not assets_dir.is_dir():
        raise FileNotFoundError(
            f"未找到前端资源：{assets_dir}\n安装包不完整，请重新安装 NovFlow。"
        )

    if uvicorn.is_file():
        cmd = [
            str(uvicorn),
            "app.main:app",
            "--app-dir",
            str(backend_dir),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ]
    elif python.is_file():
        cmd = [
            str(python),
            "-m",
            "uvicorn",
            "app.main:app",
            "--app-dir",
            str(backend_dir),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ]
    else:
        raise FileNotFoundError(f"未找到运行时 Python：{python}")

    env = os.environ.copy()
    env["NOVFLOW_DESKTOP"] = "1"
    env["NOVFLOW_INSTALL_DIR"] = str(install_dir)
    env["NOVFLOW_DATA_DIR"] = str(data_dir)
    env["USE_MINIO"] = "false"
    env.setdefault("PYTHONUTF8", "1")

    log_path = _backend_log_path(data_dir)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "a", encoding="utf-8")
    log_file.write(f"\n--- NovFlow backend start {time.strftime('%Y-%m-%d %H:%M:%S')} port={port} ---\n")
    log_file.flush()

    creationflags = CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.Popen(
        cmd,
        cwd=str(install_dir),
        env=env,
        creationflags=creationflags,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )


def _wait_for_health(port: int, proc: subprocess.Popen, timeout: float = 90.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        if _health_ok(port):
            return True
        time.sleep(0.5)
    return False


def _open_browser(port: int) -> None:
    webbrowser.open(f"http://127.0.0.1:{port}")


def _open_webview(port: int) -> bool:
    """打开嵌入式 WebView 窗口；失败时返回 False。"""
    url = f"http://127.0.0.1:{port}"
    try:
        import webview  # pywebview
    except ImportError:
        return False
    try:
        window = webview.create_window(WINDOW_TITLE, url, width=WINDOW_WIDTH, height=WINDOW_HEIGHT)
        webview.start(gui="edgechromium")
        return True
    except Exception:
        try:
            window = webview.create_window(WINDOW_TITLE, url, width=WINDOW_WIDTH, height=WINDOW_HEIGHT)
            webview.start()
            return True
        except Exception:
            return False


def _open_ui(port: int) -> None:
    if not _open_webview(port):
        _open_browser(port)


def _maybe_show_license_dialog() -> None:
    try:
        from shared.license import DESKTOP, LicenseService
        from license_dialog import LicenseDialog
    except ImportError:
        return
    svc = LicenseService(DESKTOP)
    if svc.is_activated():
        return
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        return
    root = tk.Tk()
    root.withdraw()
    ttk.Label  # preload themed widgets
    dlg = LicenseDialog(root, svc)
    root.wait_window(dlg)
    root.destroy()


def _acquire_mutex() -> bool:
    if sys.platform != "win32":
        return True
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def main() -> int:
    install_dir = _install_dir()
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    state = _read_state(data_dir)
    port = int(state.get("port") if state else DEFAULT_PORT) or DEFAULT_PORT

    if _health_ok(port):
        _write_state(data_dir, port, int(state.get("pid") or 0) if state else 0)
        _maybe_show_license_dialog()
        _open_ui(port)
        return 0

    _clear_stale_state(data_dir)
    port = DEFAULT_PORT

    if not _acquire_mutex():
        for _ in range(30):
            if _health_ok(port):
                _open_ui(port)
                return 0
            time.sleep(0.5)
        _show_error(f"NovFlow 正在启动中或端口 {port} 不可用，请稍后再试。")
        return 1

    try:
        proc = _start_server(install_dir, data_dir, port)
    except FileNotFoundError as exc:
        _show_error(str(exc))
        return 1

    if not _wait_for_health(port, proc):
        exit_code = proc.poll()
        if exit_code is None:
            proc.terminate()
        tail = _read_log_tail(data_dir)
        msg = f"NovFlow 后端启动失败（端口 {port}）。"
        if exit_code is not None:
            msg += f"\n进程已退出，代码 {exit_code}。"
        if tail:
            msg += f"\n\n最近日志（{ _backend_log_path(data_dir) }）：\n{tail}"
        else:
            msg += "\n请检查安装目录是否完整。"
        _show_error(msg)
        return 1

    _write_state(data_dir, port, proc.pid)
    _maybe_show_license_dialog()
    _open_ui(port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
