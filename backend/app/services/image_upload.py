"""用户上传图片：校验、MinIO 持久化，与 AI 生成共用 object_key 流程。"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.models import Book, Chapter, ChapterIllustration, Character, User
from app.services.image_gen import (
    _image_record,
    _new_object_key,
    active_portrait_object_key,
)
from app.services.storage import storage

UPLOAD_PROMPT = "用户上传"
MAX_UPLOAD_BYTES = 15 * 1024 * 1024

_ALLOWED_EXT = frozenset({"png", "jpg", "jpeg", "webp", "gif"})
_CONTENT_TYPE_EXT: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}


class ImageUploadError(ValueError):
    pass


def _ext_from_filename(filename: str) -> str | None:
    m = re.search(r"\.([a-zA-Z0-9]+)$", (filename or "").strip())
    if not m:
        return None
    ext = m.group(1).lower()
    if ext == "jpeg":
        return "jpg"
    return ext if ext in _ALLOWED_EXT else None


def validate_image_upload(
    file_bytes: bytes,
    filename: str,
    content_type: str | None,
) -> tuple[str, str]:
    if not file_bytes:
        raise ImageUploadError("文件为空")
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise ImageUploadError("图片不能超过 15MB")

    ct = (content_type or "").split(";")[0].strip().lower()
    ext = _CONTENT_TYPE_EXT.get(ct) or _ext_from_filename(filename)
    if not ext:
        raise ImageUploadError("仅支持 PNG、JPEG、WebP、GIF 格式")

    resolved_ct = ct if ct in _CONTENT_TYPE_EXT else f"image/{'jpeg' if ext == 'jpg' else ext}"
    return ext, resolved_ct


def upload_book_cover(
    db: Session,
    user: User,
    book: Book,
    file_bytes: bytes,
    filename: str,
    content_type: str | None,
) -> dict[str, Any]:
    del user  # 上传不依赖即梦 Key
    ext, resolved_ct = validate_image_upload(file_bytes, filename, content_type)
    object_key = _new_object_key(book.id, "cover", ext)
    storage.put_bytes(object_key, file_bytes, content_type=resolved_ct)
    book.cover_image_key = object_key
    db.commit()
    db.refresh(book)
    return _image_record(object_key, UPLOAD_PROMPT, "cover")


def upload_character_image(
    db: Session,
    book: Book,
    character: Character,
    file_bytes: bytes,
    filename: str,
    content_type: str | None,
) -> dict[str, Any]:
    ext, resolved_ct = validate_image_upload(file_bytes, filename, content_type)
    object_key = _new_object_key(book.id, "character", ext)
    storage.put_bytes(object_key, file_bytes, content_type=resolved_ct)
    images = list(character.images_json or [])
    rec = _image_record(object_key, UPLOAD_PROMPT, "character", character_id=character.id)
    images.append(rec)
    character.images_json = images
    arc = dict(character.arc_json or {})
    if not arc.get("active_portrait_object_key"):
        arc["active_portrait_object_key"] = object_key
        character.arc_json = arc
    db.commit()
    db.refresh(character)
    rec["id"] = len(images)
    rec["is_active"] = active_portrait_object_key(character) == object_key
    return rec


def upload_chapter_illustration(
    db: Session,
    book: Book,
    chapter: Chapter,
    file_bytes: bytes,
    filename: str,
    content_type: str | None,
) -> dict[str, Any]:
    ext, resolved_ct = validate_image_upload(file_bytes, filename, content_type)
    object_key = _new_object_key(book.id, "illustration", ext)
    storage.put_bytes(object_key, file_bytes, content_type=resolved_ct)
    ill = ChapterIllustration(
        chapter_id=chapter.id,
        object_key=object_key,
        prompt=UPLOAD_PROMPT,
        parent_id=None,
    )
    db.add(ill)
    db.commit()
    db.refresh(ill)
    return _image_record(object_key, UPLOAD_PROMPT, "illustration", id=ill.id)
