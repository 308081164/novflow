"""从用户上传的文档导入已有书籍设定。"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.models import Book, Character, User, Worldview
from app.services.book_import_adapt import safe_adapt
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
        "premise": premise,
        "target_chapters": target_chapters,
    }
    warnings: list[str] = []
    ai_adapted = False

    worldview_text = await _read_upload(worldview_file)
    if worldview_text:
        wv_data = None
        if adapt_with_ai:
            wv_data, warn = await safe_adapt("worldview", worldview_text, user, **ctx)
            if warn:
                warnings.append(warn)
            elif wv_data:
                ai_adapted = True
        if wv_data:
            apply_card_by_type(db, book, "worldview", wv_data)
        else:
            _apply_worldview(db, book, worldview_text)

    outline_text = await _read_upload(outline_file)
    if outline_text:
        outline_data = None
        if adapt_with_ai:
            outline_data, warn = await safe_adapt("outline", outline_text, user, **ctx)
            if warn:
                warnings.append(warn)
            elif outline_data:
                ai_adapted = True
        if outline_data:
            _apply_outline_adapted(db, book, outline_data, target_chapters)
        else:
            _apply_outline(book, outline_text, target_chapters)

    prefs_parts: list[str] = []
    writing_prefs = await _read_upload(writing_prefs_file)
    if writing_prefs:
        adapted_prefs = None
        if adapt_with_ai:
            adapted_prefs, warn = await safe_adapt("prefs", writing_prefs, user, **ctx)
            if warn:
                warnings.append(warn)
            elif adapted_prefs:
                ai_adapted = True
        prefs_parts.append(f"## 写作偏好\n\n{adapted_prefs or writing_prefs}")
    conventions = await _read_upload(conventions_file)
    if conventions:
        adapted_conv = None
        if adapt_with_ai:
            adapted_conv, warn = await safe_adapt("conventions", conventions, user, **ctx)
            if warn:
                warnings.append(warn)
            elif adapted_conv:
                ai_adapted = True
        prefs_parts.append(f"## 写作规约\n\n{adapted_conv or conventions}")
    if prefs_parts:
        book.writing_rules = "\n\n".join(prefs_parts)

    imported_chars = 0
    for cf in character_files or []:
        text = await _read_upload(cf)
        if not text:
            continue
        name_hint = _name_from_filename(cf.filename or "角色.txt")
        char_data = None
        if adapt_with_ai:
            char_data, warn = await safe_adapt(
                "character",
                text,
                user,
                name_hint=name_hint,
                **ctx,
            )
            if warn:
                warnings.append(warn)
            elif char_data:
                ai_adapted = True
        if char_data:
            sync_character_card(
                db,
                book,
                {
                    "type": "character",
                    "title": char_data.get("name") or name_hint,
                    "data": char_data,
                },
                overwrite=True,
            )
        else:
            _apply_character(db, book, cf.filename or "角色.txt", text)
        imported_chars += 1

    if not premise and outline_text:
        book.premise = outline_text[:500]
        book.blurb = book.premise

    db.commit()
    db.refresh(book)
    # 去重警告，避免多次 API 失败重复提示
    unique_warnings = list(dict.fromkeys(w for w in warnings if w))
    stats: dict[str, int | bool | str] = {
        "characters": imported_chars,
        "has_worldview": bool(worldview_text),
        "has_outline": bool(outline_text),
        "has_writing_prefs": bool(writing_prefs or conventions),
        "ai_adapted": ai_adapted and adapt_with_ai,
        "adapt_warning": unique_warnings[0] if unique_warnings else "",
    }
    return book, stats
