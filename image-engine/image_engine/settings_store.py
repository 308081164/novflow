"""Persistent settings for Image Engine console (port, models path)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 17860

LITE_DEFAULT_FILENAME = "v1-5-pruned-emaonly.safetensors"


def install_root() -> Path:
    """Application install directory (parent of image_engine package when packaged)."""
    home = os.environ.get("NOVFLOW_IMAGE_ENGINE_HOME", "").strip()
    if home:
        return Path(home).resolve()
    install = os.environ.get("NOVFLOW_INSTALL_DIR", "").strip()
    if install:
        return Path(install).resolve()
    # Dev / python -m: parent of image_engine package
    return Path(__file__).resolve().parents[1]


def legacy_programdata_models_dir() -> Path | None:
    program_data = os.environ.get("PROGRAMDATA") or os.environ.get("ProgramData")
    if not program_data:
        return None
    return Path(program_data) / "NovFlowImageEngine" / "models"


def default_models_dir() -> Path:
    """Models live under install directory: {install_root}/models."""
    return install_root() / "models"


def data_root() -> Path:
    env = os.environ.get("NOVFLOW_DATA_DIR", "").strip()
    if env:
        return Path(env).resolve()
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return (base / "NovFlow" / "data").resolve()


def config_path() -> Path:
    return data_root() / "config" / "image-engine.json"


def log_dir() -> Path:
    return data_root() / "logs"


def _dir_has_weights(path: Path) -> bool:
    if not path.is_dir():
        return False
    suffixes = {".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".onnx"}
    for p in path.rglob("*"):
        if p.is_file() and p.suffix.lower() in suffixes:
            return True
    return False


def maybe_migrate_models_dir(cfg: dict[str, Any]) -> dict[str, Any]:
    """If old ProgramData path has weights and new install path is empty, offer migration once."""
    if cfg.get("models_migrated_from_programdata"):
        return cfg

    new_dir = Path(str(cfg.get("models_dir") or default_models_dir()))
    legacy = legacy_programdata_models_dir()
    if legacy is None or not _dir_has_weights(legacy):
        return cfg

    new_has = _dir_has_weights(new_dir)
    if new_has:
        return cfg

    # Flag for GUI to prompt; also copy lite weights automatically on first load
    cfg["models_migration_pending"] = True
    cfg["models_migration_legacy"] = str(legacy)
    return cfg


def apply_models_migration(*, move: bool = False) -> Path:
    """Copy or move weights from legacy ProgramData to install models dir."""
    cfg = load_settings()
    legacy = Path(str(cfg.get("models_migration_legacy") or ""))
    if not legacy.is_dir():
        legacy = legacy_programdata_models_dir() or default_models_dir()
    dest = default_models_dir()
    dest.mkdir(parents=True, exist_ok=True)

    import shutil

    for src in legacy.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(legacy)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if move:
            shutil.move(str(src), str(target))
        else:
            shutil.copy2(src, target)

    save_settings(
        {
            "models_dir": str(dest),
            "models_migrated_from_programdata": True,
            "models_migration_pending": False,
        }
    )
    return dest


def dismiss_models_migration() -> None:
    save_settings({"models_migration_pending": False, "models_migrated_from_programdata": True})


def ensure_stdio() -> None:
    """pythonw has no console: sys.stdout/stderr are None; uvicorn logging needs isatty()."""
    if sys.stdout is not None and sys.stderr is not None:
        return

    log_path = log_dir() / "image-engine.log"
    stream = None

    def _open_log():
        nonlocal stream
        if stream is not None:
            return stream
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            stream = open(log_path, "a", encoding="utf-8", buffering=1)
        except OSError:
            stream = open(os.devnull, "w", encoding="utf-8")
        return stream

    if sys.stdout is None:
        sys.stdout = _open_log()
    if sys.stderr is None:
        sys.stderr = _open_log()


def load_settings() -> dict[str, Any]:
    path = config_path()
    data: dict[str, Any] = {
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
        "models_dir": str(default_models_dir()),
        "active_lite_model": LITE_DEFAULT_FILENAME,
    }
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data.update(raw)
        except (OSError, json.JSONDecodeError):
            pass

    # Migrate away from persisted ProgramData default
    models_dir = Path(str(data.get("models_dir") or ""))
    legacy = legacy_programdata_models_dir()
    if legacy and models_dir == legacy:
        data["models_dir"] = str(default_models_dir())

    data = maybe_migrate_models_dir(data)

    env_port = os.environ.get("NOVFLOW_IMAGE_ENGINE_PORT", "").strip()
    if env_port.isdigit():
        data["port"] = int(env_port)
    env_host = os.environ.get("NOVFLOW_IMAGE_ENGINE_HOST", "").strip()
    if env_host:
        data["host"] = env_host
    env_models = os.environ.get("NOVFLOW_IMAGE_ENGINE_MODELS", "").strip()
    if env_models:
        data["models_dir"] = env_models
    return data


def save_settings(data: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_settings()
    current.update(data)
    out = {
        "host": str(current.get("host") or DEFAULT_HOST),
        "port": int(current.get("port") or DEFAULT_PORT),
        "models_dir": str(current.get("models_dir") or default_models_dir()),
        "active_lite_model": str(current.get("active_lite_model") or LITE_DEFAULT_FILENAME),
    }
    if current.get("models_migrated_from_programdata"):
        out["models_migrated_from_programdata"] = True
    if "models_migration_pending" in current:
        out["models_migration_pending"] = bool(current.get("models_migration_pending"))
    if current.get("models_migration_legacy"):
        out["models_migration_legacy"] = str(current["models_migration_legacy"])
    if current.get("first_run_lite_prompt_dismissed"):
        out["first_run_lite_prompt_dismissed"] = True
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_to_environ(data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Push settings into process env for the HTTP server."""
    cfg = data or load_settings()
    os.environ["NOVFLOW_IMAGE_ENGINE_HOST"] = str(cfg.get("host") or DEFAULT_HOST)
    os.environ["NOVFLOW_IMAGE_ENGINE_PORT"] = str(int(cfg.get("port") or DEFAULT_PORT))
    os.environ["NOVFLOW_IMAGE_ENGINE_MODELS"] = str(cfg.get("models_dir") or default_models_dir())
    os.environ.setdefault("NOVFLOW_INSTALL_DIR", str(install_root()))
    return cfg
