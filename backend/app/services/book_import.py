"""从用户上传的文档导入已有书籍设定。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.models import Book, Character, User, Worldview
from app.services.book_import_adapt import MAX_CHARACTER_FILES, safe_adapt
from app.services.card_handlers import apply_card_by_type
from app.services.character_cards import sync_character_card
from app.services.pipeline import create_book_from_template

ALLOWED_SUFFIXES = {".txt", ".md", ".markdown"}


async def _read_upload(file: UploadFile | None) -> str:
    if not file or not file.filename:
        return ""
    suffix = Path(file.filename).suffix.lower()
    if suffix and suffix not in ALLOWED_SUFFIXES:
        raise ValueError(f"不支持的文件格式：{file.filename}，请使用 txt / md")
    raw = await file.read()
    if not raw:
        return ""
    for enc in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
        try:
            return raw.decode(enc).strip()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").strip()


def _name_from_filename(filename: str) -> str:
    stem = Path(filename).stem.strip()
    stem = re.sub(r"[_\-]+角色?(设定|卡)?$", "", stem, flags=re.I)
    stem = re.sub(r"^(角色|character)[_\-]+", "", stem, flags=re.I)
    return stem or "未命名角色"


def _name_from_content(text: str, fallback: str) -> str:
    for line in text.splitlines()[:8]:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(?:#+\s*)?(?:角色名|姓名|名称)[:：]\s*(.+)$", line)
        if m:
            return m.group(1).strip()[:100]
        if len(line) <= 20 and not line.endswith("。"):
            return line[:100]
    return fallback


def _apply_worldview(db: Session, book: Book, text: str) -> None:
    wv = db.query(Worldview).filter(Worldview.book_id == book.id).first()
    if not wv:
        wv = Worldview(book_id=book.id)
        db.add(wv)
    wv.content = text
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    if first_line and not wv.setting:
        wv.setting = first_line[:200]


def _apply_outline(book: Book, text: str, target_chapters: int) -> None:
    book.plot_framework = {
        "source": "import",
        "summary": text[:3000],
        "imported_full": text,
        "total_chapters": target_chapters,
    }


def _apply_outline_adapted(db: Session, book: Book, data: dict, target_chapters: int) -> None:
    plot = data.get("plot") if isinstance(data.get("plot"), dict) else {}
    imported_full = str(data.get("imported_full") or plot.get("summary") or "").strip()
    if plot:
        apply_card_by_type(db, book, "plot", plot)
    outline = data.get("outline") if isinstance(data.get("outline"), dict) else {}
    chapters = outline.get("chapters") if isinstance(outline.get("chapters"), list) else []
    if chapters:
        apply_card_by_type(db, book, "outline", outline)
    pf = dict(book.plot_framework or {})
    pf.setdefault("source", "import")
    if imported_full:
        pf["imported_full"] = imported_full
    if not pf.get("summary") and imported_full:
        pf["summary"] = imported_full[:3000]
    pf.setdefault("total_chapters", target_chapters)
    book.plot_framework = pf


def _apply_character(db: Session, book: Book, filename: str, text: str) -> Character:
    fallback = _name_from_filename(filename)
    name = _name_from_content(text, fallback)
    return sync_character_card(
        db,
        book,
        {
            "type": "character",
            "title": name,
            "data": {
                "name": name,
                "role": "support",
                "summary": text[:500] if len(text) > 500 else "",
                "content": text,
            },
        },
        overwrite=True,
    )


async def create_book_from_import(
    db: Session,
    user: User,
    *,
    title: str,
    genre: str = "",
    premise: str = "",
    target_chapters: int = 300,
    worldview_file: UploadFile | None = None,
    outline_file: UploadFile | None = None,
    writing_prefs_file: UploadFile | None = None,
    conventions_file: UploadFile | None = None,
    character_files: list[UploadFile] | None = None,
    adapt_with_ai: bool = True,
) -> tuple[Book, dict[str, int | bool | str]]:
    book = create_book_from_template(
        db,
        user.id,
        title.strip(),
        premise or "",
        "import",
        genre=genre,
        premise=premise,
        target_chapters=target_chapters,
    )
    book.setup_step = 5

    ctx = {
        "book_title": title.strip(),
        "genre": genre,
        "premise": premise[:500] if premise else "",
        "target_chapters": target_chapters,
    }
    warnings: list[str] = []
    infos: list[str] = []
    ai_adapted = False
    ai_success = 0
    ai_fallback = 0

    def _record(result: Any | None, warn: str | None, info: str | None) -> None:
        nonlocal ai_adapted, ai_success, ai_fallback
        if info:
            infos.append(info)
        if warn:
            warnings.append(warn)
            if result is not None:
                ai_fallback += 1
        elif result is not None:
            ai_adapted = True
            ai_success += 1

    worldview_text = await _read_upload(worldview_file)

    char_files = character_files or []
    if len(char_files) > MAX_CHARACTER_FILES:
        warnings.append(f"角色文件超过 {MAX_CHARACTER_FILES} 个，仅处理前 {MAX_CHARACTER_FILES} 个")
        char_files = char_files[:MAX_CHARACTER_FILES]

    imported_chars = 0
    character_names: list[str] = []
    for cf in char_files:
        text = await _read_upload(cf)
        if not text:
            continue
        name_hint = _name_from_filename(cf.filename or "角色.txt")
        character_names.append(name_hint)
        char_data = None
        if adapt_with_ai:
            char_data, warn, info = await safe_adapt(
                "character",
                text,
                user,
                label=f"角色·{name_hint}",
                name_hint=name_hint,
                **ctx,
            )
            _record(char_data, warn, info)
        if char_data:
            name = str(char_data.get("name") or name_hint).strip()
            if name:
                character_names[-1] = name
            sync_character_card(
                db,
                book,
                {
                    "type": "character",
                    "title": name or name_hint,
                    "data": char_data,
                },
                overwrite=True,
            )
        else:
            ch = _apply_character(db, book, cf.filename or "角色.txt", text)
            if ch.name:
                character_names[-1] = ch.name
        imported_chars += 1

    if worldview_text:
        wv_data = None
        if adapt_with_ai:
            wv_data, warn, info = await safe_adapt("worldview", worldview_text, user, label="世界观", **ctx)
            _record(wv_data, warn, info)
        if wv_data:
            apply_card_by_type(db, book, "worldview", wv_data)
        else:
            _apply_worldview(db, book, worldview_text)

    outline_text = await _read_upload(outline_file)
    if outline_text:
        outline_data = None
        if adapt_with_ai:
            outline_data, warn, info = await safe_adapt(
                "outline",
                outline_text,
                user,
                label="故事大纲",
                character_names=character_names,
                **ctx,
            )
            _record(outline_data, warn, info)
        if outline_data:
            _apply_outline_adapted(db, book, outline_data, target_chapters)
        else:
            _apply_outline(book, outline_text, target_chapters)

    prefs_parts: list[str] = []
    writing_prefs = await _read_upload(writing_prefs_file)
    if writing_prefs:
        adapted_prefs = None
        if adapt_with_ai:
            adapted_prefs, warn, info = await safe_adapt("prefs", writing_prefs, user, label="写作偏好", **ctx)
            _record(adapted_prefs, warn, info)
        prefs_parts.append(f"## 写作偏好\n\n{adapted_prefs or writing_prefs}")
    conventions = await _read_upload(conventions_file)
    if conventions:
        adapted_conv = None
        if adapt_with_ai:
            adapted_conv, warn, info = await safe_adapt("conventions", conventions, user, label="写作规约", **ctx)
            _record(adapted_conv, warn, info)
        prefs_parts.append(f"## 写作规约\n\n{adapted_conv or conventions}")
    if prefs_parts:
        book.writing_rules = "\n\n".join(prefs_parts)

    if not premise and outline_text:
        book.premise = outline_text[:500]
        book.blurb = book.premise

    db.commit()
    db.refresh(book)
    unique_warnings = list(dict.fromkeys(w for w in warnings if w))
    unique_infos = list(dict.fromkeys(i for i in infos if i))
    adapt_parts: list[str] = []
    if unique_warnings:
        adapt_parts.append("；".join(unique_warnings[:4]))
        if len(unique_warnings) > 4:
            adapt_parts[-1] += f" 等 {len(unique_warnings)} 条"
    if unique_infos and adapt_with_ai:
        adapt_parts.append("摘要：" + "；".join(unique_infos[:2]))
    stats: dict[str, int | bool | str] = {
        "characters": imported_chars,
        "has_worldview": bool(worldview_text),
        "has_outline": bool(outline_text),
        "has_writing_prefs": bool(writing_prefs or conventions),
        "ai_adapted": ai_adapted and adapt_with_ai,
        "adapt_warning": "。".join(adapt_parts) if adapt_parts else "",
        "adapt_ai_success": ai_success,
        "adapt_ai_fallback": ai_fallback,
    }
    return book, stats
