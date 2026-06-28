from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
import asyncio
import json
import re
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Book, User
from app.routers.books import book_to_out
from app.schemas import (
    SetupApplyIn,
    SetupChatIn,
    SetupChatTurnOut,
    SetupContextOut,
    SetupMessageOut,
    SetupCardOut,
    SetupActionOut,
    BookOut,
)
from app.services.setup_agent import (
    _book_snapshot,
    _normalize_cards_list,
    apply_card,
    chat_turn,
    ensure_welcome,
    finish_setup,
    list_messages,
    mark_card_applied_in_messages,
    reconcile_cards_with_book,
    repair_all_setup_messages,
    sync_reconciled_card_statuses,
)

router = APIRouter(prefix="/books/{book_id}/setup/chat", tags=["setup-chat"])


def _get_owned(db: Session, book_id: int, user: User) -> Book:
    book = db.query(Book).filter(Book.id == book_id, Book.user_id == user.id).first()
    if not book:
        raise HTTPException(404, "书籍不存在")
    return book


def _msg_out(m, book: Book | None = None, db: Session | None = None) -> SetupMessageOut:
    raw_cards = m.cards_json or []
    if book is not None and db is not None:
        raw_cards = reconcile_cards_with_book(db, book, raw_cards)
    raw_cards = _normalize_cards_list(raw_cards)
    cards = [SetupCardOut(**c) if isinstance(c, dict) else c for c in raw_cards]
    content = m.content or ""
    if re.search(r"\[已输出卡片", content):
        content = ""
    raw_actions = getattr(m, "actions_json", None) or []
    actions = [SetupActionOut(**a) if isinstance(a, dict) else a for a in raw_actions]
    return SetupMessageOut(
        id=m.id,
        role=m.role,
        content=content,
        cards=cards,
        actions=actions,
        meta=getattr(m, "meta_json", None) or {},
        created_at=m.created_at,
    )


@router.get("", response_model=SetupContextOut)
def get_setup_chat(book_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    book = _get_owned(db, book_id, user)
    ensure_welcome(db, book)
    repair_all_setup_messages(db, book.id)
    sync_reconciled_card_statuses(db, book)
    messages = list_messages(db, book.id)
    return SetupContextOut(
        book=book_to_out(book, db),
        snapshot=_book_snapshot(db, book),
        messages=[_msg_out(m, book, db) for m in messages],
    )


@router.post("", response_model=SetupChatTurnOut)
async def post_setup_chat(
    book_id: int,
    data: SetupChatIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    book = _get_owned(db, book_id, user)
    ensure_welcome(db, book)
    user_msg, assistant_msg, applied = await chat_turn(db, user, book, data.message.strip())
    db.refresh(book)
    return SetupChatTurnOut(
        user_message=_msg_out(user_msg, book, db),
        assistant_message=_msg_out(assistant_msg, book, db),
        applied=applied,
        book=book_to_out(book, db),
        snapshot=_book_snapshot(db, book),
    )


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.post("/stream")
async def post_setup_chat_stream(
    book_id: int,
    data: SetupChatIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    book = _get_owned(db, book_id, user)
    if not data.message.strip():
        raise HTTPException(400, "消息不能为空")
    ensure_welcome(db, book)

    queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()

    def emit(event: str, payload: dict) -> None:
        queue.put_nowait((event, payload))

    async def run_turn() -> None:
        try:
            user_msg, assistant_msg, applied = await chat_turn(
                db, user, book, data.message.strip(), stream_emit=emit
            )
            db.refresh(book)
            emit(
                "done",
                {
                    "user_message": _msg_out(user_msg, book, db).model_dump(mode="json"),
                    "assistant_message": _msg_out(assistant_msg, book, db).model_dump(mode="json"),
                    "applied": applied,
                    "book": book_to_out(book, db).model_dump(mode="json"),
                    "snapshot": _book_snapshot(db, book),
                },
            )
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


@router.post("/apply", response_model=dict)
def apply_setup_card(
    book_id: int,
    data: SetupApplyIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    book = _get_owned(db, book_id, user)
    card = data.card.model_dump()
    card["status"] = "applied"
    if card.get("type") == "character":
        from app.services.character_cards import sync_character_card

        ch = sync_character_card(db, book, card, overwrite=True)
        result = {"type": "character", "ok": True, "character_id": ch.id, "message": f"角色「{ch.name}」已保存"}
    else:
        result = apply_card(db, book, card)
    mark_card_applied_in_messages(db, book_id, card)
    sync_reconciled_card_statuses(db, book)
    messages = list_messages(db, book.id)
    return {
        "result": result,
        "book": book_to_out(book, db),
        "snapshot": _book_snapshot(db, book),
        "messages": [_msg_out(m, book, db) for m in messages],
    }


@router.post("/finish", response_model=BookOut)
async def finish_setup_chat(
    book_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    book = _get_owned(db, book_id, user)
    book = await finish_setup(db, user, book)
    return book_to_out(book, db)
