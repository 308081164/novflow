"""ImageProvider 协议与 Jimeng 实现。"""
from __future__ import annotations

import uuid
from typing import Literal, Protocol

from app.config import settings
from app.models import User
from app.services.api_key import resolve_jimeng_config
from app.services.jimeng_image import JimengError, generate_image
from app.services.storage import storage

ImageKind = Literal["cover", "character", "illustration"]


class ImageProvider(Protocol):
    async def generate(
        self,
        user: User,
        prompt: str,
        *,
        reference_images: list[bytes] | None = None,
        size: str | None = None,
    ) -> bytes: ...


class JimengProvider:
    """火山方舟即梦 / Seedream 文生图。"""

    async def generate(
        self,
        user: User,
        prompt: str,
        *,
        reference_images: list[bytes] | None = None,
        size: str | None = None,
    ) -> bytes:
        cfg = resolve_jimeng_config(user)
        return await generate_image(
            cfg["api_key"],
            prompt,
            base_url=cfg["base_url"],
            model=cfg["model"],
            size=size or cfg["size"],
            reference_images=reference_images,
        )


_default_provider: JimengProvider | None = None


def get_image_provider() -> JimengProvider:
    global _default_provider
    if _default_provider is None:
        _default_provider = JimengProvider()
    return _default_provider


def category_for_kind(kind: ImageKind) -> str:
    return {"cover": "covers", "character": "characters", "illustration": "illustrations"}[kind]


def new_object_key(book_id: int, kind: ImageKind, ext: str = "png") -> str:
    cat = category_for_kind(kind)
    return f"images/{book_id}/{cat}/{uuid.uuid4().hex[:16]}.{ext}"


def media_url(object_key: str) -> str:
    return f"/api/v1/media/{object_key}"


def size_for_kind(kind: ImageKind) -> str | None:
    if kind == "character":
        return settings.jimeng_character_size
    return None


async def generate_and_store(
    user: User,
    book_id: int,
    kind: ImageKind,
    prompt: str,
    reference_keys: list[str] | None = None,
    *,
    provider: ImageProvider | None = None,
) -> tuple[str, bytes]:
    """调用 provider 生成图片并写入 storage，返回 (object_key, bytes)。"""
    prov = provider or get_image_provider()
    refs: list[bytes] = []
    if reference_keys:
        for key in reference_keys[:14]:
            data = storage.get_bytes(key)
            if not data:
                raise JimengError(f"参考图不存在或无法读取：{key}")
            refs.append(data)
    image_bytes = await prov.generate(
        user,
        prompt,
        reference_images=refs or None,
        size=size_for_kind(kind),
    )
    object_key = new_object_key(book_id, kind)
    storage.put_bytes(object_key, image_bytes, content_type="image/png")
    return object_key, image_bytes
