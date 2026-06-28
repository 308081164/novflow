"""章节改文共享内核：generation 与 write_agent 共用校验与写入逻辑。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import Book, Chapter, ChapterPlan, ChapterVersion
from app.services.agent_intent import finalize_chapter_edit_content
from app.services.chapter_content import get_content, set_content
from app.services.rule_engine import word_count


def snapshot_chapter(db: Session, book: Book, chapter_no: int) -> dict | None:
    ch = db.query(Chapter).filter(Chapter.book_id == book.id, Chapter.chapter_no == chapter_no).first()
    if not ch:
        return {"chapter_no": chapter_no, "title": f"第{chapter_no}章", "content": ""}
    return {
        "chapter_no": chapter_no,
        "title": ch.title or f"第{chapter_no}章",
        "content": get_content(ch),
    }


def revert_snapshots(db: Session, book: Book, snapshots: list[dict]) -> list[dict]:
    """将章节恢复为智能体修改前的快照。"""
    reverted: list[dict] = []
    for snap in snapshots:
        no = int(snap.get("chapter_no") or 0)
        if no < 1:
            continue
        content = str(snap.get("content") or "")
        title = str(snap.get("title") or f"第{no}章")
        ch = db.query(Chapter).filter(Chapter.book_id == book.id, Chapter.chapter_no == no).first()
        if not ch:
            ch = Chapter(book_id=book.id, chapter_no=no, title=title, status="planned")
            db.add(ch)
            db.flush()
        set_content(ch, content)
        ch.title = title
        ch.word_count = word_count(content) if content.strip() else 0
        ch.status = "draft" if content.strip() else "planned"
        ch.updated_at = datetime.utcnow()
        db.add(ChapterVersion(chapter_id=ch.id, content=content, source="write_agent_revert"))
        reverted.append({"chapter_no": no, "title": ch.title, "word_count": ch.word_count})
    if reverted:
        db.commit()
    return reverted


def apply_edits(
    db: Session,
    book: Book,
    edits: list[dict],
    *,
    chapter_contents: dict[int, str] | None = None,
    edit_context: dict[str, Any] | None = None,
    source: str = "write_agent",
) -> tuple[list[dict], list[dict]]:
    """校验并写入章节 edits，返回 (applied, revert_snapshots)。"""
    applied: list[dict] = []
    revert_snapshots: list[dict] = []
    seen: set[int] = set()
    contents = chapter_contents or {}
    ctx = edit_context or {}
    for e in edits:
        no = int(e["chapter_no"])
        if no in seen:
            continue
        seen.add(no)
        ch = db.query(Chapter).filter(Chapter.book_id == book.id, Chapter.chapter_no == no).first()
        orig = (contents.get(no) or "").strip()
        if not orig and ch:
            orig = get_content(ch).strip()
        finalized = finalize_chapter_edit_content(
            str(e.get("content") or ""),
            chapter_no=no,
            original_content=orig,
            edit_scope=str(ctx.get("edit_scope") or "chapter"),
            selection_quote=str(ctx.get("selection_quote") or ""),
        )
        if not finalized:
            continue
        if orig and finalized.strip() == orig.strip():
            continue
        snap = snapshot_chapter(db, book, no)
        prev_content = str(snap.get("content") or "") if snap else orig
        if snap:
            revert_snapshots.append(snap)
        if not ch:
            ch = Chapter(book_id=book.id, chapter_no=no, title=e.get("title") or f"第{no}章", status="draft")
            db.add(ch)
            db.flush()
        set_content(ch, finalized)
        ch.word_count = word_count(finalized)
        if e.get("title"):
            ch.title = e["title"]
        if ch.status == "planned":
            ch.status = "draft"
        ch.updated_at = datetime.utcnow()
        db.add(ChapterVersion(chapter_id=ch.id, content=finalized, source=source))
        plan = (
            db.query(ChapterPlan)
            .filter(ChapterPlan.book_id == book.id, ChapterPlan.chapter_no == no)
            .first()
        )
        if plan and e.get("title"):
            plan.title = e["title"]
        applied.append(
            {
                "chapter_no": no,
                "title": ch.title,
                "word_count": ch.word_count,
                "previous_content": prev_content,
            }
        )
    if applied:
        db.commit()
    return applied, revert_snapshots
