"""Card 类型插件：apply_card(type, data) 注册 handler。"""
from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models import Book, Chapter, ChapterPlan, Character, Worldview

OUTLINE_MAX_BATCH = 15


def _get_or_create_worldview(db: Session, book: Book) -> Worldview:
    wv = db.query(Worldview).filter(Worldview.book_id == book.id).first()
    if not wv:
        wv = Worldview(book_id=book.id)
        db.add(wv)
        db.flush()
    return wv


CardHandler = Callable[[Session, Book, dict[str, Any], dict[str, Any]], dict[str, Any]]


def _apply_premise(db: Session, book: Book, data: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    if data.get("title"):
        book.title = str(data["title"]).strip()
    if data.get("genre"):
        book.genre = str(data["genre"])
    if data.get("premise"):
        book.premise = str(data["premise"])
    if data.get("blurb"):
        book.blurb = str(data["blurb"])
    elif data.get("premise"):
        book.blurb = str(data["premise"])
    if data.get("target_chapters"):
        book.target_chapters = int(data["target_chapters"])
    if book.setup_step < 2:
        book.setup_step = 2
    result["message"] = "作品信息已更新"
    return result


def _apply_worldview(db: Session, book: Book, data: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    wv = _get_or_create_worldview(db, book)
    for field in ("era", "setting", "tone", "timeline_text", "taboos", "content"):
        if data.get(field) is not None:
            setattr(wv, field, data[field])
    if book.setup_step < 3:
        book.setup_step = 3
    result["message"] = "世界观已保存"
    result["worldview_id"] = wv.id
    return result


def _apply_character(db: Session, book: Book, data: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    cid = data.get("character_id")
    ch = None
    if cid is not None:
        try:
            cid_int = int(cid)
        except (TypeError, ValueError):
            cid_int = None
        if cid_int is not None:
            ch = db.query(Character).filter(Character.id == cid_int, Character.book_id == book.id).first()
    if not ch and data.get("name"):
        ch = (
            db.query(Character)
            .filter(Character.name == data["name"], Character.book_id == book.id)
            .first()
        )
    if ch:
        for field in ("name", "role", "summary", "voice_notes", "content"):
            if data.get(field) is not None:
                setattr(ch, field, data[field])
    else:
        ch = Character(
            book_id=book.id,
            name=data.get("name") or "未命名",
            role=data.get("role") or "support",
            summary=data.get("summary") or "",
            voice_notes=data.get("voice_notes") or "",
            content=data.get("content") or "",
        )
        db.add(ch)
        db.flush()
    char_count = db.query(Character).filter(Character.book_id == book.id).count()
    if char_count >= 1 and book.setup_step < 4:
        book.setup_step = max(book.setup_step, 3)
    result["message"] = f"角色「{ch.name}」已保存"
    result["character_id"] = ch.id
    return result


def _apply_outline(db: Session, book: Book, data: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    from app.services.outline_planner import normalize_outline_data

    normalized = normalize_outline_data(data)
    chapters = normalized.get("chapters") or []
    if isinstance(chapters, list) and len(chapters) > OUTLINE_MAX_BATCH:
        chapters = chapters[:OUTLINE_MAX_BATCH]
    applied = 0
    for item in chapters:
        no = int(item.get("chapter_no", 0))
        if no < 1:
            continue
        plan = (
            db.query(ChapterPlan)
            .filter(ChapterPlan.book_id == book.id, ChapterPlan.chapter_no == no)
            .first()
        )
        if not plan:
            plan = ChapterPlan(book_id=book.id, chapter_no=no)
            db.add(plan)
        # 仅写入卡片中的非空字段，避免同步已采纳卡片时用空值覆盖导入的大纲
        new_title = (item.get("title") or "").strip()
        if new_title:
            plan.title = new_title
        elif not (plan.title or "").strip():
            plan.title = f"第{no}章"
        new_plot = (item.get("plot_points") or item.get("synopsis") or "").strip()
        if new_plot:
            plan.plot_points = new_plot
        new_comedy = (item.get("comedy_core") or item.get("comedy_hook") or "").strip()
        if new_comedy:
            plan.comedy_core = new_comedy
        new_scene = (item.get("scene") or "").strip()
        if new_scene:
            plan.scene = new_scene
        cast = item.get("cast") or item.get("characters") or []
        if isinstance(cast, list) and cast:
            plan.character_names = "、".join(str(x) for x in cast)
        elif cast:
            plan.character_names = str(cast)
        new_meta = {
            "cast": cast if isinstance(cast, list) else ([cast] if cast else []),
            "events": item.get("events") or [],
            "entrances": item.get("entrances") or [],
            "exits": item.get("exits") or [],
        }
        if any(new_meta[k] for k in ("cast", "events", "entrances", "exits")):
            existing_meta = plan.meta_json if isinstance(plan.meta_json, dict) else {}
            plan.meta_json = {**existing_meta, **{k: v for k, v in new_meta.items() if v}}
        elif not plan.meta_json:
            plan.meta_json = new_meta
        ch = db.query(Chapter).filter(Chapter.book_id == book.id, Chapter.chapter_no == no).first()
        if not ch:
            ch = Chapter(book_id=book.id, chapter_no=no, title=plan.title, status="planned")
            db.add(ch)
        else:
            ch.title = plan.title
        applied += 1
    if applied and book.setup_step < 5:
        book.setup_step = max(book.setup_step, 4)
    result["message"] = f"已更新 {applied} 章大纲"
    return result


def _apply_plot(db: Session, book: Book, data: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    if data.get("summary"):
        book.blurb = data["summary"]
    total = data.get("total_chapters")
    if not total:
        from app.services.setup_agent import _infer_total_chapters_from_plot_data

        total = _infer_total_chapters_from_plot_data(data)
    if total:
        book.target_chapters = int(total)
        data = {**data, "total_chapters": int(total)}
    book.plot_framework = {
        k: data.get(k)
        for k in ("summary", "total_chapters", "style", "phases", "units", "title")
        if data.get(k) is not None
    }
    result["message"] = "长线剧情框架已记录"
    return result


def _apply_writing_prefs(db: Session, book: Book, data: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content") or data.get("writing_rules") or ""
    mode = data.get("mode", "replace")
    if mode == "append" and book.writing_rules.strip():
        book.writing_rules = book.writing_rules.strip() + "\n\n" + content
    else:
        book.writing_rules = content
    result["message"] = "本书写作偏好已保存"
    return result


CARD_HANDLERS: dict[str, CardHandler] = {
    "premise": _apply_premise,
    "worldview": _apply_worldview,
    "character": _apply_character,
    "outline": _apply_outline,
    "plot": _apply_plot,
    "writing_prefs": _apply_writing_prefs,
}


def apply_card_by_type(
    db: Session,
    book: Book,
    card_type: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    handler = CARD_HANDLERS.get(card_type)
    result: dict[str, Any] = {"type": card_type, "ok": True}
    if not handler:
        result["ok"] = False
        result["message"] = f"未知卡片类型: {card_type}"
        return result
    return handler(db, book, data, result)
