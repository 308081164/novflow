"""NovFlow 本地生图引擎 HTTP 客户端。"""
from __future__ import annotations

import base64
import re
from typing import Any

import httpx

from app.models import User
from app.services.image_providers.base import ImageEngineError, ImageKind

DEFAULT_BASE_URL = "http://127.0.0.1:17860/v1"
DEFAULT_NEGATIVE = "low quality, blurry, watermark, text"

# Lite 档默认像素（与 LOCAL_IMAGE_DLC.md §6.3 一致）
_KIND_DIMENSIONS: dict[ImageKind, tuple[int, int]] = {
    "cover": (512, 768),
    "character": (512, 912),
    "illustration": (768, 432),
}


def resolve_local_dlc_base_url(user: User | None) -> str:
    if user and (user.local_dlc_base_url or "").strip():
        return user.local_dlc_base_url.strip().rstrip("/")
    return DEFAULT_BASE_URL


def parse_size(size: str | None, kind: ImageKind = "illustration") -> tuple[int, int]:
    if size:
        m = re.match(r"^(\d+)\s*[x×]\s*(\d+)$", size.strip(), re.I)
        if m:
            return int(m.group(1)), int(m.group(2))
    return _KIND_DIMENSIONS.get(kind, (768, 432))


class LocalDlcProvider:
    """转发至用户本机 NovFlow 本地生图引擎服务。"""

    def __init__(self, user: User | None = None, *, kind: ImageKind = "illustration") -> None:
        self._user = user
        self._base_url = resolve_local_dlc_base_url(user)
        self._kind = kind
        tier = "auto"
        if user and (user.local_dlc_tier or "").strip():
            tier = user.local_dlc_tier.strip()
        self._tier = tier

    @property
    def base_url(self) -> str:
        return self._base_url

    async def health(self) -> dict[str, Any]:
        url = f"{self._base_url}/health"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.json()
        except httpx.ConnectError:
            raise ImageEngineError(
                "无法连接本地生图引擎。请确认 NovFlow 本地生图引擎已启动（默认 127.0.0.1:17860）。"
            ) from None
        except httpx.HTTPStatusError as exc:
            raise ImageEngineError(f"本地引擎健康检查失败（HTTP {exc.response.status_code}）") from exc
        except Exception as exc:
            raise ImageEngineError(f"本地引擎健康检查失败：{exc}") from exc

    async def generate(
        self,
        user: User,
        prompt: str,
        *,
        reference_images: list[bytes] | None = None,
        size: str | None = None,
    ) -> bytes:
        width, height = parse_size(size, self._kind)
        ref_b64: str | None = None
        if reference_images:
            ref_b64 = base64.b64encode(reference_images[0]).decode("ascii")

        payload: dict[str, Any] = {
            "prompt": prompt,
            "negative_prompt": DEFAULT_NEGATIVE,
            "width": width,
            "height": height,
            "steps": 24,
            "seed": -1,
            "kind": self._kind,
            "reference_image_base64": ref_b64,
        }
        if self._tier and self._tier != "auto":
            payload["tier_override"] = self._tier

        url = f"{self._base_url}/generate"
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code >= 400:
                    detail = resp.text[:400]
                    try:
                        err_json = resp.json()
                        detail = str(err_json.get("error") or err_json.get("detail") or detail)
                    except Exception:
                        pass
                    if resp.status_code == 507 or "oom" in detail.lower() or "显存" in detail:
                        raise ImageEngineError(f"本地引擎显存不足：{detail}")
                    raise ImageEngineError(f"本地引擎生成失败：{detail}")
                ct = (resp.headers.get("content-type") or "").lower()
                if "application/json" in ct:
                    data = resp.json()
                    raise ImageEngineError(str(data.get("error") or data))
                return resp.content
        except ImageEngineError:
            raise
        except httpx.ConnectError:
            raise ImageEngineError(
                "本地生图引擎未运行。请在 Image Engine 控制台启动服务，或在设置页测试连接。"
            ) from None
        except httpx.TimeoutException:
            raise ImageEngineError("本地引擎生成超时，请稍后重试或降低分辨率档位。") from None
        except Exception as exc:
            raise ImageEngineError(f"本地引擎请求失败：{exc}") from exc

    async def test_generate(self) -> bytes:
        url = f"{self._base_url}/generate/test"
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url)
                if resp.status_code >= 400:
                    raise ImageEngineError(f"测试生成失败（HTTP {resp.status_code}）")
                return resp.content
        except ImageEngineError:
            raise
        except httpx.ConnectError:
            raise ImageEngineError("无法连接本地生图引擎，请确认 DLC 已启动。") from None
        except Exception as exc:
            raise ImageEngineError(f"测试生成失败：{exc}") from exc
