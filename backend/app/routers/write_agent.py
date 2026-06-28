from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import json
import asyncio
from app.database import get_db
from app.deps import get_current_user
from app.models import Book, User, WriteAgentMessage
from app.schemas import (
    SetupApplyIn,
    SetupActionOut,
    SetupCardOut,
    WriteAgentAppliedOut,
    WriteAgentChatIn,
    WriteAgentChatOut,
    WriteAgentCompressOut,
    WriteAgentContextStatus,
    WriteAgentMessageOut,
    WriteAgentMessagesOut,
    WriteAgentNewSessionOut,
    WriteAgentRevertIn,
)
from app.services.setup_agent import apply_card, reconcile_cards_with_book
from app.services.write_agent import (
    chat_turn,
    ensure_write_agent_session,
    list_write_agent_messages,
    mark_write_agent_card_applied,
    revert_snapshots,
    start_new_write_agent_session,
)
from app.services.write_agent_context import compress_write_agent_session, get_context_status

router = APIRouter(prefix="/books/{book_id}/write-agent", tags=["write-agent"])


def _owned(db: Session, book_id: int, user: User) -> Book:
    book = db.query(Book).filter(Book.id == book_id, Book.user_id == user.id).first()
    if not book:
        raise HTTPException(404, "书籍不存在")
    return book


def _msg_out(m: WriteAgentMessage, book: Book, db: Session) -> WriteAgentMessageOut:
    cards = reconcile_cards_with_book(db, book, m.cards_json or [])
    return WriteAgentMessageOut(
        id=m.id,
        role=m.role,
        content=m.content or "",
        cards=[SetupCardOut(**c) if isinstance(c, dict) else c for c in cards],
        actions=[SetupActionOut(**a) if isinstance(a, dict) else a for a in (m.actions_json or [])],
        meta=m.meta_json or {},
        created_at=m.created_at,
    )


def _context_status_out(book: Book, db: Session, chapter_no: int = 1) -> WriteAgentContextStatus:
    return WriteAgentContextStatus(**get_context_status(db, book, chapter_no=chapter_no))


@router.get("/messages", response_model=WriteAgentMessagesOut)
def get_write_agent_messages(
    book_id: int,
    chapter_no: int = 1,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    book = _owned(db, book_id, user)
    session_id = ensure_write_agent_session(db, book)
    messages = list_write_agent_messages(db, book)
    return WriteAgentMessagesOut(
        session_id=session_id,
        messages=[_msg_out(m, book, db) for m in messages],
        context_status=_context_status_out(book, db, chapter_no=chapter_no),
    )


@router.post("/new-session", response_model=WriteAgentNewSessionOut)
def new_write_agent_session(
    book_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    book = _owned(db, book_id, user)
    session_id, welcome = start_new_write_agent_session(db, book)
    return WriteAgentNewSessionOut(
        session_id=session_id,
        messages=[_msg_out(welcome, book, db)],
        context_status=_context_status_out(book, db),
    )


@router.post("/chat", response_model=WriteAgentChatOut)
async def write_agent_chat(
    book_id: int,
    data: WriteAgentChatIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    book = _owned(db, book_id, user)
    if not data.message.strip():
        raise HTTPException(400, "消息不能为空")

    session_id = ensure_write_agent_session(db, book)
    if data.resend_from_message_id:
        db.query(WriteAgentMessage).filter(
            WriteAgentMessage.book_id == book.id,
            WriteAgentMessage.session_id == session_id,
            WriteAgentMessage.id >= data.resend_from_message_id,
        ).delete(synchronize_session=False)
        db.commit()

    user_meta = {
        "input_text": (data.input_text or "").strip(),
        "quote": data.quote,
        "lint_issues": data.lint_issues or [],
    }
    result = await chat_turn(
        db,
        user,
        book,
        message=data.message.strip(),
        chapter_no=data.chapter_no,
        draft_content=data.draft_content,
        history=[h.model_dump() for h in data.history],
        user_meta=user_meta,
    )
    cards = reconcile_cards_with_book(db, book, result.get("cards") or [])
    result["cards"] = [SetupCardOut(**c) if isinstance(c, dict) else c for c in cards]
    result["actions"] = [SetupActionOut(**a) if isinstance(a, dict) else a for a in (result.get("actions") or [])]

    user_row = db.query(WriteAgentMessage).filter(WriteAgentMessage.id == result.pop("user_message_id", None)).first()
    assistant_row = db.query(WriteAgentMessage).filter(
        WriteAgentMessage.id == result.pop("assistant_message_id", None)
    ).first()
    out = WriteAgentChatOut(**result)
    if user_row:
        out.user_message = _msg_out(user_row, book, db)
    if assistant_row:
        out.assistant_message = _msg_out(assistant_row, book, db)
    if result.get("context_status"):
        out.context_status = WriteAgentContextStatus(**result["context_status"])
    return out


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.post("/chat/stream")
async def write_agent_chat_stream(
    book_id: int,
    data: WriteAgentChatIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    book = _owned(db, book_id, user)
    if not data.message.strip():
        raise HTTPException(400, "消息不能为空")

    session_id = ensure_write_agent_session(db, book)
    if data.resend_from_message_id:
        db.query(WriteAgentMessage).filter(
            WriteAgentMessage.book_id == book.id,
            WriteAgentMessage.session_id == session_id,
            WriteAgentMessage.id >= data.resend_from_message_id,
        ).delete(synchronize_session=False)
        db.commit()

    user_meta = {
        "input_text": (data.input_text or "").strip(),
        "quote": data.quote,
        "lint_issues": data.lint_issues or [],
    }

    queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()

    def emit(event: str, payload: dict) -> None:
        queue.put_nowait((event, payload))

    async def run_turn() -> None:
        try:
            result = await chat_turn(
                db,
                user,
                book,
                message=data.message.strip(),
                chapter_no=data.chapter_no,
                draft_content=data.draft_content,
                history=[h.model_dump() for h in data.history],
                user_meta=user_meta,
                stream_emit=emit,
            )
            cards = reconcile_cards_with_book(db, book, result.get("cards") or [])
            result["cards"] = cards
            user_row = db.query(WriteAgentMessage).filter(
                WriteAgentMessage.id == result.pop("user_message_id", None)
            ).first()
            assistant_row = db.query(WriteAgentMessage).filter(
                WriteAgentMessage.id == result.pop("assistant_message_id", None)
            ).first()
            if user_row:
                result["user_message"] = _msg_out(user_row, book, db).model_dump(mode="json")
            if assistant_row:
                result["assistant_message"] = _msg_out(assistant_row, book, db).model_dump(mode="json")
            emit("done", result)
        except Exception as exc:
            emit("error", {"message": str(exc)})
        finally:
            queue.put_nowait(None)

    async def event_generator():
        task = asyncio.create_task(run_turn())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                event, payload = item
                yield _sse_event(event, payload)
        finally:
            await task

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/compress-context", response_model=WriteAgentCompressOut)
async def write_agent_compress_context(
    book_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    book = _owned(db, book_id, user)
    result = await compress_write_agent_session(db, user, book)
    messages = list_write_agent_messages(db, book)
    summary_row = None
    if result.get("summary_message_id"):
        summary_row = db.query(WriteAgentMessage).filter(
            WriteAgentMessage.id == result["summary_message_id"]
        ).first()
    return WriteAgentCompressOut(
        ok=result["ok"],
        message=result["message"],
        archived_count=result.get("archived_count", 0),
        summary_message=_msg_out(summary_row, book, db) if summary_row else None,
        context_status=WriteAgentContextStatus(**result["context_status"]),
        messages=[_msg_out(m, book, db) for m in messages],
    )


@router.post("/apply", response_model=dict)
def write_agent_apply_card(
    book_id: int,
    data: SetupApplyIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    book = _owned(db, book_id, user)
    card = data.card.model_dump()
    card_id = str(card.get("id") or "")
    card["status"] = "applied"
    if card.get("type") == "character":
        from app.services.character_cards import sync_character_card

        ch = sync_character_card(db, book, card, overwrite=True)
        result = {"type": "character", "ok": True, "character_id": ch.id, "card_id": card_id, "message": f"角色「{ch.name}」已保存"}
    else:
        result = apply_card(db, book, card)
        result["card_id"] = card_id
    if card_id:
        mark_write_agent_card_applied(db, book, card_id)
    return {"result": result, "card": card, "card_applied": [result]}


@router.post("/revert", response_model=dict)
def write_agent_revert(
    book_id: int,
    data: WriteAgentRevertIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    book = _owned(db, book_id, user)
    if not data.snapshots:
        raise HTTPException(400, "无快照可撤销")
    reverted = revert_snapshots(db, book, [s.model_dump() for s in data.snapshots])
    return {"reverted": [WriteAgentAppliedOut(**r) for r in reverted]}
