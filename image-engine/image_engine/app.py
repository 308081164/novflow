"""NovFlow Image Engine stub — placeholder PNG for integration testing."""

from __future__ import annotations

import io
import random
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from PIL import Image, ImageDraw, ImageFont

from image_engine.license_gate import license_service, require_dlc_license

app = FastAPI(title="NovFlow Image Engine (Stub)", version="0.1.0-stub")

HOST = "127.0.0.1"
PORT = 17860


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


def _placeholder_png(width: int, height: int, prompt: str, *, test: bool = False) -> bytes:
    rng = random.Random(hash((width, height, prompt[:80], test)))
    color = (rng.randint(40, 200), rng.randint(40, 200), rng.randint(40, 200))
    img = Image.new("RGB", (width, height), color)
    draw = ImageDraw.Draw(img)
    label = "NovFlow Stub" if not test else "TEST"
    text = f"{label}\n{width}x{height}"
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


@app.get("/v1/health")
def health() -> dict[str, Any]:
    st = license_service().status()
    return {
        "status": "ok",
        "tier": "lite",
        "vram_mb": 4096,
        "model": "stub",
        "engine": "placeholder",
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
    return {
        "resolutions": ["512x768", "512x912", "768x432", "1024x1024"],
        "max_steps": 50,
        "ref_image": True,
        "nsfw_filter": False,
    }


@app.post("/v1/generate", dependencies=[Depends(require_dlc_license)])
def generate(data: GenerateIn) -> Response:
    if not (data.prompt or "").strip():
        raise HTTPException(400, detail={"error": "prompt 不能为空"})
    png = _placeholder_png(data.width, data.height, data.prompt.strip())
    return Response(content=png, media_type="image/png")


@app.post("/v1/generate/test", dependencies=[Depends(require_dlc_license)])
def generate_test() -> Response:
    png = _placeholder_png(64, 64, "test", test=True)
    return Response(content=png, media_type="image/png")
