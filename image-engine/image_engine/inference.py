"""Lazy SD 1.5 inference via diffusers when model weights are present."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from image_engine.models_mgr import find_lite_checkpoint
from image_engine.settings_store import load_settings

_pipeline: Any = None
_pipeline_lock = threading.Lock()
_last_error: str | None = None


def diffusers_available() -> bool:
    try:
        import diffusers  # noqa: F401
        import torch  # noqa: F401

        return True
    except ImportError:
        return False


def model_ready() -> bool:
    ckpt = find_lite_checkpoint()
    return ckpt is not None and ckpt.is_file() and ckpt.stat().st_size > 10 * 1024 * 1024


def last_load_error() -> str | None:
    return _last_error


def _load_pipeline():
    global _pipeline, _last_error
    with _pipeline_lock:
        if _pipeline is not None:
            return _pipeline
        ckpt = find_lite_checkpoint()
        if ckpt is None:
            _last_error = "未找到 Lite 模型权重"
            return None
        try:
            import torch
            from diffusers import StableDiffusionPipeline

            device = "cuda" if torch.cuda.is_available() else "cpu"
            dtype = torch.float16 if device == "cuda" else torch.float32
            pipe = StableDiffusionPipeline.from_single_file(
                str(ckpt),
                torch_dtype=dtype,
                safety_checker=None,
            )
            pipe = pipe.to(device)
            if device == "cuda":
                try:
                    pipe.enable_attention_slicing()
                except Exception:
                    pass
                try:
                    pipe.enable_vae_slicing()
                except Exception:
                    pass
            _pipeline = pipe
            _last_error = None
            return _pipeline
        except Exception as exc:
            _last_error = str(exc)
            _pipeline = None
            return None


def unload_pipeline() -> None:
    global _pipeline, _last_error
    with _pipeline_lock:
        _pipeline = None
        _last_error = None


def generate_image(
    prompt: str,
    *,
    negative_prompt: str = "",
    width: int = 512,
    height: int = 512,
    steps: int = 24,
    seed: int = -1,
) -> bytes | None:
    """Return PNG bytes or None if inference unavailable."""
    if not model_ready():
        return None
    if not diffusers_available():
        _last_error = "未安装 torch/diffusers，请重新安装引擎或使用占位模式"
        return None

    pipe = _load_pipeline()
    if pipe is None:
        return None

    import io
    import random

    import torch

    gen = None
    if seed >= 0:
        gen = torch.Generator(device=pipe.device).manual_seed(seed)
    else:
        gen = torch.Generator(device=pipe.device).manual_seed(random.randint(0, 2**31 - 1))

    neg = negative_prompt or "low quality, blurry, watermark, text, deformed"
    with torch.inference_mode():
        result = pipe(
            prompt=prompt,
            negative_prompt=neg,
            width=width,
            height=height,
            num_inference_steps=min(max(steps, 1), 50),
            generator=gen,
        )
    img = result.images[0]
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def engine_status() -> dict[str, Any]:
    ckpt = find_lite_checkpoint()
    cfg = load_settings()
    ready = model_ready()
    has_diffusers = diffusers_available()
    mode = "diffusers" if ready and has_diffusers else "placeholder"
    return {
        "mode": mode,
        "model_path": str(ckpt) if ckpt else None,
        "model_name": cfg.get("active_lite_model"),
        "diffusers": has_diffusers,
        "model_ready": ready,
        "load_error": _last_error,
    }
