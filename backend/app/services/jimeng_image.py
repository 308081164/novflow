"""火山引擎即梦 / Seedream 图像生成 API 客户端。"""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# 按开通率与稳定性排序；测试连接时会依次尝试
SEEDREAM_MODEL_CANDIDATES: tuple[str, ...] = (
    "doubao-seedream-4-0-250828",
    "doubao-seedream-4-5-251128",
    "doubao-seedream-5-0-260128",
)

DEFAULT_SEEDREAM_MODEL = SEEDREAM_MODEL_CANDIDATES[0]


class JimengError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _normalize_base_url(base_url: str) -> str:
    url = (base_url or settings.jimeng_base_url).strip().rstrip("/")
    if not url:
        url = settings.jimeng_base_url
    return url


def _extract_model_from_message(message: str) -> str | None:
    m = re.search(r"model\s+(\S+)", message, re.I)
    return m.group(1).rstrip(".") if m else None


def _format_api_error(status_code: int, detail: str) -> str:
    """将火山方舟 JSON 错误转为可操作的中文提示。"""
    try:
        payload = json.loads(detail)
    except json.JSONDecodeError:
        return f"即梦 API 错误 ({status_code}): {detail[:400]}"

    err = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(err, dict):
        return f"即梦 API 错误 ({status_code}): {detail[:400]}"

    code = str(err.get("code") or "")
    message = str(err.get("message") or "")
    model_id = _extract_model_from_message(message) or "所选模型"

    if code == "ModelNotOpen" or "has not activated the model" in message:
        return (
            f"账号尚未开通模型「{model_id}」。"
            "请登录火山方舟控制台 → 模型广场，搜索 Seedream 并开通对应模型；"
            "或在下方「模型 ID」改用已开通的 ID（如 doubao-seedream-4-0-250828）。"
            "开通后点击「测试连接」会自动尝试多个常见模型。"
        )
    if code == "InvalidEndpointOrModel" or "model" in message.lower() and "not found" in message.lower():
        return f"模型 ID 无效或未开通：{model_id}。请在模型广场复制完整模型名称后填入设置。"
    if "invalid url" in message.lower() or "parameter `image`" in message.lower():
        return (
            "参考图格式无效，无法用于多轮调整。"
            "请确认原图仍存在于存储中，或重新生成一张后再调整。"
        )
    if "sensitive information" in message.lower() or "敏感" in message:
        return (
            "即梦内容安全审核未通过：原文或提示词可能含不适宜生图的描写。"
            "系统会自动尝试转为含蓄的场景描述后重试；若仍失败，请换一段更侧重环境/动作的选段。"
        )
    if message:
        return f"即梦 API 错误 ({status_code}): {message}"
    return f"即梦 API 错误 ({status_code}): {detail[:400]}"


def _is_model_not_open_error(exc: JimengError) -> bool:
    text = str(exc)
    return "ModelNotOpen" in text or "尚未开通模型" in text or "has not activated the model" in text


def _detect_image_mime(img_bytes: bytes) -> str:
    if img_bytes[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if img_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if len(img_bytes) >= 12 and img_bytes[:4] == b"RIFF" and img_bytes[8:12] == b"WEBP":
        return "webp"
    return "png"


def _encode_reference_image(img_bytes: bytes) -> str:
    """即梦 API 要求参考图为 URL 或 data:image/{fmt};base64,... 格式。"""
    mime = _detect_image_mime(img_bytes)
    b64 = base64.b64encode(img_bytes).decode("ascii")
    return f"data:image/{mime};base64,{b64}"


async def generate_image(
    api_key: str,
    prompt: str,
    *,
    base_url: str | None = None,
    model: str | None = None,
    size: str | None = None,
    reference_images: list[bytes] | None = None,
    watermark: bool = False,
) -> bytes:
    """调用 Seedream 文生图 / 参考图生图，返回图片二进制。"""
    key = (api_key or "").strip()
    if not key:
        raise JimengError("未配置即梦 API Key")

    url = f"{_normalize_base_url(base_url or '')}/images/generations"
    resolved_model = (model or settings.jimeng_model).strip() or DEFAULT_SEEDREAM_MODEL
    body: dict[str, Any] = {
        "model": resolved_model,
        "prompt": prompt.strip(),
        "size": (size or settings.jimeng_default_size).strip() or "2K",
        "response_format": "url",
        "watermark": watermark,
        "sequential_image_generation": "disabled",
    }

    if reference_images:
        encoded = [_encode_reference_image(img) for img in reference_images[:14]]
        body["image"] = encoded[0] if len(encoded) == 1 else encoded

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(url, headers=headers, json=body)
        if resp.status_code >= 400:
            logger.warning("jimeng API error %s: %s", resp.status_code, resp.text[:600])
            raise JimengError(_format_api_error(resp.status_code, resp.text), resp.status_code)

        data = resp.json()
        items = data.get("data") or []
        if not items:
            raise JimengError("即梦 API 未返回图片数据")

        first = items[0]
        if first.get("b64_json"):
            return base64.b64decode(first["b64_json"])

        image_url = first.get("url")
        if not image_url:
            raise JimengError("即梦 API 响应缺少图片 URL")

        img_resp = await client.get(image_url)
        if img_resp.status_code >= 400:
            raise JimengError(f"下载生成图片失败 ({img_resp.status_code})")
        return img_resp.content


async def test_connection(
    api_key: str,
    *,
    base_url: str | None = None,
    model: str | None = None,
) -> dict[str, str]:
    """连通性测试：验证 Key 与端点；若指定模型未开通则自动尝试其他 Seedream 模型。"""
    preferred = (model or settings.jimeng_model or DEFAULT_SEEDREAM_MODEL).strip()
    candidates: list[str] = []
    for m in [preferred, *SEEDREAM_MODEL_CANDIDATES]:
        if m and m not in candidates:
            candidates.append(m)

    last_err: JimengError | None = None
    for candidate in candidates:
        try:
            await generate_image(
                api_key,
                "a simple red circle on white background, minimal test",
                base_url=base_url,
                model=candidate,
                size="2K",
                watermark=False,
            )
            if candidate != preferred:
                return {
                    "status": "ok",
                    "message": (
                        f"连接成功。您填写的模型「{preferred}」未开通，"
                        f"已用「{candidate}」验证通过；请保存设置或改用该模型 ID。"
                    ),
                    "model": candidate,
                    "requested_model": preferred,
                }
            return {
                "status": "ok",
                "message": f"即梦 API 连接成功（模型: {candidate}）",
                "model": candidate,
            }
        except JimengError as exc:
            last_err = exc
            if _is_model_not_open_error(exc):
                logger.info("jimeng test: model %s not open, trying next", candidate)
                continue
            raise

    if last_err:
        raise last_err
    raise JimengError("即梦 API 测试失败：未找到可用模型")
