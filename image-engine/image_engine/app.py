"""NovFlow 本地生图引擎 — diffusers when model present, else placeholder PNG."""

from __future__ import annotations

import io
import random
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from PIL import Image, ImageDraw, ImageFont

from image_engine import inference
from image_engine.license_gate import license_service, require_dlc_license

app = FastAPI(title="NovFlow 本地生图引擎", version="0.1.0")


class GenerateIn(BaseModel):
    prompt: str = ""
    negative_prompt: str = ""
    width: int = Field(default=512, ge=64, le=2048)
    height: int = Field(default=512, ge=64, le=2048)
    steps: int = 24
    seed: int = -1
    kind: str = "illustration"
    reference_image_base64: str | None = None
    tier_override: str | None = None


def _placeholder_png(width: int, height: int, prompt: str, *, test: bool = False, hint: str = "") -> bytes:
    rng = random.Random(hash((width, height, prompt[:80], test)))
    color = (rng.randint(40, 200), rng.randint(40, 200), rng.randint(40, 200))
    img = Image.new("RGB", (width, height), color)
    draw = ImageDraw.Draw(img)
    st = inference.engine_status()
    if st.get("mode") == "diffusers":
        label = "NovFlow SD1.5"
    elif not st.get("model_ready"):
        label = "占位图（未安装模型）"
    elif not st.get("diffusers"):
        label = "占位图（缺少 diffusers）"
    else:
        label = "NovFlow Stub"
    if test:
        label = "TEST"
    text = f"{label}\n{width}x{height}"
    if hint:
        text += f"\n{hint[:60]}"
    elif not st.get("model_ready"):
        text += "\n请在控制台「模型」页一键下载 Lite 基础模型"
    if prompt:
        text += f"\n{prompt[:40]}"
    draw.rectangle([4, 4, width - 5, height - 5], outline=(255, 255, 255), width=2)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    draw.multiline_text((12, 12), text, fill=(255, 255, 255), font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _generate_png(data: GenerateIn, *, test: bool = False) -> tuple[bytes, str]:
    prompt = (data.prompt or "").strip()
    if inference.model_ready() and inference.diffusers_available():
        png = inference.generate_image(
            prompt,
            negative_prompt=data.negative_prompt or "",
            width=data.width,
            height=data.height,
            steps=data.steps,
            seed=data.seed,
        )
        if png:
            return png, "diffusers"
        err = inference.last_load_error() or "推理失败"
        if test:
            return _placeholder_png(data.width, data.height, prompt, test=True, hint=err), "placeholder"
        return _placeholder_png(data.width, data.height, prompt, hint=err), "placeholder"
    hint = ""
    if not inference.model_ready():
        hint = "未检测到 Lite 模型，请一键下载"
    elif not inference.diffusers_available():
        hint = "引擎未包含 diffusers 运行时"
    return _placeholder_png(data.width, data.height, prompt, test=test, hint=hint), "placeholder"


@app.get("/v1/health")
def health() -> dict[str, Any]:
    st = license_service().status()
    eng = inference.engine_status()
    tier = "lite" if eng.get("model_ready") else "lite-stub"
    model_label = "sd15" if eng.get("mode") == "diffusers" else "stub"
    return {
        "status": "ok",
        "tier": tier,
        "vram_mb": 4096,
        "model": model_label,
        "engine": eng.get("mode", "placeholder"),
        "model_path": eng.get("model_path"),
        "model_ready": eng.get("model_ready"),
        "license": {
            "activated": bool(st.get("activated")),
            "product_id": license_service().profile.product_id,
            "error": st.get("error"),
        },
    }


@app.get("/v1/license/device")
def license_device() -> dict[str, Any]:
    return license_service().device_info()


@app.get("/v1/capabilities")
def capabilities() -> dict[str, Any]:
    eng = inference.engine_status()
    return {
        "resolutions": ["512x768", "512x912", "768x432", "1024x1024"],
        "max_steps": 50,
        "ref_image": True,
        "nsfw_filter": False,
        "inference": eng.get("mode") == "diffusers",
    }


@app.post("/v1/generate", dependencies=[Depends(require_dlc_license)])
def generate(data: GenerateIn) -> Response:
    if not (data.prompt or "").strip():
        raise HTTPException(400, detail={"error": "prompt 不能为空"})
    png, _mode = _generate_png(data)
    return Response(content=png, media_type="image/png")


@app.post("/v1/generate/test", dependencies=[Depends(require_dlc_license)])
def generate_test() -> Response:
    data = GenerateIn(prompt="connectivity test", width=64, height=64, steps=4)
    png, _ = _generate_png(data, test=True)
    return Response(content=png, media_type="image/png")
