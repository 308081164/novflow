"""NovFlow backend sidecar — starts uvicorn, writes server.json, runs until terminated."""

from __future__ import annotations

import argparse
import atexit
import ctypes
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_PORT = 18765
CREATE_NO_WINDOW = 0x08000000
STATE_FILE = "server.json"
LAUNCHER_PID_FILE = "launcher.pid"
LAUNCHER_LOG_FILE = "launcher.log"

JobObjectExtendedLimitInformation = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

_LOG_HANDLE: object | None = None
_JOB_HANDLE: int | None = None
_BACKEND_PROC: subprocess.Popen | None = None
_SHUTTING_DOWN = False


def _install_dir() -> Path:
    if os.environ.get("NOVFLOW_INSTALL_DIR"):
        return Path(os.environ["NOVFLOW_INSTALL_DIR"]).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    if os.environ.get("NOVFLOW_DATA_DIR"):
        return Path(os.environ["NOVFLOW_DATA_DIR"]).resolve()
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return (base / "NovFlow" / "data").resolve()


def _init_log(data_dir: Path) -> None:
    global _LOG_HANDLE
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / LAUNCHER_LOG_FILE
    try:
        _LOG_HANDLE = open(path, "a", encoding="utf-8")
        _LOG_HANDLE.write(
            f"\n--- NovFlow backend {time.strftime('%Y-%m-%d %H:%M:%S')} pid={os.getpid()} ---\n"
        )
        _LOG_HANDLE.flush()
    except OSError:
        _LOG_HANDLE = None


def _log(message: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] [backend] {message}"
    if _LOG_HANDLE is not None:
        try:
            _LOG_HANDLE.write(line + "\n")
            _LOG_HANDLE.flush()
        except OSError:
            pass


def _state_path(data_dir: Path) -> Path:
    return data_dir / STATE_FILE


def _launcher_pid_path(data_dir: Path) -> Path:
    return data_dir / LAUNCHER_PID_FILE


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


def _write_launcher_pid(data_dir: Path, pid: int) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    _launcher_pid_path(data_dir).write_text(str(pid), encoding="utf-8")


def _remove_runtime_files(data_dir: Path) -> None:
    for name in (STATE_FILE, LAUNCHER_PID_FILE):
        path = data_dir / name
        if path.is_file():
            try:
                path.unlink()
            except OSError:
                pass


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
        return bool(ok) and exit_code.value == 259
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _create_kill_on_close_job() -> int | None:
    if sys.platform != "win32":
        return None
    kernel32 = ctypes.windll.kernel32
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = kernel32.SetInformationJobObject(
        job,
        JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        kernel32.CloseHandle(job)
        return None
    return job


def _assign_process_to_job(job: int | None, proc: subprocess.Popen) -> None:
    if not job or sys.platform != "win32":
        return
    handle = proc._handle  # noqa: SLF001
    if handle:
        ctypes.windll.kernel32.AssignProcessToJobObject(job, handle)


def _kill_process_tree(pid: int) -> None:
    if pid <= 0:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, OSError):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def _kill_install_runtime_processes(install_dir: Path, except_pid: int | None = None) -> None:
    if sys.platform != "win32":
        return
    runtime_key = str((install_dir / "runtime").resolve()).lower()
    ps_cmd = (
        "Get-CimInstance Win32_Process | Where-Object { "
        "($_.Name -eq 'python.exe' -or $_.Name -eq 'uvicorn.exe') "
        "-and $_.CommandLine -and $_.CommandLine.ToLower().Contains($env:NOVFLOW_INSTALL_KEY) "
        "} | ForEach-Object { $_.ProcessId }"
    )
    env = os.environ.copy()
    env["NOVFLOW_INSTALL_KEY"] = runtime_key
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            env=env,
            creationflags=CREATE_NO_WINDOW,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if not line.isdigit():
            continue
        pid = int(line)
        if except_pid and pid == except_pid:
            continue
        _kill_process_tree(pid)


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

    # Prefer `python -m uvicorn`: Windows venv --copies often ships a broken uvicorn.exe
    # that exits with code 1 and no stderr (see packaged desktop installs).
    if python.is_file():
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
    elif uvicorn.is_file():
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


def _shutdown(install_dir: Path | None, data_dir: Path | None) -> None:
    global _SHUTTING_DOWN, _JOB_HANDLE
    if _SHUTTING_DOWN:
        return
    _SHUTTING_DOWN = True
    _log("shutdown")

    if _BACKEND_PROC is not None and _BACKEND_PROC.poll() is None:
        _kill_process_tree(_BACKEND_PROC.pid)
        try:
            _BACKEND_PROC.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    elif data_dir is not None:
        state = _read_state(data_dir)
        if state:
            backend_pid = int(state.get("pid") or 0) or None
            if backend_pid and _pid_alive(backend_pid):
                _kill_process_tree(backend_pid)

    if install_dir is not None:
        _kill_install_runtime_processes(install_dir, except_pid=os.getpid())

    if data_dir is not None:
        _remove_runtime_files(data_dir)

    if _JOB_HANDLE and sys.platform == "win32":
        ctypes.windll.kernel32.CloseHandle(_JOB_HANDLE)
        _JOB_HANDLE = None


def _terminate_stale_backend(data_dir: Path, install_dir: Path) -> None:
    state = _read_state(data_dir)
    backend_pid = int(state.get("pid") or 0) if state else 0
    if backend_pid and backend_pid != os.getpid() and _pid_alive(backend_pid):
        _log(f"terminating stale backend pid={backend_pid}")
        _kill_process_tree(backend_pid)
    _kill_install_runtime_processes(install_dir, except_pid=os.getpid())
    _remove_runtime_files(data_dir)


def _ensure_shared_import(install_dir: Path) -> None:
    root = str(install_dir.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)


def _log_license_status(install_dir: Path) -> None:
    """Non-blocking license check — log warning only, never block startup."""
    try:
        _ensure_shared_import(install_dir)
        from shared.license import DESKTOP, LicenseService

        svc = LicenseService(DESKTOP)
        if svc.is_activated():
            _log("license: activated")
            return
        status = svc.status()
        err = status.get("error", "未激活")
        _log(f"license warning: not activated ({err}) — activate in Settings after app opens")
    except Exception as exc:
        _log(f"license warning: status check skipped ({exc})")


def main() -> int:
    parser = argparse.ArgumentParser(description="NovFlow backend sidecar")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    install_dir = _install_dir()
    data_dir = _data_dir()
    port = args.port
    data_dir.mkdir(parents=True, exist_ok=True)
    _init_log(data_dir)
    _log(f"install_dir={install_dir} port={port}")

    if _health_ok(port):
        state = _read_state(data_dir)
        pid = int(state.get("pid") or 0) if state else 0
        if pid and _pid_alive(pid):
            _log(f"reusing healthy backend pid={pid} port={port}")
            _write_launcher_pid(data_dir, os.getpid())
            try:
                while _health_ok(port) and _pid_alive(pid):
                    time.sleep(1.0)
            except KeyboardInterrupt:
                pass
            return 0
        _log("port healthy but stale state — cleaning up")
        _terminate_stale_backend(data_dir, install_dir)

    global _JOB_HANDLE, _BACKEND_PROC
    _JOB_HANDLE = _create_kill_on_close_job()

    def _on_exit() -> None:
        _shutdown(install_dir, data_dir)

    atexit.register(_on_exit)

    def _signal_handler(signum: int, _frame: object) -> None:
        _shutdown(install_dir, data_dir)
        raise SystemExit(128 + signum)

    for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
        if sig is not None:
            try:
                signal.signal(sig, _signal_handler)
            except (OSError, ValueError):
                pass
    if sys.platform == "win32" and hasattr(signal, "SIGBREAK"):
        try:
            signal.signal(signal.SIGBREAK, _signal_handler)
        except (OSError, ValueError):
            pass

    _remove_runtime_files(data_dir)

    try:
        proc = _start_server(install_dir, data_dir, port)
    except FileNotFoundError as exc:
        _log(f"start failed: {exc}")
        print(str(exc), file=sys.stderr)
        return 1

    _assign_process_to_job(_JOB_HANDLE, proc)
    _BACKEND_PROC = proc
    _log(f"backend started pid={proc.pid} port={port}")

    if not _wait_for_health(port, proc):
        exit_code = proc.poll()
        _log(f"health check failed exit_code={exit_code}")
        try:
            log_path = _backend_log_path(data_dir)
            if log_path.is_file():
                tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-8:]
                if tail:
                    _log("backend.log tail:")
                    for line in tail:
                        _log(f"  {line}")
        except OSError:
            pass
        _shutdown(install_dir, data_dir)
        return 1

    _write_state(data_dir, port, proc.pid)
    _write_launcher_pid(data_dir, os.getpid())
    _log("backend healthy")
    _log_license_status(install_dir)

    try:
        proc.wait()
    except KeyboardInterrupt:
        pass
    _shutdown(install_dir, data_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
