"""写作智能体对话上下文估算与压缩。"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import Book, User, WriteAgentMessage
from app.services.ai_assist import _chat
from app.services.message_format import assistant_content_for_history as _assistant_content_for_history
from app.services.context_limits import (
    CONTEXT_COMPRESS_SUGGEST_CHARS,
    CONTEXT_WARN_CHARS,
    KEEP_RECENT_ON_COMPRESS,
    chars_to_estimated_tokens,
)

_SUMMARY_SYSTEM = """你是写作智能体对话压缩助手。将较长的对话历史压缩为结构化摘要，供后续轮次继续协作。
必须保留：用户决策与约束、已改动的设定/书名/角色、章节修改记录（章号与改动要点）、未完成任务、用户表达的写作偏好。
不要粘贴完整章节正文。用中文 Markdown，分节清晰，控制在 2000 字以内。"""


def _session_messages_query(db: Session, book: Book, session_id: str):
    return (
        db.query(WriteAgentMessage)
        .filter(
            WriteAgentMessage.book_id == book.id,
            WriteAgentMessage.session_id == session_id,
        )
        .order_by(WriteAgentMessage.id)
    )


def _message_meta(m: WriteAgentMessage) -> dict[str, Any]:
    return dict(m.meta_json or {})


def _is_archived(m: WriteAgentMessage) -> bool:
    return bool(_message_meta(m).get("archived"))


def _is_welcome(m: WriteAgentMessage) -> bool:
    return bool(_message_meta(m).get("welcome"))


def _is_context_summary(m: WriteAgentMessage) -> bool:
    return bool(_message_meta(m).get("context_summary"))



def list_visible_session_messages(db: Session, book: Book, session_id: str) -> list[WriteAgentMessage]:
    """UI 与 LLM 可见消息：欢迎语 + 最新摘要 + 未归档对话。"""
    rows = _session_messages_query(db, book, session_id).all()
    welcome = [m for m in rows if _is_welcome(m) and not _is_archived(m)]
    summaries = [m for m in rows if _is_context_summary(m) and not _is_archived(m)]
    active = [
        m
        for m in rows
        if not _is_archived(m) and not _is_welcome(m) and not _is_context_summary(m)
    ]
    out: list[WriteAgentMessage] = []
    if welcome:
        out.append(welcome[0])
    if summaries:
        out.append(summaries[-1])
    out.extend(active)
    return out


def _count_active_messages(db: Session, book: Book, session_id: str) -> tuple[int, int]:
    rows = _session_messages_query(db, book, session_id).all()
    total = len([m for m in rows if not _is_archived(m)])
    compressible = len(
        [
            m
            for m in rows
            if not _is_archived(m) and not _is_welcome(m) and not _is_context_summary(m)
        ]
    )
    return total, compressible


def estimate_write_agent_context(
    db: Session,
    book: Book,
    session_id: str,
    *,
    chapter_no: int = 1,
    draft_content: str | None = None,
) -> dict[str, Any]:
    from app.services.write_agent import _book_write_snapshot, _system_prompt, build_history_from_db

    snapshot = _book_write_snapshot(db, book, chapter_no, draft_content)
    system_chars = len(_system_prompt(snapshot))
    history = build_history_from_db(db, book, session_id)
    history_chars = sum(len(str(h.get("content") or "")) for h in history)
    estimated_chars = system_chars + history_chars
    total_msgs, active_compressible = _count_active_messages(db, book, session_id)
    rows = _session_messages_query(db, book, session_id).all()
    has_summary = any(_is_context_summary(m) and not _is_archived(m) for m in rows)
    return {
        "estimated_chars": estimated_chars,
        "estimated_tokens": chars_to_estimated_tokens(estimated_chars),
        "system_chars": system_chars,
        "history_chars": history_chars,
        "message_count": total_msgs,
        "active_message_count": active_compressible,
        "warn": estimated_chars >= CONTEXT_WARN_CHARS,
        "suggest_compress": estimated_chars >= CONTEXT_COMPRESS_SUGGEST_CHARS
        or active_compressible > KEEP_RECENT_ON_COMPRESS * 3,
        "has_summary": has_summary,
    }


def get_context_status(
    db: Session,
    book: Book,
    *,
    chapter_no: int = 1,
    draft_content: str | None = None,
) -> dict[str, Any]:
    from app.services.write_agent import ensure_write_agent_session

    session_id = ensure_write_agent_session(db, book)
    return estimate_write_agent_context(
        db, book, session_id, chapter_no=chapter_no, draft_content=draft_content
    )


async def _summarize_conversation(user: User, transcript: str) -> str:
    messages = [
        {"role": "system", "content": _SUMMARY_SYSTEM},
        {
            "role": "user",
            "content": f"请压缩以下写作智能体对话历史：\n\n{transcript[:120_000]}",
        },
    ]
    raw = await _chat(user, messages, temperature=0.3, max_tokens=4096, json_object=False)
    text = (raw or "").strip()
    if not text:
        raise ValueError("压缩摘要生成失败，请稍后重试")
    return text[:8000]


async def compress_write_agent_session(
    db: Session,
    user: User,
    book: Book,
    *,
    keep_recent: int = KEEP_RECENT_ON_COMPRESS,
) -> dict[str, Any]:
    from app.services.write_agent import ensure_write_agent_session

    session_id = ensure_write_agent_session(db, book)
    rows = _session_messages_query(db, book, session_id).all()
    visible = [m for m in rows if not _is_archived(m)]
    compressible = [
        m for m in visible if not _is_welcome(m) and not _is_context_summary(m)
    ]

    status = estimate_write_agent_context(db, book, session_id)

    if len(compressible) <= keep_recent:
        return {
            "ok": False,
            "message": f"当前仅 {len(compressible)} 条对话，暂无需压缩（保留最近 {keep_recent} 条）",
            "archived_count": 0,
            "summary_message_id": None,
            "context_status": status,
        }

    to_archive = compressible[:-keep_recent]
    old_summaries = [m for m in visible if _is_context_summary(m)]

    parts: list[str] = []
    for s in old_summaries:
        parts.append(f"【此前已压缩摘要】\n{s.content or ''}")
    for m in to_archive:
        if m.role == "user":
            parts.append(f"用户：{(m.content or '').strip()}")
        elif m.role == "assistant":
            parts.append(f"助手：{_assistant_content_for_history(m)}")

    summary_text = await _summarize_conversation(user, "\n\n".join(parts))
    archived_count = len(to_archive)

    for s in old_summaries:
        meta = _message_meta(s)
        meta["archived"] = True
        s.meta_json = meta
        archived_count += 1

    for m in to_archive:
        meta = _message_meta(m)
        meta["archived"] = True
        m.meta_json = meta

    summary_msg = WriteAgentMessage(
        book_id=book.id,
        session_id=session_id,
        role="assistant",
        content=summary_text,
        cards_json=[],
        actions_json=[],
        meta_json={
            "context_summary": True,
            "archived_count": archived_count,
            "covers_until_id": to_archive[-1].id if to_archive else 0,
        },
    )
    db.add(summary_msg)
    db.commit()
    db.refresh(summary_msg)

    new_status = estimate_write_agent_context(db, book, session_id)
    return {
        "ok": True,
        "message": f"已压缩 {archived_count} 条历史消息，保留最近 {keep_recent} 轮对话",
        "archived_count": archived_count,
        "summary_message_id": summary_msg.id,
        "context_status": new_status,
    }
