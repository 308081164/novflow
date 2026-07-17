"""One-click model download from preset catalog (ModelScope / HF mirrors)."""

from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from image_engine.models_mgr import ensure_models_dir

ProgressCallback = Callable[[int, int, str], None]


@dataclass
class CatalogModel:
    id: str
    name: str
    tier: str
    filename: str
    size_bytes: int
    size_display: str
    description: str
    urls: list[str]
    sha256: str | None = None


@dataclass
class DownloadState:
    cancelled: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    error: str | None = None
    dest: Path | None = None


_active_download = DownloadState()


def _catalog_path() -> Path:
    return Path(__file__).resolve().parent / "model_catalog.json"


def load_catalog() -> list[CatalogModel]:
    path = _catalog_path()
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("models") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    out: list[CatalogModel] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out.append(
            CatalogModel(
                id=str(item.get("id", "")),
                name=str(item.get("name", "")),
                tier=str(item.get("tier", "lite")),
                filename=str(item.get("filename", "")),
                size_bytes=int(item.get("size_bytes") or 0),
                size_display=str(item.get("size_display", "")),
                description=str(item.get("description", "")),
                urls=[str(u) for u in (item.get("urls") or []) if u],
                sha256=(str(item["sha256"]) if item.get("sha256") else None),
            )
        )
    return out


def get_catalog_model(model_id: str) -> CatalogModel | None:
    for m in load_catalog():
        if m.id == model_id:
            return m
    return None


def is_downloading() -> bool:
    t = _active_download.thread
    return t is not None and t.is_alive()


def cancel_download() -> None:
    _active_download.cancelled.set()


def _verify_sha256(path: Path, expected: str) -> bool:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest().lower() == expected.lower()


def _download_url(
    url: str,
    dest: Path,
    *,
    total_hint: int,
    on_progress: ProgressCallback | None,
    cancelled: threading.Event,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "NovFlow-ImageEngine/0.1"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or total_hint or 0)
        done = 0
        with tmp.open("wb") as out:
            while True:
                if cancelled.is_set():
                    raise InterruptedError("下载已取消")
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done, total, dest.name)
    if cancelled.is_set():
        tmp.unlink(missing_ok=True)
        raise InterruptedError("下载已取消")
    tmp.replace(dest)


def download_model(
    model_id: str,
    *,
    on_progress: ProgressCallback | None = None,
    on_done: Callable[[Path | None, str | None], None] | None = None,
) -> None:
    """Start background download; raises if one is already running."""
    if is_downloading():
        raise RuntimeError("已有下载任务进行中")

    model = get_catalog_model(model_id)
    if model is None:
        raise ValueError(f"未知模型：{model_id}")
    if not model.urls:
        raise ValueError(f"模型 {model.name} 无可用下载地址")

    dest_dir = ensure_models_dir() / model.tier
    dest = dest_dir / model.filename
    if dest.is_file() and dest.stat().st_size > 1024 * 1024:
        if on_done:
            on_done(dest, None)
        return

    state = DownloadState()
    _active_download.cancelled = state.cancelled
    _active_download.error = None
    _active_download.dest = None

    def _worker() -> None:
        err: str | None = None
        result: Path | None = None
        try:
            last_exc: Exception | None = None
            for url in model.urls:
                try:
                    if on_progress:
                        on_progress(0, model.size_bytes, f"连接 {url[:48]}…")
                    _download_url(
                        url,
                        dest,
                        total_hint=model.size_bytes,
                        on_progress=on_progress,
                        cancelled=state.cancelled,
                    )
                    if model.sha256 and not _verify_sha256(dest, model.sha256):
                        dest.unlink(missing_ok=True)
                        raise ValueError("SHA256 校验失败")
                    result = dest
                    break
                except InterruptedError:
                    raise
                except Exception as exc:
                    last_exc = exc
                    dest.unlink(missing_ok=True)
                    continue
            if result is None:
                err = f"所有镜像均失败：{last_exc}"
        except InterruptedError:
            err = "下载已取消"
        except Exception as exc:
            err = str(exc)
        _active_download.error = err
        _active_download.dest = result
        if on_done:
            on_done(result, err)

    t = threading.Thread(target=_worker, name=f"dl-{model_id}", daemon=True)
    _active_download.thread = t
    t.start()
