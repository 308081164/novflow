from __future__ import annotations

from app.models import Chapter
from app.services.storage import storage


def get_content(chapter: Chapter) -> str:
    """读取章节正文：MinIO 优先，未配置或对象不存在时回退 DB TEXT。"""
    if storage.enabled:
        obj = storage.get_chapter(chapter.book_id, chapter.chapter_no)
        if obj is not None:
            return obj
    return chapter.content or ""


def set_content(chapter: Chapter, content: str) -> None:
    """保存章节正文：MinIO 模式下写入对象存储并清空 DB 正文列。"""
    if storage.enabled:
        storage.put_chapter(chapter.book_id, chapter.chapter_no, content)
        chapter.content = ""
    else:
        chapter.content = content


def has_content(chapter: Chapter) -> bool:
    return bool(get_content(chapter).strip())
