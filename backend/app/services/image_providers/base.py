"""ImageProvider 协议、路由与 Jimeng / Local DLC 实现。"""
from __future__ import annotations

import uuid
from typing import Literal, Protocol

from app.config import settings
from app.models import User
from app.services.api_key import has_jimeng_key, resolve_jimeng_config
from app.services.jimeng_image import JimengError, generate_image
from app.services.storage import storage

ImageKind = Literal["cover", "character", "illustration"]
ImageBackend = Literal["jimeng", "local_dlc", "off"]


class ImageEngineError(Exception):
    """本地 Image Engine DLC 错误。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)


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


def resolve_image_backend(user: User | None = None) -> ImageBackend:
    if user and (user.image_backend or "").strip():
        backend = user.image_backend.strip().lower()
        if backend in ("jimeng", "local_dlc", "off"):
            return backend  # type: ignore[return-value]
    return "jimeng"


def has_local_dlc(user: User | None = None) -> bool:
    if resolve_image_backend(user) != "local_dlc":
        return False
    if not user:
        return False
    return user.local_dlc_eula_accepted_at is not None


def has_image_generation(user: User | None = None) -> bool:
    backend = resolve_image_backend(user)
    if backend == "off":
        return False
    if backend == "local_dlc":
        return has_local_dlc(user)
    return has_jimeng_key(user)


def get_image_provider(user: User | None = None, *, kind: ImageKind = "illustration") -> ImageProvider:
    backend = resolve_image_backend(user)
    if backend == "local_dlc":
        from app.services.image_providers.local_dlc import LocalDlcProvider

        return LocalDlcProvider(user, kind=kind)
    return JimengProvider()


def category_for_kind(kind: ImageKind) -> str:
    return {"cover": "covers", "character": "characters", "illustration": "illustrations"}[kind]


def new_object_key(book_id: int, kind: ImageKind, ext: str = "png") -> str:
    cat = category_for_kind(kind)
    return f"images/{book_id}/{cat}/{uuid.uuid4().hex[:16]}.{ext}"


def media_url(object_key: str) -> str:
    return f"/api/v1/media/{object_key}"


def size_for_kind(kind: ImageKind, user: User | None = None) -> str | None:
    backend = resolve_image_backend(user)
    if backend == "local_dlc":
        from app.services.image_providers.local_dlc import _KIND_DIMENSIONS

        w, h = _KIND_DIMENSIONS.get(kind, (768, 432))
        return f"{w}x{h}"
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
    prov = provider or get_image_provider(user, kind=kind)
    refs: list[bytes] = []
    if reference_keys:
        for key in reference_keys[:14]:
            data = storage.get_bytes(key)
            if not data:
                err_cls = ImageEngineError if resolve_image_backend(user) == "local_dlc" else JimengError
                raise err_cls(f"参考图不存在或无法读取：{key}")
            refs.append(data)
    image_bytes = await prov.generate(
        user,
        prompt,
        reference_images=refs or None,
        size=size_for_kind(kind, user),
    )
    object_key = new_object_key(book_id, kind)
    storage.put_bytes(object_key, image_bytes, content_type="image/png")
    return object_key, image_bytes
