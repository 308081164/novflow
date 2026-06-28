"""写作智能体卡片采纳与 book meta 写入。"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import Book
from app.services.agent_constants import ADOPT_KEYWORDS, PREMISE_KEYWORDS
from app.services.agent_intent import extract_title_from_message, is_apply_book_meta_message
from app.services.card_handlers import apply_card_by_type
from app.services.character_cards import sync_character_card
from app.services.setup_agent import apply_card


def build_premise_apply_card(book: Book, title: str) -> dict[str, Any]:
    card_id = f"premise_{uuid.uuid4().hex[:10]}"
    synopsis = (book.premise or book.blurb or "").strip()
    return {
        "id": card_id,
        "type": "premise",
        "title": title or book.title or "作品信息",
        "status": "applied",
        "data": {
            "title": title,
            "genre": book.genre or "",
            "premise": synopsis,
            "blurb": book.blurb or book.premise or synopsis,
            "target_chapters": book.target_chapters,
        },
    }


def resolve_title_for_apply(
    msg: str,
    understanding: dict[str, Any],
    parsed: dict[str, Any],
) -> str | None:
    title = str(understanding.get("extracted_title") or "").strip()
    if title:
        return title
    title = extract_title_from_message(msg)
    if title:
        return title
    title = extract_title_from_message(str(parsed.get("reply") or ""))
    if title:
        return title
    for card in parsed.get("cards") or []:
        if isinstance(card, dict) and card.get("type") == "premise":
            data = card.get("data") or {}
            t = str(data.get("title") or "").strip()
            if t:
                return t
    return None


def should_apply_book_title(
    msg: str,
    understanding: dict[str, Any],
    parsed: dict[str, Any],
    card_applied: list[dict],
) -> bool:
    if card_applied:
        return False
    if understanding.get("intent") == "apply_book_meta":
        return True
    if is_apply_book_meta_message(msg):
        return True
    if understanding.get("intent") == "draft_card" and understanding.get("topic") == "book_meta":
        return True
    if "书名" in msg and any(k in msg for k in ADOPT_KEYWORDS):
        return True
    reply = str(parsed.get("reply") or "")
    if ("书名" in msg or is_apply_book_meta_message(msg)) and any(
        k in reply for k in ("已更新", "已改为", "已改成", "已写入", "已保存")
    ):
        return True
    return bool(parsed.get("apply_card_ids")) and any(
        isinstance(c, dict) and c.get("type") == "premise" for c in (parsed.get("cards") or [])
    )


def apply_book_title_to_db(
    db: Session,
    book: Book,
    title: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    card = build_premise_apply_card(book, title)
    result = apply_card(db, book, card)
    db.flush()
    db.refresh(book)
    return card, {**result, "card_id": card["id"], "type": "premise", "ok": True}


def finalize_book_meta_apply(
    db: Session,
    book: Book,
    msg: str,
    understanding: dict[str, Any],
    parsed: dict[str, Any],
    cards: list[dict],
    card_applied: list[dict],
) -> tuple[list[dict], list[dict], dict[str, Any]]:
    if not should_apply_book_title(msg, understanding, parsed, card_applied):
        return cards, card_applied, parsed

    title = resolve_title_for_apply(msg, understanding, parsed)
    if not title:
        return cards, card_applied, parsed

    if book.title.strip() == title.strip() and card_applied:
        return cards, card_applied, parsed

    card, result = apply_book_title_to_db(db, book, title)
    cards = [card]
    card_applied = [result]
    if not parsed.get("reply") or any(k in str(parsed.get("reply")) for k in ("已更新", "已改为", "已改成")):
        parsed = dict(parsed)
        parsed["reply"] = (
            f"好的，书名已更新为《{title}》。"
            f"\n\n**当前作品信息**\n- 书名：{book.title}\n- 类型：{book.genre or '未设定'}"
        )
    return cards, card_applied, parsed


def adopt_cards_from_parsed(
    db: Session,
    book: Book,
    cards: list[dict],
    apply_ids: set[str],
) -> list[dict]:
    """按 apply_card_ids 采纳卡片（character 走 sync_character_card）。"""
    card_applied: list[dict] = []
    for card in cards:
        if card.get("status") == "applied":
            continue
        if card.get("id") not in apply_ids:
            continue
        if card.get("type") == "character":
            res = sync_character_card(db, book, {**card, "status": "applied"}, overwrite=True)
            card_applied.append({"type": "character", "ok": True, "character_id": res.id, "card_id": card["id"]})
        else:
            res = apply_card(db, book, {**card, "status": "applied"})
            card_applied.append({**res, "card_id": card["id"]})
        card["status"] = "applied"
    return card_applied
