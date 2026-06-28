"""角色卡：DB 与 SetupCard 之间的唯一转换与同步。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import case
from sqlalchemy.orm import Session

from app.models import Book, Character

CHARACTER_TEXT_FIELDS = ("summary", "voice_notes", "content", "role", "name")


def character_model_to_card(c: Character) -> dict[str, Any]:
    return {
        "id": f"char_{c.id}",
        "type": "character",
        "title": c.name,
        "status": "applied",
        "data": {
            "character_id": c.id,
            "name": c.name,
            "role": c.role,
            "summary": c.summary or "",
            "voice_notes": c.voice_notes or "",
            "content": c.content or "",
        },
    }


def character_name(card: dict[str, Any]) -> str:
    data = card.get("data") or {}
    return str(data.get("name") or card.get("title") or "").strip()


def merge_character_cards_by_name(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """合并同名角色卡：每个文本字段取最长非空版本。"""
    by_name: dict[str, dict[str, Any]] = {}
    for card in cards:
        if card.get("type") != "character":
            continue
        name = character_name(card)
        if not name:
            continue
        data = dict(card.get("data") or {})
        if name not in by_name:
            merged = dict(card)
            merged["data"] = data
            merged["title"] = name
            by_name[name] = merged
            continue
        target = by_name[name]
        tdata = target.setdefault("data", {})
        for field in CHARACTER_TEXT_FIELDS:
            a = str(tdata.get(field) or "").strip()
            b = str(data.get(field) or "").strip()
            if len(b) > len(a):
                tdata[field] = data[field]
        if data.get("character_id") and not tdata.get("character_id"):
            tdata["character_id"] = data["character_id"]
    return list(by_name.values())


def dedupe_characters_by_name(db: Session, book: Book | None) -> int:
    """合并同名角色，保留 id 最小的一条。"""
    if not book:
        return 0
    chars = (
        db.query(Character)
        .filter(Character.book_id == book.id)
        .order_by(Character.id)
        .all()
    )
    keepers: dict[str, Character] = {}
    removed = 0
    for c in chars:
        if c.name not in keepers:
            keepers[c.name] = c
            continue
        prev = keepers[c.name]
        for field in ("content", "summary", "voice_notes", "role"):
            nv = (getattr(c, field) or "").strip()
            pv = (getattr(prev, field) or "").strip()
            if len(nv) > len(pv):
                setattr(prev, field, getattr(c, field))
        db.delete(c)
        removed += 1
    if removed:
        db.commit()
    return removed


def list_character_cards(db: Session, book_id: int) -> list[dict[str, Any]]:
    book = db.query(Book).filter(Book.id == book_id).first()
    dedupe_characters_by_name(db, book)
    role_rank = case(
        (Character.role.in_(("protagonist", "男主", "主角")), 0),
        (Character.role.in_(("support", "配角", "女主")), 1),
        else_=2,
    )
    chars = (
        db.query(Character)
        .filter(Character.book_id == book_id)
        .order_by(role_rank, Character.name, Character.id)
        .all()
    )
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for c in chars:
        if c.name in seen:
            continue
        seen.add(c.name)
        out.append(character_model_to_card(c))
    return out


def _find_character(db: Session, book: Book, data: dict[str, Any]) -> Character | None:
    cid = data.get("character_id")
    if cid is not None:
        try:
            cid_int = int(cid)
            ch = db.query(Character).filter(Character.id == cid_int, Character.book_id == book.id).first()
            if ch:
                return ch
        except (TypeError, ValueError):
            pass
    name = (data.get("name") or "").strip()
    if name:
        return (
            db.query(Character)
            .filter(Character.name == name, Character.book_id == book.id)
            .order_by(Character.id)
            .first()
        )
    return None


def sync_character_card(db: Session, book: Book, card: dict[str, Any], *, overwrite: bool = False) -> Character:
    data = dict(card.get("data") or {})
    if not data.get("name") and card.get("title"):
        data["name"] = card["title"]

    ch = _find_character(db, book, data)
    if ch:
        for field in ("name", "role", "summary", "voice_notes", "content"):
            incoming = data.get(field)
            if incoming is None:
                continue
            inc = str(incoming).strip() if isinstance(incoming, str) else incoming
            if not inc and field != "role":
                continue
            old = (getattr(ch, field) or "").strip()
            if overwrite:
                setattr(ch, field, incoming)
            elif field in ("summary", "voice_notes", "content"):
                if len(inc) >= len(old):
                    setattr(ch, field, incoming)
            elif inc:
                setattr(ch, field, incoming)
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

    if book.setup_step < 4:
        book.setup_step = max(book.setup_step, 3)
    db.commit()
    db.refresh(ch)
    return ch


def ingest_character_cards(db: Session, book: Book, cards: list[dict[str, Any]], *, overwrite: bool = True) -> None:
    merged = merge_character_cards_by_name(cards)
    for card in merged:
        sync_character_card(db, book, card, overwrite=overwrite)
    dedupe_characters_by_name(db, book)


def cards_from_db_names(db: Session, book: Book, names: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name in names:
        if not name:
            continue
        ch = (
            db.query(Character)
            .filter(Character.book_id == book.id, Character.name == name)
            .order_by(Character.id)
            .first()
        )
        if ch:
            out.append(character_model_to_card(ch))
    return out
