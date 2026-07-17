"""Local model / resource path management for Image Engine."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from image_engine.settings_store import load_settings


WEIGHT_SUFFIXES = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".onnx")


@dataclass
class ModelEntry:
    name: str
    path: Path
    tier: str
    size_mb: float

    def display(self) -> str:
        return f"[{self.tier}] {self.name}  ({self.size_mb:.1f} MB)"


def models_root() -> Path:
    cfg = load_settings()
    root = Path(str(cfg.get("models_dir") or "")).expanduser()
    if not root.is_absolute():
        root = root.resolve()
    return root


def ensure_models_dir() -> Path:
    root = models_root()
    for tier in ("lite", "standard", "pro"):
        (root / tier).mkdir(parents=True, exist_ok=True)
    return root


def list_models() -> list[ModelEntry]:
    root = ensure_models_dir()
    entries: list[ModelEntry] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in WEIGHT_SUFFIXES:
            continue
        try:
            rel = path.relative_to(root)
            parts = rel.parts
            tier = parts[0] if len(parts) > 1 and parts[0] in ("lite", "standard", "pro") else "other"
        except ValueError:
            tier = "other"
        size_mb = path.stat().st_size / (1024 * 1024)
        entries.append(ModelEntry(name=path.name, path=path, tier=tier, size_mb=size_mb))
    return entries


def import_weight(src: Path, tier: str = "lite") -> Path:
    """Copy a weight file into models/<tier>/."""
    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(f"文件不存在：{src}")
    if src.suffix.lower() not in WEIGHT_SUFFIXES:
        raise ValueError(f"不支持的文件类型：{src.suffix}（请导入 .safetensors 等权重）")
    tier = tier if tier in ("lite", "standard", "pro") else "lite"
    dest_dir = ensure_models_dir() / tier
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if dest.resolve() == src.resolve():
        return dest
    shutil.copy2(src, dest)
    return dest


def import_folder(src_dir: Path, tier: str = "lite") -> list[Path]:
    """Copy all weight files from a folder into models/<tier>/."""
    src_dir = Path(src_dir)
    if not src_dir.is_dir():
        raise NotADirectoryError(f"目录不存在：{src_dir}")
    imported: list[Path] = []
    for path in sorted(src_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in WEIGHT_SUFFIXES:
            imported.append(import_weight(path, tier=tier))
    return imported


def set_models_dir(path: Path) -> Path:
    from image_engine.settings_store import save_settings

    path = Path(path).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    save_settings({"models_dir": str(path)})
    return path


def find_lite_checkpoint() -> Path | None:
    """Return active Lite checkpoint if present."""
    from image_engine.settings_store import LITE_DEFAULT_FILENAME, load_settings

    cfg = load_settings()
    preferred = str(cfg.get("active_lite_model") or LITE_DEFAULT_FILENAME)
    root = ensure_models_dir()
    candidates = [
        root / "lite" / preferred,
        root / "lite" / LITE_DEFAULT_FILENAME,
    ]
    for path in candidates:
        if path.is_file() and path.stat().st_size > 1024 * 1024:
            return path
    # Any large safetensors in lite/
    lite_dir = root / "lite"
    if lite_dir.is_dir():
        for path in sorted(lite_dir.glob("*.safetensors")):
            if path.stat().st_size > 1024 * 1024:
                return path
    return None


def set_active_lite_model(filename: str) -> None:
    from image_engine.settings_store import save_settings

    save_settings({"active_lite_model": filename})
