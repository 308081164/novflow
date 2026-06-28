"""写作页智能体：可读/改全书章节，针对本章或全书协助润色与调整。"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models import Book, Chapter, ChapterPlan, Character, User, Worldview, WriteAgentMessage
from app.services.ai_assist import _chat
from app.services.chapter_content import get_content, set_content
from app.services.prompt_assembler import assemble_context, _format_plot_framework, _format_worldview
from app.services.rule_engine import word_count
from app.services.setup_agent import (
    _build_progress,
    _extract_json_array_after_key,
    _normalize_cards_list,
    apply_card,
    reconcile_cards_with_book,
)
from app.services.character_cards import (
    character_model_to_card,
    character_name,
    ingest_character_cards,
    merge_character_cards_by_name,
    cards_from_db_names,
    sync_character_card,
)
from app.services.system_writing_rules import get_author_preferences
from app.services.agent_constants import (
    ADOPT_KEYWORDS,
    EDIT_KEYWORDS,
    OUTLINE_KEYWORDS,
    OUTLINE_PLAN_KEYWORDS,
    PREMISE_KEYWORDS,
    SETTING_INTENT_KEYWORDS,
    SHOW_KEYWORDS,
    SYNC_EXPAND_KEYWORDS,
    WRITING_PREFS_KEYWORDS,
)
from app.services.agent_intent import (
    edit_failure_reply,
    execute_brainstorm_plain,
    execute_chapter_edit_plain,
    extract_edits_from_messy_text,
    extract_title_from_message,
    finalize_chapter_edit_content,
    is_apply_book_meta_message,
    is_edit_text_message,
    is_meta_summary_content,
    is_valid_chapter_edit_content,
    looks_like_json_edit_payload,
    parse_selection_from_message,
    parse_target_chapter_nos,
    reply_implies_edit_success,
    salvage_edits_from_chapter_sections,
    salvage_reply_from_raw,
    sanitize_chapter_edit_content,
    understand_write_message,
    write_execution_hint,
    diagnose_edit_failure,
)
from app.services.chapter_edit_kernel import apply_edits, revert_snapshots, snapshot_chapter as _snapshot_chapter
from app.services.message_format import assistant_content_for_history as _assistant_content_for_history
from app.services.observability import LLMCallTracker, StreamEmit, log_structured, timed_operation
from app.services.write_agent_cards import (
    adopt_cards_from_parsed,
    finalize_book_meta_apply as _finalize_book_meta_apply,
)
from app.services.write_agent_routing import WriteRouteContext, execute_route
from app.services.context_limits import (
    CHARACTER_SUMMARY_CHARS,
    CONTINUITY_CUR_CHARS,
    CONTINUITY_PREV_CHARS,
    MAX_HISTORY_MESSAGES,
    OUTLINE_PLAN_LINE_CHARS,
    OUTLINE_PLAN_LINES_MAX,
    SNAPSHOT_CHAPTER_CURRENT_CHARS,
    SNAPSHOT_CHAPTER_OTHER_CHARS,
    SNAPSHOT_CHAPTERS_TOTAL_CHARS,
)
from app.services.book_index import (
    build_book_index,
    build_prefetch_context_blocks,
    format_book_index_block,
    index_chapter_scope_hint,
)
from app.services.task_planner import (
    format_task_plan_system_block,
    plan_write_task,
    should_route_chapter_edit,
)
from app.services.write_task_executor import (
    coerce_consistency_apply_understanding,
    was_consistency_analysis_context,
)
from app.services.image_gen import maybe_handle_chat_image
from app.services.write_agent_context import (
    get_context_status,
    list_visible_session_messages,
)

MAX_HISTORY = MAX_HISTORY_MESSAGES
MAX_OTHER_CHAPTER_CHARS = SNAPSHOT_CHAPTER_OTHER_CHARS
OUTLINE_MAX_BATCH = 15
WELCOME_MESSAGE = (
    "我是写作智能体，已加载本书全部设定与章节。可查看/修改角色卡、世界观、大纲与正文；"
    "选中正文后点「加入对话」，或直接描述你想怎么改。对话会保存在本书下，切换章节不会丢失。"
)


def _has_setting_intent(msg: str) -> bool:
    if _is_show_request(msg):
        return True
    if any(k in msg for k in ADOPT_KEYWORDS):
        return True
    return any(k in msg for k in SETTING_INTENT_KEYWORDS)


def _is_text_edit_only(msg: str) -> bool:
    if "【选段" in msg:
        return True
    if any(k in msg for k in EDIT_KEYWORDS) and not _has_setting_intent(msg):
        return True
    return False


def _should_include_cards(msg: str, parsed: dict[str, Any], understanding: dict[str, Any] | None = None) -> bool:
    u = understanding or {}
    intent = u.get("intent", "")
    if intent in ("edit_text", "brainstorm", "discuss") and not parsed.get("apply_card_ids"):
        return False
    if intent == "apply_book_meta":
        return True
    if u.get("allow_cards") is False and not parsed.get("apply_card_ids"):
        return bool(parsed.get("cards")) and intent in ("draft_card", "show_card", "plan_outline")
    if _is_text_edit_only(msg):
        return False
    if intent == "show_card" or u.get("allow_cards"):
        return True
    if _has_setting_intent(msg):
        return True
    if parsed.get("apply_card_ids"):
        return True
    for c in parsed.get("cards") or []:
        if isinstance(c, dict) and c.get("status") == "draft":
            return True
    return False


def _apply_understanding_constraints(
    parsed: dict[str, Any],
    understanding: dict[str, Any],
    *,
    db: Session,
    book: Book,
    msg: str,
) -> dict[str, Any]:
    """按语义理解结果裁剪误输出的 cards / actions / edits。"""
    intent = understanding.get("intent", "general")
    if not understanding.get("allow_edits") or intent != "edit_text":
        if not (intent == "edit_text" or "【选段" in msg):
            parsed["edits"] = []

    if intent in ("consistency_check", "analyze_only", "cross_sync"):
        parsed["edits"] = []
        if intent in ("consistency_check", "analyze_only") and not parsed.get("apply_card_ids"):
            parsed["apply_card_ids"] = []

    if intent != "view_outline":
        if intent in ("brainstorm", "discuss", "edit_text", "show_card", "draft_card", "plan_outline"):
            parsed["actions"] = []
        elif not understanding.get("allow_actions"):
            parsed["actions"] = []

    if intent in ("brainstorm", "discuss", "edit_text"):
        if not understanding.get("allow_cards") and not parsed.get("apply_card_ids"):
            parsed["cards"] = []
            parsed["apply_card_ids"] = []

    if intent == "apply_book_meta":
        parsed["actions"] = []
        parsed["edits"] = []

    if intent == "brainstorm":
        reply = parsed.get("reply", "")
        # 空口承诺但未列出实质内容时标记需重试
        parsed["_needs_brainstorm_retry"] = (
            len(reply) < 80
            or (("如下" in reply or "以下" in reply) and reply.count("\n") < 2 and "《" not in reply)
        )

    if intent == "edit_text" and not parsed.get("edits"):
        parsed["_needs_edit_retry"] = True

    return parsed


def _dedupe_cards(cards: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for c in cards:
        data = c.get("data") or {}
        char_id = data.get("character_id")
        if c.get("type") == "character":
            key = f"character:{c.get('title') or char_id}"
        else:
            key = str(c.get("id") or f"{c.get('type')}:{c.get('title')}")
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _truncate(text: str, limit: int) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[:limit] + "…"


def ensure_write_agent_session(db: Session, book: Book) -> str:
    sid = (book.write_agent_session_id or "").strip()
    if not sid:
        sid = str(uuid.uuid4())
        book.write_agent_session_id = sid
        db.commit()
        db.refresh(book)
    return sid


def _session_messages_query(db: Session, book: Book, session_id: str):
    return (
        db.query(WriteAgentMessage)
        .filter(WriteAgentMessage.book_id == book.id, WriteAgentMessage.session_id == session_id)
        .order_by(WriteAgentMessage.id)
    )


def list_write_agent_messages(db: Session, book: Book) -> list[WriteAgentMessage]:
    session_id = ensure_write_agent_session(db, book)
    msgs = list_visible_session_messages(db, book, session_id)
    if not msgs:
        welcome = WriteAgentMessage(
            book_id=book.id,
            session_id=session_id,
            role="assistant",
            content=WELCOME_MESSAGE,
            cards_json=[],
            actions_json=[],
            meta_json={"welcome": True},
        )
        db.add(welcome)
        db.commit()
        db.refresh(welcome)
        return [welcome]
    return msgs


def mark_write_agent_card_applied(db: Session, book: Book, card_id: str) -> bool:
    """将写作智能体消息中的草案卡片标记为已采纳，避免重复应用。"""
    if not card_id:
        return False
    session_id = ensure_write_agent_session(db, book)
    msgs = (
        db.query(WriteAgentMessage)
        .filter(
            WriteAgentMessage.book_id == book.id,
            WriteAgentMessage.session_id == session_id,
            WriteAgentMessage.role == "assistant",
        )
        .order_by(WriteAgentMessage.id.desc())
        .all()
    )
    for m in msgs:
        raw = m.cards_json or []
        if not isinstance(raw, list):
            continue
        changed = False
        updated: list[dict] = []
        for c in raw:
            if not isinstance(c, dict):
                updated.append(c)
                continue
            item = dict(c)
            if str(item.get("id") or "") == str(card_id) and item.get("status") != "applied":
                item["status"] = "applied"
                changed = True
            updated.append(item)
        if changed:
            m.cards_json = updated
            flag_modified(m, "cards_json")
            db.commit()
            return True
    return False


def start_new_write_agent_session(db: Session, book: Book) -> tuple[str, WriteAgentMessage]:
    session_id = str(uuid.uuid4())
    book.write_agent_session_id = session_id
    welcome = WriteAgentMessage(
        book_id=book.id,
        session_id=session_id,
        role="assistant",
        content=WELCOME_MESSAGE,
        cards_json=[],
        actions_json=[],
        meta_json={"welcome": True},
    )
    db.add(welcome)
    db.commit()
    db.refresh(book)
    db.refresh(welcome)
    return session_id, welcome


def build_history_from_db(db: Session, book: Book, session_id: str) -> list[dict]:
    rows = list_visible_session_messages(db, book, session_id)
    history: list[dict] = []
    for m in rows:
        meta = m.meta_json or {}
        if meta.get("welcome"):
            continue
        if meta.get("context_summary"):
            count = meta.get("archived_count", "?")
            summary = (m.content or "").strip()
            if summary:
                history.append(
                    {
                        "role": "assistant",
                        "content": f"【对话历史摘要 · 已压缩 {count} 条更早消息】\n{summary}",
                    }
                )
            continue
        if m.role == "user":
            content = (m.content or "").strip()
            if content:
                history.append({"role": "user", "content": content})
        elif m.role == "assistant":
            content = _assistant_content_for_history(m)
            if content:
                history.append({"role": "assistant", "content": content})
    return history


def _book_write_snapshot(
    db: Session,
    book: Book,
    current_chapter_no: int,
    draft_content: str | None = None,
) -> dict[str, Any]:
    wv = db.query(Worldview).filter(Worldview.book_id == book.id).first()
    characters = db.query(Character).filter(Character.book_id == book.id).order_by(Character.id).all()
    plans = (
        db.query(ChapterPlan)
        .filter(ChapterPlan.book_id == book.id)
        .order_by(ChapterPlan.chapter_no)
        .all()
    )
    chapters = (
        db.query(Chapter)
        .filter(Chapter.book_id == book.id)
        .order_by(Chapter.chapter_no)
        .all()
    )

    char_lines = [
        f"- {c.name}（{c.role}）：{_truncate(c.summary or c.content, CHARACTER_SUMMARY_CHARS)}"
        for c in characters
    ]
    plan_lines = [
        f"第{p.chapter_no}章 {p.title}：{_truncate(p.plot_points, OUTLINE_PLAN_LINE_CHARS)}"
        for p in plans
        if p.plot_points.strip() or p.title.strip()
    ]

    chapter_blocks: list[str] = []
    for ch in chapters:
        body = draft_content if ch.chapter_no == current_chapter_no and draft_content is not None else get_content(ch)
        if not body.strip():
            chapter_blocks.append(f"【第{ch.chapter_no}章 {ch.title}】（空）")
            continue
        label = "当前编辑中" if ch.chapter_no == current_chapter_no else "已写"
        chapter_blocks.append(
            f"【第{ch.chapter_no}章 {ch.title} · {label} · {word_count(body)}字】\n{_truncate(body, SNAPSHOT_CHAPTER_CURRENT_CHARS if ch.chapter_no == current_chapter_no else MAX_OTHER_CHAPTER_CHARS)}"
        )

    ctx = assemble_context(db, book, current_chapter_no)
    progress = _build_progress(db, book)
    continuity_block = build_continuity_block(
        db, book, current_chapter_no, draft_content=draft_content
    )
    return {
        "book_id": book.id,
        "title": book.title,
        "genre": book.genre,
        "premise": book.premise or book.blurb,
        "blurb": book.blurb or book.premise,
        "target_chapters": book.target_chapters,
        "setup_step": book.setup_step,
        "progress": progress,
        "author_preferences": ctx["author_preferences"],
        "worldview": _format_worldview(wv, book),
        "plot_framework": _format_plot_framework(book.plot_framework),
        "characters": "\n".join(char_lines) if char_lines else "（暂无）",
        "outline_plans": "\n".join(plan_lines[:OUTLINE_PLAN_LINES_MAX]) if plan_lines else "（暂无）",
        "chapters": "\n\n".join(chapter_blocks) if chapter_blocks else "（尚无正文）",
        "current_chapter_no": current_chapter_no,
        "current_plan": ctx["chapter_synopsis"],
        "prev_chapters": ctx["prev_chapters"],
        "nearby_plans": ctx["nearby_plans"],
        "continuity_block": continuity_block,
    }


def build_continuity_block(
    db: Session,
    book: Book,
    chapter_no: int,
    *,
    draft_content: str | None = None,
    for_chapter_no: int | None = None,
) -> str:
    """为改文/润色注入情节连续性上下文。"""
    target = for_chapter_no or chapter_no
    ctx = assemble_context(db, book, target)

    ch = db.query(Chapter).filter(Chapter.book_id == book.id, Chapter.chapter_no == target).first()
    if target == chapter_no and draft_content is not None:
        cur_body = draft_content
    elif ch:
        cur_body = get_content(ch)
    else:
        cur_body = ""

    prev_ch = (
        db.query(Chapter)
        .filter(Chapter.book_id == book.id, Chapter.chapter_no == target - 1)
        .first()
    )
    prev_tail = ""
    if prev_ch:
        prev_body = get_content(prev_ch)
        if prev_body.strip():
            tail = prev_body.strip()
            if len(tail) > CONTINUITY_PREV_CHARS:
                tail = "…\n" + tail[-CONTINUITY_PREV_CHARS:]
            prev_tail = f"第{prev_ch.chapter_no}章《{prev_ch.title}》结尾：\n{tail}"

    next_plan = (
        db.query(ChapterPlan)
        .filter(ChapterPlan.book_id == book.id, ChapterPlan.chapter_no == target + 1)
        .first()
    )
    next_hint = ""
    if next_plan and (next_plan.plot_points or next_plan.title):
        next_hint = f"第{next_plan.chapter_no}章规划：{next_plan.title} — {_truncate(next_plan.plot_points, 400)}"

    lines = [
        "## 【情节连续性 · 改文前必读】",
        "1. 只能写/改**与前文已发生事件一致**的内容，禁止凭空添加前文未描写的动作、后果、人物状态。",
        "2. 用户指出「前文没有…」时，必须删除或改写所有依赖该错误前提的句子，并通读全章排查类似问题。",
        "3. 修改选段时必须与**本章全文 + 上一章结尾**衔接自然，不得自相矛盾。",
        "4. 角色能力/设定以角色卡与正文已写为准，不得临时添加未设定能力。",
        "",
        "### 前文回顾（assemble）",
        ctx["prev_chapters"] or "（无前文）",
    ]
    if prev_tail:
        lines += ["", "### 上一章结尾（重点承接）", prev_tail]
    lines += [
        "",
        f"### 第{target}章大纲/规划",
        ctx["chapter_synopsis"],
        "",
        f"### 第{target}章当前正文（修改基准）",
        _truncate(cur_body.strip(), CONTINUITY_CUR_CHARS) if cur_body.strip() else "（空）",
    ]
    if ctx.get("nearby_plans"):
        lines += ["", "### 相邻章节规划", ctx["nearby_plans"]]
    if next_hint:
        lines += ["", "### 下一章预告（勿提前剧透，仅作方向参考）", next_hint]
    return "\n".join(lines)


def build_continuity_blocks_for_targets(
    db: Session,
    book: Book,
    chapter_nos: list[int],
    *,
    draft_content: str | None,
    focus_chapter_no: int,
    include_all_targets: bool = False,
) -> str:
    nos = sorted(set(n for n in chapter_nos if n > 0))
    if not nos:
        nos = [focus_chapter_no]
    if not include_all_targets and len(nos) > 3:
        nos = nos[:3]
    parts = [
        build_continuity_block(db, book, focus_chapter_no, draft_content=draft_content, for_chapter_no=n)
        for n in nos
    ]
    return "\n\n---\n\n".join(parts)


def _progress_hint(progress: dict[str, Any]) -> str:
    completed = "、".join(progress.get("completed") or []) or "无"
    pending = "、".join(progress.get("pending") or []) or "无"
    return f"""## 创作进度
- 已完成：{completed}
- 待完成：{pending}
- 建议下一步：{progress.get("next_action") or "继续写作"}
- 已存档角色：{'、'.join(progress.get("character_names") or []) or '无'}
- 大纲进度：{progress.get("outline_written", 0)}/{progress.get("outline_target", 0)} 章"""


def _resolve_character_ids(db: Session, book: Book, cards: list[dict]) -> list[dict]:
    """将 AI 返回的 slug 式 character_id 解析为数据库整数 id。"""
    if not cards:
        return cards
    by_name = {c.name: c for c in db.query(Character).filter(Character.book_id == book.id).all()}
    for card in cards:
        if card.get("type") != "character":
            continue
        data = dict(card.get("data") or {})
        cid = data.get("character_id")
        valid_id = False
        if cid is not None:
            try:
                data["character_id"] = int(cid)
                valid_id = True
            except (TypeError, ValueError):
                valid_id = False
        if not valid_id:
            name = data.get("name") or card.get("title")
            if name and name in by_name:
                data["character_id"] = by_name[name].id
            elif "character_id" in data and not valid_id:
                data.pop("character_id", None)
        card["data"] = data
    return cards


def _is_show_request(msg: str) -> bool:
    return any(k in msg for k in SHOW_KEYWORDS)


def _is_outline_plan_request(msg: str) -> bool:
    return any(k in msg for k in OUTLINE_PLAN_KEYWORDS)


def _is_outline_view_request(msg: str) -> bool:
    if not any(k in msg for k in OUTLINE_KEYWORDS):
        return False
    if _is_outline_plan_request(msg):
        return False
    if any(k in msg for k in EDIT_KEYWORDS) and not any(
        k in msg for k in ("调出", "查看", "展示", "显示", "列出", "打开", "看看")
    ):
        return False
    return _is_show_request(msg) or msg.strip() in ("大纲", "章节规划", "写作大纲")


def _is_writing_prefs_request(msg: str) -> bool:
    return any(k in msg for k in WRITING_PREFS_KEYWORDS)


def _cap_outline_chapters(cards: list[dict], max_chapters: int = OUTLINE_MAX_BATCH) -> list[dict]:
    out: list[dict] = []
    for card in cards:
        if card.get("type") != "outline":
            out.append(card)
            continue
        data = dict(card.get("data") or {})
        chapters = data.get("chapters") or []
        if isinstance(chapters, list) and len(chapters) > max_chapters:
            data["chapters"] = chapters[:max_chapters]
        out.append({**card, "data": data})
    return out


def _outline_view_action(book_id: int, outline_written: int) -> dict[str, Any]:
    label = f"查看章节大纲（共 {outline_written} 章）" if outline_written else "查看章节大纲"
    return {"type": "open_outline", "label": label}


def _lookup_db_cards(db: Session, book: Book, message: str) -> list[dict]:
    """从数据库调出已有设定为卡片（展示用）。"""
    cards: list[dict] = []
    msg = message

    if _is_writing_prefs_request(msg) and _is_show_request(msg):
        prefs = get_author_preferences(book)
        cards.append(
            {
                "id": "writing_prefs_current",
                "type": "writing_prefs",
                "title": "本书写作偏好",
                "status": "applied",
                "data": {"content": prefs or "（尚未配置）", "mode": "replace"},
            }
        )

    if any(k in msg for k in PREMISE_KEYWORDS) and _is_show_request(msg):
        synopsis = (book.premise or book.blurb or "").strip()
        cards.append(
            {
                "id": "premise_current",
                "type": "premise",
                "title": book.title or "作品信息",
                "status": "applied",
                "data": {
                    "title": book.title,
                    "genre": book.genre,
                    "premise": synopsis,
                    "blurb": book.blurb or synopsis,
                    "target_chapters": book.target_chapters,
                },
            }
        )

    if not _is_show_request(message):
        seen_early: set[str] = set()
        out_early: list[dict] = []
        for c in cards:
            cid = c.get("id", "")
            if cid and cid not in seen_early:
                seen_early.add(cid)
                out_early.append(c)
        return out_early
    chars = db.query(Character).filter(Character.book_id == book.id).order_by(Character.id).all()

    for c in chars:
        if c.name and len(c.name) >= 2 and c.name in msg:
            cards.append(character_model_to_card(c))

    if any(k in msg for k in ("男主", "主角", "主人公")):
        found = [
            c
            for c in chars
            if c.role in ("protagonist", "主角", "男主")
            or "男主" in (c.role or "")
            or "主角" in (c.role or "")
            or "主人公" in (c.role or "")
        ]
        if found and not any(card.get("data", {}).get("character_id") == found[0].id for card in cards):
            cards.append(character_model_to_card(found[0]))

    if "反派" in msg or "女主" in msg:
        role_map = {"反派": ("antagonist", "反派"), "女主": ("support", "女主角")}
        for kw, roles in role_map.items():
            if kw in msg:
                for c in chars:
                    if c.role in roles or kw in (c.summary or ""):
                        if not any(x.get("id") == f"char_{c.id}" for x in cards):
                            cards.append(character_model_to_card(c))

    if any(k in msg for k in ("全部角色", "所有角色", "角色列表")):
        cards = [character_model_to_card(c) for c in chars]

    if "世界观" in msg:
        wv = db.query(Worldview).filter(Worldview.book_id == book.id).first()
        if wv:
            cards.append(
                {
                    "id": f"wv_{wv.id}",
                    "type": "worldview",
                    "title": "世界观",
                    "status": "applied",
                    "data": {
                        "era": wv.era,
                        "setting": wv.setting,
                        "tone": wv.tone,
                        "timeline_text": wv.timeline_text,
                        "taboos": wv.taboos,
                        "content": wv.content,
                    },
                }
            )

    if any(k in msg for k in ("剧情框架", "长线", "单元剧")):
        pf = book.plot_framework
        if isinstance(pf, dict) and pf:
            cards.append(
                {
                    "id": "plot_framework",
                    "type": "plot",
                    "title": str(pf.get("title") or "长线剧情框架"),
                    "status": "applied",
                    "data": pf,
                }
            )

    # 大纲查看不在对话中塞卡片，改由 actions 跳转专属页面

    seen: set[str] = set()
    out: list[dict] = []
    for c in cards:
        cid = c.get("id", "")
        if cid and cid not in seen:
            seen.add(cid)
            out.append(c)
    return out


def _system_prompt(snapshot: dict[str, Any]) -> str:
    progress = snapshot.get("progress") or {}
    return f"""你是 NovFlow 写作智能体，具备与「AI 创作助手」相同的设定能力，并可阅读/修改全书章节正文。

## 权限
- 阅读：世界观、角色、大纲、长线框架、全部章节
- 修改：章节正文（edits）、设定卡片（cards + apply_card_ids 写入）
- 当前聚焦：第 {snapshot["current_chapter_no"]} 章

## 作品档案
- 书名：{snapshot["title"]}
- 类型：{snapshot.get("genre") or "未设定"}
- 梗概：{_truncate(str(snapshot.get("blurb") or ""), 500)}
- 阶段：第 {snapshot.get("setup_step", 5)} 步

{_progress_hint(progress)}

## 本书写作偏好
{snapshot["author_preferences"] or "（尚未配置，可在「写作偏好与语料库」页面编辑）"}

> 平台合规与语言规范由系统自动注入，无需在此维护。

## 世界观（摘要）
{snapshot["worldview"]}

## 长线框架
{snapshot["plot_framework"]}

## 角色（摘要）
{snapshot["characters"]}

## 章节大纲（摘要）
{snapshot["outline_plans"]}

## 正文快照
{snapshot["chapters"][:SNAPSHOT_CHAPTERS_TOTAL_CHARS]}

## 本章规划
{snapshot["current_plan"]}

## 情节连续性（改文/润色时最高优先级）
- 必须严格承接前文与本章已有正文；改文时会另附「情节连续性」上下文，务必逐条遵守。
- 用户指出事实错误（如「前文没有…」）时，通篇排查并修正所有相关表述。

## 输出格式（必须合法 JSON）
{{
  "reply": "给用户看的说明，可含追问；有 cards 时不要重复粘贴卡片全文",
  "cards": [
    {{
      "id": "唯一字符串",
      "type": "premise|worldview|character|outline|plot|writing_prefs",
      "title": "卡片标题",
      "status": "draft",
      "data": {{ }}
    }}
  ],
  "apply_card_ids": [],
  "actions": [
    {{ "type": "open_outline|open_overview|open_resources", "label": "按钮文字" }}
  ],
  "edits": [
    {{
      "chapter_no": 1,
      "title": "可选",
      "content": "完整章节 Markdown",
      "reason": "说明"
    }}
  ]
}}

## cards.data 类型（与创作助手一致）
- premise: {{ "title", "genre", "premise", "blurb", "target_chapters" }}
- worldview: {{ "era", "setting", "tone", "timeline_text", "taboos", "content" }}
- character: {{ "character_id": 已有id或null, "name", "role", "summary", "voice_notes", "content" }}
- outline: {{ "chapters": [{{ "chapter_no", "title", "plot_points", "scene", "comedy_core", "cast", "events" }}] }}
- plot: {{ "summary", "total_chapters", "style", "phases", "units" }}
- writing_prefs: {{ "content": "Markdown 写作偏好", "mode": "replace|append" }}

## 规则
1. 用户要「调出/查看/展示」**角色卡、世界观、写作偏好、作品信息（书名/简介）**时，在 cards 输出完整卡片（已有存档设 status=applied）。作品信息用 type=premise，含 title、genre、premise/blurb。
2. 用户要修改书名、简介、类型时，输出 premise 卡片草案；采纳后写入书籍。
3. 用户要「查看/调出/展示」**大纲/章节规划**时：**禁止**输出 outline 卡片；在 actions 中给出 `open_outline` 跳转按钮，reply 简要说明章数即可。
4. 用户要**规划/新增**大纲章节时，才输出 outline 卡片（每批最多 {OUTLINE_MAX_BATCH} 章）；讨论出新设定时用 cards 给草案；用户确认「采纳」时把 id 放入 apply_card_ids。
5. 改正文/润色/删改选段时**只用 edits**，cards 与 apply_card_ids **必须为空数组**，不要附带无关角色卡。
6. 改正文用 edits，单次最多 3 章；优先第 {snapshot["current_chapter_no"]} 章。
6b. **edits[].content 必须是修改后的完整章节小说正文**（Markdown），禁止把「已修正…删除该句…通读全章…」等改动说明/操作摘要放入 content；这类说明只写在 reply。
7. 一次最多 3 张 cards；character 每批最多 3 个。
8. 可规划大纲、设计角色、完善世界观，与创作助手能力相同。
9. reply 必填；禁止 [已输出卡片...] 内部标记。"""


def _parse_edits_list(edits: Any) -> list[dict]:
    if not isinstance(edits, list):
        return []
    clean: list[dict] = []
    for e in edits[:3]:
        if not isinstance(e, dict):
            continue
        no = int(e.get("chapter_no") or 0)
        raw_content = str(e.get("content") or "").strip()
        content = sanitize_chapter_edit_content(raw_content, chapter_no=no if no >= 1 else None)
        if not content:
            continue
        clean.append(
            {
                "chapter_no": no,
                "title": str(e.get("title") or "").strip() or None,
                "content": content,
                "reason": str(e.get("reason") or "").strip(),
            }
        )
    return clean


def _parse_actions_list(actions_raw: Any) -> list[dict]:
    actions: list[dict] = []
    if not isinstance(actions_raw, list):
        return actions
    for a in actions_raw[:5]:
        if not isinstance(a, dict):
            continue
        t = str(a.get("type") or "").strip()
        label = str(a.get("label") or "").strip()
        if t and label:
            item: dict[str, Any] = {"type": t, "label": label}
            if a.get("chapter_no") is not None:
                item["chapter_no"] = int(a["chapter_no"])
            actions.append(item)
    return actions


def _finalize_parsed(data: dict[str, Any], raw: str) -> dict[str, Any]:
    reply = str(data.get("reply") or "").strip()
    if not reply:
        reply = salvage_reply_from_raw(raw)
    if not reply:
        reply = re.sub(r"^\s*\{[\s\S]*", "", raw.strip()).strip()[:8000]
    cards_raw = data.get("cards") or []
    if not isinstance(cards_raw, list):
        cards_raw = []
    apply_ids = data.get("apply_card_ids") or []
    if not isinstance(apply_ids, list):
        apply_ids = []
    return {
        "reply": reply or "已完成分析。",
        "edits": _parse_edits_list(data.get("edits")),
        "cards": _cap_outline_chapters(_normalize_cards_list(cards_raw)[:3]),
        "apply_card_ids": [str(x) for x in apply_ids if x],
        "actions": _parse_actions_list(data.get("actions")),
    }


def _strip_edit_wrapper(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:markdown|md|text|json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    lines = t.split("\n")
    while lines and any(lines[0].strip().startswith(p) for p in ("以下是", "润色后", "修改后", "已润色", "改写后")):
        lines.pop(0)
    return "\n".join(lines).strip()


def _reply_looks_like_chapter_body(reply: str, *, min_len: int = 120) -> bool:
    body = _strip_edit_wrapper(reply)
    if is_meta_summary_content(body):
        return False
    return len(body) >= min_len


def _chapter_contents_map(
    db: Session,
    book: Book,
    chapter_nos: list[int],
    *,
    draft_content: str | None,
    focus_chapter_no: int,
) -> dict[int, str]:
    out: dict[int, str] = {}
    for no in chapter_nos:
        if no == focus_chapter_no and draft_content is not None:
            out[no] = draft_content
            continue
        snap = _snapshot_chapter(db, book, no)
        if snap:
            out[no] = str(snap.get("content") or "")
    return out


def _edit_context_from_understanding(understanding: dict[str, Any]) -> dict[str, Any]:
    return {
        "edit_scope": str(understanding.get("edit_scope") or "chapter"),
        "selection_quote": str(understanding.get("selection_quote") or "").strip(),
    }


def _normalize_edits_for_chapter(
    edits: list[dict],
    target_chapter_nos: list[int],
    fallback_chapter_no: int,
    chapter_contents: dict[int, str] | None = None,
    edit_context: dict[str, Any] | None = None,
) -> list[dict]:
    out: list[dict] = []
    allowed = set(n for n in target_chapter_nos if n > 0)
    single_target = len(allowed) == 1
    contents = chapter_contents or {}
    ctx = edit_context or {}
    edit_scope = str(ctx.get("edit_scope") or "chapter")
    selection_quote = str(ctx.get("selection_quote") or "").strip()

    for e in edits:
        if not isinstance(e, dict):
            continue
        no = int(e.get("chapter_no") or 0)
        if no < 1:
            if single_target:
                no = next(iter(allowed))
            elif len(allowed) == 0 and fallback_chapter_no > 0:
                no = fallback_chapter_no
            else:
                continue
        if allowed and no not in allowed:
            continue
        raw_content = str(e.get("content") or "").strip()
        orig = (contents.get(no) or "").strip()
        content = finalize_chapter_edit_content(
            raw_content,
            chapter_no=no,
            original_content=orig,
            edit_scope=edit_scope,
            selection_quote=selection_quote,
        )
        if not content or looks_like_json_edit_payload(content):
            continue
        out.append(
            {
                "chapter_no": no,
                "title": str(e.get("title") or "").strip() or None,
                "content": content,
                "reason": str(e.get("reason") or "").strip() or "智能体改写",
            }
        )
    return out[:3]


def _salvage_edits_from_raw_json(
    raw: str,
    target_chapter_nos: list[int],
    fallback_chapter_no: int,
    chapter_contents: dict[int, str] | None = None,
    edit_context: dict[str, Any] | None = None,
) -> list[dict]:
    edits_raw = _extract_json_array_after_key(raw or "", "edits")
    if isinstance(edits_raw, list) and edits_raw:
        return _normalize_edits_for_chapter(
            edits_raw, target_chapter_nos, fallback_chapter_no, chapter_contents, edit_context
        )
    messy = extract_edits_from_messy_text(raw or "")
    if messy:
        return _normalize_edits_for_chapter(
            messy, target_chapter_nos, fallback_chapter_no, chapter_contents, edit_context
        )
    return []


def _salvage_edits_from_reply(
    reply: str,
    target_chapter_nos: list[int],
    fallback_chapter_no: int,
    original_content: str,
    edit_context: dict[str, Any] | None = None,
) -> list[dict]:
    allowed = [n for n in target_chapter_nos if n > 0]
    if len(allowed) > 1:
        return []
    no = allowed[0] if len(allowed) == 1 else fallback_chapter_no
    if no < 1:
        return []
    ctx = edit_context or {}
    body = finalize_chapter_edit_content(
        _strip_edit_wrapper(reply),
        chapter_no=no,
        original_content=original_content,
        edit_scope=str(ctx.get("edit_scope") or "chapter"),
        selection_quote=str(ctx.get("selection_quote") or ""),
    )
    if not body:
        return []
    if original_content.strip() and body.strip() == original_content.strip():
        return []
    return [{"chapter_no": no, "content": body, "reason": "从 reply 回收正文"}]


def _recover_chapter_edits(
    parsed: dict[str, Any],
    raw: str,
    target_chapter_nos: list[int],
    fallback_chapter_no: int,
    original_content: str,
    chapter_contents: dict[int, str] | None = None,
    edit_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """补全 edits：JSON 损坏或模型误把正文放在 reply 时回收（带安全校验）。"""
    edits = _normalize_edits_for_chapter(
        list(parsed.get("edits") or []),
        target_chapter_nos,
        fallback_chapter_no,
        chapter_contents,
        edit_context,
    )
    if not edits:
        edits = _salvage_edits_from_raw_json(
            raw, target_chapter_nos, fallback_chapter_no, chapter_contents, edit_context
        )
    reply_body = str(parsed.get("reply") or "")
    if not edits and reply_body.strip():
        edits = salvage_edits_from_chapter_sections(
            reply_body, target_chapter_nos, chapter_contents, edit_context
        )
    if not edits and _reply_looks_like_chapter_body(reply_body):
        edits = _salvage_edits_from_reply(
            reply_body,
            target_chapter_nos,
            fallback_chapter_no,
            original_content,
            edit_context,
        )
    if edits:
        parsed = dict(parsed)
        parsed["edits"] = edits
        parsed.pop("_needs_edit_retry", None)
        reply = str(parsed.get("reply") or "").strip()
        if _reply_looks_like_chapter_body(reply) and len(reply) > 500:
            nos = ", ".join(str(e["chapter_no"]) for e in edits)
            parsed["reply"] = f"已修改第 {nos} 章并写入编辑器。"
    return parsed


def _expand_edits_from_dirty_payloads(edits: list[dict]) -> list[dict]:
    """若某条 edit.content 内嵌多章 JSON，拆成多条干净 edit。"""
    expanded: list[dict] = []
    for e in edits:
        raw = str(e.get("content") or "")
        if looks_like_json_edit_payload(raw):
            extracted = extract_edits_from_messy_text(raw)
            if extracted:
                expanded.extend(extracted)
                continue
        expanded.append(e)
    return expanded


def _coerce_edit_understanding(
    msg: str,
    understanding: dict[str, Any],
    focus_chapter_no: int,
) -> dict[str, Any]:
    target_nos = parse_target_chapter_nos(msg, focus_chapter_no)
    if understanding.get("intent") != "edit_text" and not is_edit_text_message(msg):
        if target_nos and target_nos != [focus_chapter_no]:
            u = dict(understanding)
            u["target_chapter_nos"] = target_nos
            return u
        return understanding
    u = dict(understanding)
    u["intent"] = "edit_text"
    u["topic"] = "chapter"
    u["allow_edits"] = True
    u["allow_cards"] = False
    u["allow_actions"] = False
    u["target_chapter_nos"] = target_nos

    if "【选段" in msg:
        sel_ch, sel_quote = parse_selection_from_message(msg)
        u["edit_scope"] = "selection"
        if sel_quote:
            u["selection_quote"] = sel_quote
        if sel_ch:
            u["target_chapter_nos"] = [sel_ch]
    elif len(target_nos) > 1:
        u["edit_scope"] = "multi_chapter"
    else:
        u.setdefault("edit_scope", "chapter")

    u.setdefault("must_do", [])
    u.setdefault("must_not_do", [])
    if u.get("edit_scope") == "selection":
        u["must_do"] = list(
            dict.fromkeys(
                [
                    "只修改用户选中的段落，其余正文保持原样",
                    "edits[].content 必须是整章完整正文",
                    *(u.get("must_do") or []),
                ]
            )
        )[:8]
    else:
        u["must_do"] = list(
            dict.fromkeys(
                u["must_do"]
                + [
                    f"分别修改第 {target_nos} 章" if len(target_nos) > 1 else f"修改第 {target_nos[0]} 章",
                    "edits 中每条含正确 chapter_no 与完整正文",
                ]
            )
        )[:8]
    u["must_not_do"] = list(
        dict.fromkeys(
            u["must_not_do"]
            + ["禁止把改动摘要写入章节", "禁止写入未指定章节", "禁止编造前文未发生的事件"]
        )
    )[:8]
    return u


def _coerce_targets_from_index(
    msg: str,
    understanding: dict[str, Any],
    focus_chapter_no: int,
    book_index: dict[str, Any],
) -> dict[str, Any]:
    """模糊短句改文请求：从索引推断默认章范围。"""
    u = dict(understanding)
    if u.get("intent") in ("consistency_check", "cross_sync", "analyze_only"):
        u.setdefault("target_chapter_nos", [])
        return u
    if u.get("target_chapter_nos"):
        return u
    if u.get("intent") != "edit_text":
        return u
    stripped = (msg or "").strip()
    if re.search(r"第\s*\d+", stripped):
        return u
    if len(stripped) > 48:
        return u
    if any(k in stripped for k in SYNC_EXPAND_KEYWORDS):
        return u
    u["target_chapter_nos"] = [focus_chapter_no]
    u.setdefault("edit_scope", "chapter")
    hint = index_chapter_scope_hint(book_index)
    u["summary"] = (u.get("summary") or stripped) + f"（索引推断：聚焦第{focus_chapter_no}章 · {hint}）"
    return u

def _parse_agent_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty response")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    blob_start = text.find("{")
    blob_end = text.rfind("}")
    data: dict[str, Any] | None = None
    if blob_start >= 0 and blob_end > blob_start:
        try:
            loaded = json.loads(text[blob_start : blob_end + 1])
            if isinstance(loaded, dict):
                data = loaded
        except json.JSONDecodeError:
            pass
    if data is None:
        reply_m = re.search(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
        salvaged_edits = extract_edits_from_messy_text(text)
        if reply_m or salvaged_edits:
            data = {
                "reply": reply_m.group(1).replace("\\n", "\n").replace('\\"', '"') if reply_m else "",
                "edits": salvaged_edits,
                "cards": [],
                "apply_card_ids": [],
                "actions": [],
            }
        elif not text.startswith("{"):
            return _finalize_parsed({"reply": text}, text)
        else:
            salvaged = salvage_reply_from_raw(text)
            if salvaged:
                return _finalize_parsed({"reply": salvaged}, text)
            raise ValueError("unparseable json")
    return _finalize_parsed(data, text)


def _is_parse_failure_reply(reply: str) -> bool:
    t = (reply or "").strip()
    if not t:
        return True
    return t in ("解析失败，请重试。", "解析失败")


MAX_SEQUENTIAL_CHAPTERS = 5


def _expand_sync_target_chapters(
    db: Session,
    book: Book,
    message: str,
    target_nos: list[int],
) -> list[int]:
    """「同步/全书/逻辑一致」类请求：扩展为所有已有正文的章节。"""
    msg = (message or "").strip()
    if len(target_nos) > 1:
        return target_nos
    if re.search(r"第\s*\d+", msg):
        return target_nos
    if not any(k in msg for k in SYNC_EXPAND_KEYWORDS):
        return target_nos
    nums: list[int] = []
    for ch in db.query(Chapter).filter(Chapter.book_id == book.id).order_by(Chapter.chapter_no):
        text = get_content(ch).strip()
        if len(text) >= 100:
            nums.append(ch.chapter_no)
    return nums if nums else target_nos


def _build_chapter_edit_messages(
    chapter_no: int,
    user_message: str,
    original_content: str,
    understanding: dict[str, Any],
    *,
    retry: bool = False,
    index_slice: str = "",
) -> list[dict]:
    """构造单章改写的精简消息（不含历史分析，避免模型继续输出说明）。"""
    hint = write_execution_hint(understanding, user_message)
    mode_hint = (
        f"\n\n【独立章节任务 · 第 {chapter_no} 章】"
        "你的输出必须是且仅是修改后的**完整小说章节正文**。"
        "从 # 第NNN章 标题行（若原文有）或第一句正文开始，到章末结束。"
        "禁止输出 JSON、禁止改动说明、禁止分析、禁止清单、禁止「以下是修改后正文」。"
    )
    if retry:
        mode_hint += (
            "\n\n【重试 · 上次不合格】你必须直接输出完整章节正文全文。"
            "不要任何前言、总结或点评。第一个字符就是正文内容。"
        )
    msgs: list[dict] = [
        {"role": "system", "content": hint + mode_hint},
    ]
    if index_slice.strip():
        msgs.append({"role": "system", "content": index_slice.strip()})
    msgs.append({"role": "user", "content": user_message.strip()})
    orig = (original_content or "").strip()
    if orig:
        msgs.append(
            {
                "role": "user",
                "content": f"【第 {chapter_no} 章完整原文 — 请修改后输出完整正文】\n{orig}",
            }
        )
    return msgs


async def _generate_single_chapter_edit(
    user: User,
    messages: list[dict],
    chapter_no: int,
    understanding: dict[str, Any],
    user_message: str,
    original_content: str,
    *,
    edit_scope: str = "chapter",
    selection_quote: str = "",
    index_slice: str = "",
    llm_tracker: LLMCallTracker | None = None,
) -> tuple[str | None, str]:
    """为单章调用 LLM 生成完整修改后正文。返回 (正文, 失败原因)。"""
    del messages  # 不使用含历史分析的完整对话，改用精简消息
    from app.services.observability import tracked_chat

    async def _attempt(retry: bool) -> tuple[str | None, str, str]:
        plain_msgs = _build_chapter_edit_messages(
            chapter_no,
            user_message,
            original_content,
            understanding,
            retry=retry,
            index_slice=index_slice,
        )
        if edit_scope == "selection" and selection_quote:
            plain_msgs.append(
                {
                    "role": "system",
                    "content": f"【选段修改】只改此段，但必须输出整章完整正文：\n{selection_quote[:800]}",
                }
            )
        if llm_tracker:
            text = await tracked_chat(
                llm_tracker,
                user,
                plain_msgs,
                purpose=f"chapter_edit_{chapter_no}" + ("_retry" if retry else ""),
                temperature=0.35 if retry else 0.45,
                max_tokens=16384,
                json_object=False,
            )
        else:
            text = await _chat(user, plain_msgs, temperature=0.35 if retry else 0.45, max_tokens=16384, json_object=False)
        body = (text or "").strip()
        orig = (original_content or "").strip()

        embedded = extract_edits_from_messy_text(body)
        if embedded:
            for e in embedded:
                if int(e.get("chapter_no") or 0) in (0, chapter_no):
                    cand = str(e.get("content") or "").strip()
                    finalized = finalize_chapter_edit_content(
                        cand,
                        chapter_no=chapter_no,
                        original_content=orig,
                        edit_scope=edit_scope,
                        selection_quote=selection_quote,
                    )
                    if finalized:
                        return finalized, "", body

        finalized = finalize_chapter_edit_content(
            body,
            chapter_no=chapter_no,
            original_content=orig,
            edit_scope=edit_scope,
            selection_quote=selection_quote,
        )
        if finalized:
            return finalized, "", body
        return None, diagnose_edit_failure(body, orig, chapter_no), body

    result, reason, _ = await _attempt(retry=False)
    if result:
        return result, ""
    result, reason2, _ = await _attempt(retry=True)
    if result:
        return result, ""
    return None, reason2 or reason


async def execute_sequential_chapter_edits(
    db: Session,
    book: Book,
    user: User,
    messages: list[dict],
    target_chapter_nos: list[int],
    understanding: dict[str, Any],
    user_message: str,
    chapter_contents: dict[int, str],
    edit_context: dict[str, Any],
    *,
    focus_chapter_no: int | None = None,
    editor_draft: str | None = None,
    stream_emit: StreamEmit | None = None,
    llm_tracker: LLMCallTracker | None = None,
) -> dict[str, Any]:
    """逐章独立生成并立即写入，每章一次 LLM 调用，避免多章任务互相干扰。"""
    all_targets = [n for n in (target_chapter_nos or []) if n > 0]
    batch = all_targets[:MAX_SEQUENTIAL_CHAPTERS]
    remaining = all_targets[MAX_SEQUENTIAL_CHAPTERS:]

    edit_scope = str(edit_context.get("edit_scope") or understanding.get("edit_scope") or "chapter")
    selection_quote = str(edit_context.get("selection_quote") or understanding.get("selection_quote") or "")

    book_index = build_book_index(
        db,
        book,
        all_targets,
        draft_content=editor_draft,
        focus_chapter_no=focus_chapter_no or (batch[0] if batch else None),
    )

    contents = dict(chapter_contents or {})
    all_edits: list[dict] = []
    all_applied: list[dict] = []
    all_revert: list[dict] = []
    report: list[str] = []

    for no in batch:
        if stream_emit:
            stream_emit("progress", {"chapter_no": no, "status": "generating"})
        orig = (contents.get(no) or "").strip()
        if not orig:
            snap = _snapshot_chapter(db, book, no)
            orig = str(snap.get("content") or "").strip() if snap else ""
            contents[no] = orig

        single_u = {
            **understanding,
            "target_chapter_nos": [no],
            "edit_scope": "selection" if edit_scope == "selection" else "chapter",
        }
        index_slice = format_book_index_block(
            book_index,
            target_chapter_nos=[no],
            slice_for_chapter=no,
            compact=True,
        )
        finalized, fail_reason = await _generate_single_chapter_edit(
            user,
            messages,
            no,
            single_u,
            user_message,
            orig,
            edit_scope=edit_scope if edit_scope == "selection" else "chapter",
            selection_quote=selection_quote if edit_scope == "selection" else "",
            index_slice=index_slice,
            llm_tracker=llm_tracker,
        )

        if not finalized:
            report.append(f"❌ 第 {no} 章：{fail_reason or '未能生成有效正文'}")
            if stream_emit:
                stream_emit("progress", {"chapter_no": no, "status": "failed", "reason": fail_reason})
            continue
        if orig and finalized.strip() == orig.strip():
            report.append(f"⏭ 第 {no} 章：正文无变化，已跳过")
            if stream_emit:
                stream_emit("progress", {"chapter_no": no, "status": "skipped"})
            continue

        applied, snaps = apply_edits(
            db,
            book,
            [{"chapter_no": no, "content": finalized, "reason": "智能体逐章改写"}],
            chapter_contents=contents,
            edit_context={**edit_context, "edit_scope": "chapter"},
        )
        if applied:
            all_applied.extend(applied)
            all_revert.extend(snaps)
            all_edits.append({"chapter_no": no, "content": finalized, "reason": "智能体逐章改写"})
            ch = db.query(Chapter).filter(Chapter.book_id == book.id, Chapter.chapter_no == no).first()
            if ch:
                contents[no] = get_content(ch)
            wc = applied[-1].get("word_count", 0)
            report.append(f"✅ 第 {no} 章：已写入（{wc} 字）")
            if stream_emit:
                stream_emit("progress", {"chapter_no": no, "status": "applied", "word_count": wc})
        else:
            report.append(f"❌ 第 {no} 章：正文校验未通过，未写入")
            if stream_emit:
                stream_emit("progress", {"chapter_no": no, "status": "failed"})

    if not all_applied:
        detail = "**逐章处理结果**\n" + "\n".join(report) if report else edit_failure_reply(
            edit_scope=edit_scope,
            target_chapter_nos=all_targets,
        )
        if report:
            detail += "\n\n正文未被修改。请尝试缩小范围（如「先同步第1-3章」）或指定要统一的设定点。"
        return {
            "reply": detail,
            "edits": [],
            "applied": [],
            "revert_snapshots": [],
        }

    reply = "**逐章处理结果**\n" + "\n".join(report)
    if remaining:
        reply += (
            f"\n\n⏳ 本次已处理 {len(batch)} 章；剩余第 "
            f"{', '.join(str(n) for n in remaining)} 章。"
            "请发送「继续同步剩余章节」继续。"
        )
    else:
        reply += "\n\n请在编辑器中查看变更高亮（绿=新增、红=删除、黄=修改）。"

    return {
        "reply": reply,
        "edits": all_edits,
        "applied": all_applied,
        "revert_snapshots": all_revert,
    }


async def chat_turn(
    db: Session,
    user: User,
    book: Book,
    *,
    message: str,
    chapter_no: int,
    draft_content: str | None = None,
    history: list[dict] | None = None,
    user_meta: dict | None = None,
    stream_emit: StreamEmit | None = None,
) -> dict[str, Any]:
    llm_tracker = LLMCallTracker()
    session_id = ensure_write_agent_session(db, book)
    db_history = build_history_from_db(db, book, session_id)
    snapshot = _book_write_snapshot(db, book, chapter_no, draft_content)
    merged_history = db_history if db_history else (history or [])

    def _lightweight_index_hint() -> str:
        plan_count = db.query(ChapterPlan).filter(ChapterPlan.book_id == book.id).count()
        ch_count = db.query(Chapter).filter(Chapter.book_id == book.id).count()
        return f"本书约 {plan_count} 章规划、{ch_count} 章正文；当前聚焦第 {chapter_no} 章"

    snapshot["book_index_hint"] = _lightweight_index_hint()

    # 阶段一：语义理解
    understanding = await understand_write_message(user, message.strip(), merged_history, snapshot)
    last_preview = ""
    for h in reversed(merged_history):
        if h.get("role") == "assistant":
            last_preview = str(h.get("content") or "")[:500]
            break
    understanding = coerce_consistency_apply_understanding(
        message.strip(),
        merged_history,
        understanding,
        last_assistant_preview=last_preview,
    )
    understanding = _coerce_edit_understanding(message.strip(), understanding, chapter_no)
    if user_meta and str(user_meta.get("quote") or "").strip():
        understanding["edit_scope"] = "selection"
        understanding["selection_quote"] = str(user_meta["quote"]).strip()
        if not understanding.get("target_chapter_nos"):
            understanding["target_chapter_nos"] = [chapter_no]
    lint_issues = user_meta.get("lint_issues") if user_meta else None
    if isinstance(lint_issues, list) and lint_issues:
        understanding["lint_issues"] = lint_issues
        rules = [str(x.get("rule_id") or "") for x in lint_issues if isinstance(x, dict)]
        msgs = [str(x.get("message") or "") for x in lint_issues if isinstance(x, dict)]
        understanding["must_do"] = list(
            dict.fromkeys(
                (understanding.get("must_do") or [])
                + [f"修复 lint 违规：{rid} — {msg}" for rid, msg in zip(rules, msgs) if rid and msg]
                + ["按本书写作规约修正选段，输出整章完整正文"]
            )
        )[:8]
    edit_context = _edit_context_from_understanding(understanding)
    intent = understanding.get("intent", "general")

    target_chapter_nos: list[int] = list(understanding.get("target_chapter_nos") or []) or [chapter_no]
    if intent not in ("consistency_check", "cross_sync", "analyze_only"):
        target_chapter_nos = _expand_sync_target_chapters(db, book, message.strip(), target_chapter_nos)
    else:
        target_chapter_nos = []
    if len(target_chapter_nos) > 1 and should_route_chapter_edit(intent, {"execution_mode": "chapter_edit"}):
        understanding = {**understanding, "target_chapter_nos": target_chapter_nos, "edit_scope": "multi_chapter"}

    index_chapters = sorted(set(target_chapter_nos or [chapter_no]))
    book_index = build_book_index(
        db,
        book,
        index_chapters,
        draft_content=draft_content,
        focus_chapter_no=chapter_no,
    )
    understanding = _coerce_targets_from_index(message.strip(), understanding, chapter_no, book_index)
    task_plan = plan_write_task(message.strip(), understanding, book_index)
    understanding = {**understanding, "task_plan": task_plan, "affected_resources": task_plan.get("resources") or []}
    execution_mode = str(task_plan.get("execution_mode") or "default")
    chapter_contents = _chapter_contents_map(
        db, book, target_chapter_nos, draft_content=draft_content, focus_chapter_no=chapter_no
    )
    is_sync = (
        should_route_chapter_edit(intent, task_plan)
        and any(k in message.strip() for k in SYNC_EXPAND_KEYWORDS)
        and len(target_chapter_nos) > 1
    )
    index_block = format_book_index_block(
        book_index,
        target_chapter_nos=target_chapter_nos or [chapter_no],
        compact=intent == "edit_text",
    )
    prefetch_blocks = build_prefetch_context_blocks(book_index, task_plan.get("resources") or [])
    task_plan_block = format_task_plan_system_block(task_plan)

    messages: list[dict] = [{"role": "system", "content": _system_prompt(snapshot)}]
    messages.append({"role": "system", "content": index_block})
    if task_plan_block.strip():
        messages.append({"role": "system", "content": task_plan_block})
    for block in prefetch_blocks:
        messages.append({"role": "system", "content": block})
    messages.append({"role": "system", "content": write_execution_hint(understanding, message.strip())})
    if intent == "edit_text" and should_route_chapter_edit(intent, task_plan):
        continuity = build_continuity_blocks_for_targets(
            db,
            book,
            target_chapter_nos,
            draft_content=draft_content,
            focus_chapter_no=chapter_no,
            include_all_targets=is_sync or len(target_chapter_nos) > 1,
        )
        messages.append({"role": "system", "content": continuity})
    for h in merged_history[-MAX_HISTORY:]:
        role = h.get("role")
        content = str(h.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message.strip()})

    user_msg = WriteAgentMessage(
        book_id=book.id,
        session_id=session_id,
        role="user",
        content=message.strip(),
        cards_json=[],
        actions_json=[],
        meta_json={
            **(user_meta or {}),
            "chapter_no": chapter_no,
            "understanding": {
                k: understanding.get(k)
                for k in (
                    "intent",
                    "topic",
                    "summary",
                    "is_follow_up",
                    "edit_scope",
                    "target_chapter_nos",
                    "affected_resources",
                )
            },
            "task_plan": {
                "execution_mode": task_plan.get("execution_mode"),
                "resources": task_plan.get("resources"),
                "steps": [
                    {"id": s.get("id"), "description": s.get("description"), "action": s.get("action")}
                    for s in (task_plan.get("steps") or [])
                ],
            },
        },
    )
    db.add(user_msg)
    db.flush()

    history_meta = [
        (m.meta_json or {}) for m in list_write_agent_messages(db, book)
        if m.role == "assistant"
    ]
    img_result = await maybe_handle_chat_image(
        db,
        user,
        book,
        message.strip(),
        chapter_no=chapter_no,
        history=merged_history,
        history_meta=history_meta,
    )
    if img_result and img_result.get("handled"):
        reply_text = str(img_result.get("reply") or "")
        images = img_result.get("images") or []
        assistant_msg = WriteAgentMessage(
            book_id=book.id,
            session_id=session_id,
            role="assistant",
            content=reply_text,
            cards_json=[],
            actions_json=[],
            meta_json={"images": images, "chapter_no": chapter_no},
        )
        db.add(assistant_msg)
        db.commit()
        db.refresh(user_msg)
        db.refresh(assistant_msg)
        context_status = get_context_status(db, book, chapter_no=chapter_no, draft_content=draft_content)
        return {
            "reply": reply_text,
            "edits": [],
            "applied": [],
            "revert_snapshots": [],
            "cards": [],
            "card_applied": [],
            "actions": [],
            "images": images,
            "user_message_id": user_msg.id,
            "assistant_message_id": assistant_msg.id,
            "session_id": session_id,
            "context_status": context_status,
        }

    intent = understanding.get("intent", "general")
    understanding = {**understanding, "session_id": session_id}

    def _apply_constraints(parsed: dict[str, Any]) -> dict[str, Any]:
        return _apply_understanding_constraints(parsed, understanding, db=db, book=book, msg=message.strip())

    route_ctx = WriteRouteContext(
        db=db,
        user=user,
        book=book,
        message=message.strip(),
        chapter_no=chapter_no,
        draft_content=draft_content,
        understanding=understanding,
        task_plan=task_plan,
        book_index=book_index,
        messages=messages,
        target_chapter_nos=target_chapter_nos,
        chapter_contents=chapter_contents,
        edit_context=edit_context,
        merged_history=merged_history,
        last_preview=last_preview,
        llm_tracker=llm_tracker,
        stream_emit=stream_emit,
        session_id=session_id,
        parse_agent_json=_parse_agent_json,
        apply_understanding_constraints=_apply_constraints,
        execute_sequential_chapter_edits=execute_sequential_chapter_edits,
        chapter_contents_map=_chapter_contents_map,
        edit_context_from_understanding=_edit_context_from_understanding,
    )
    with timed_operation("chat_turn_execute", book_id=book.id, execution_mode=execution_mode):
        route_name, parsed = await execute_route(route_ctx)
    sequential_result = route_ctx.sequential_result
    cross_sync_applied = list(route_ctx.cross_sync_applied)
    log_structured(
        "chat_turn_complete",
        book_id=book.id,
        route=route_name,
        execution_mode=execution_mode,
        call_count=llm_tracker.call_count,
        estimated_tokens=llm_tracker.estimated_tokens,
    )

    cards = list(parsed.get("cards") or [])
    actions: list[dict] = list(parsed.get("actions") or [])
    progress = _build_progress(db, book)
    msg = message.strip()

    if _should_include_cards(msg, parsed, understanding):
        ai_cards = _cap_outline_chapters(_normalize_cards_list([c for c in cards if isinstance(c, dict,)]))
        lookup = _lookup_db_cards(db, book, msg) if understanding.get("intent") == "show_card" else []
        char_sources = merge_character_cards_by_name(
            [c for c in ai_cards if c.get("type") == "character"]
            + [c for c in lookup if c.get("type") == "character"]
        )
        other_cards = _dedupe_cards(
            reconcile_cards_with_book(
                db,
                book,
                _cap_outline_chapters(
                    _normalize_cards_list([c for c in ai_cards if c.get("type") != "character"])[:3]
                ),
            )
        )
        result_cards: list[dict] = []
        if char_sources:
            ingest_character_cards(db, book, char_sources, overwrite=True)
            shown_names = [character_name(c) for c in char_sources]
            result_cards = cards_from_db_names(db, book, shown_names)
        else:
            result_cards = [c for c in lookup if c.get("type") != "character"]
        cards = _dedupe_cards(_cap_outline_chapters(result_cards + other_cards))[:3]
    else:
        cards = []

    if understanding.get("intent") == "view_outline" or _is_outline_view_request(msg):
        cards = [c for c in cards if c.get("type") != "outline"]
        if not any(a.get("type") == "open_outline" for a in actions):
            actions.append(_outline_view_action(book.id, int(progress.get("outline_written") or 0)))

    card_applied: list[dict] = list(cross_sync_applied)
    apply_ids = set(parsed.get("apply_card_ids") or [])
    apply_ids.discard("")
    if _is_show_request(msg) and not any(k in msg for k in ADOPT_KEYWORDS) and not is_apply_book_meta_message(msg):
        apply_ids = set()
    card_applied.extend(adopt_cards_from_parsed(db, book, cards, apply_ids))

    cards, card_applied, parsed = _finalize_book_meta_apply(
        db, book, msg, understanding, parsed, cards, card_applied
    )

    applied: list[dict] = []
    revert_snaps: list[dict] = []
    edits = parsed.get("edits") or []

    if sequential_result is not None:
        applied = list(sequential_result["applied"])
        revert_snaps = list(sequential_result["revert_snapshots"])
        reply_text = str(sequential_result["reply"] or "").strip()
    else:
        edits = _expand_edits_from_dirty_payloads(edits)
        edits = _normalize_edits_for_chapter(
            edits, target_chapter_nos, chapter_no, chapter_contents, edit_context
        )
        if edits and _is_show_request(msg) and not any(k in msg for k in EDIT_KEYWORDS) and not is_edit_text_message(msg):
            edits = []
        reply_text = str(parsed.get("reply") or "").strip()
        wants_edit = understanding.get("intent") == "edit_text" or is_edit_text_message(msg)
        claimed_success_without_writes = (
            reply_implies_edit_success(reply_text)
            and not applied
            and not card_applied
            and not edits
            and sequential_result is None
            and intent not in ("consistency_check", "analyze_only")
            and not understanding.get("execute_prior_plan")
            and not (
                was_consistency_analysis_context(merged_history, last_assistant_preview=last_preview)
                and any(k in msg for k in ADOPT_KEYWORDS)
            )
        )
        if wants_edit:
            if edits and not any(k in reply_text for k in ("未能", "未被修改", "请重试", "失败")):
                pass
            elif not edits and reply_implies_edit_success(reply_text):
                reply_text = edit_failure_reply(
                    edit_scope=str(edit_context.get("edit_scope") or "chapter"),
                    target_chapter_nos=target_chapter_nos,
                )
        elif claimed_success_without_writes:
            reply_text = (
                "未能实际写入修改（数据库无变更）。"
                "若上一轮是设定一致性分析，请发送「开始执行」或点击卡片「采纳」来应用方案。"
            )
        if edits:
            applied, revert_snaps = apply_edits(
                db, book, edits, chapter_contents=chapter_contents, edit_context=edit_context
            )
            if wants_edit and not applied:
                reply_text = edit_failure_reply(
                    edit_scope=str(edit_context.get("edit_scope") or "chapter"),
                    target_chapter_nos=target_chapter_nos,
                )
                edits = []
            elif applied:
                nos = "、".join(f"第{a['chapter_no']}章" for a in applied)
                if reply_implies_edit_success(reply_text) or len(reply_text) > 600:
                    reply_text = f"已修改 {nos} 并写入编辑器。请在左侧查看变更高亮，确认后可继续编辑。"
        else:
            applied, revert_snaps = [], []

    assistant_msg = WriteAgentMessage(
        book_id=book.id,
        session_id=session_id,
        role="assistant",
        content=reply_text,
        cards_json=cards,
        actions_json=actions,
        meta_json={
            "applied": applied,
            "revert_snapshots": revert_snaps,
            "card_applied": card_applied,
            "chapter_no": chapter_no,
            "images": parsed.get("images") or [],
            "task_plan": {
                "execution_mode": task_plan.get("execution_mode"),
                "resources": task_plan.get("resources"),
                "steps": [
                    {"id": s.get("id"), "description": s.get("description"), "action": s.get("action")}
                    for s in (task_plan.get("steps") or [])
                ],
            },
            "analysis": parsed.get("analysis") if isinstance(parsed.get("analysis"), dict) else None,
            **llm_tracker.to_meta(execution_mode),
        },
    )
    db.add(assistant_msg)
    db.commit()
    db.refresh(user_msg)
    db.refresh(assistant_msg)

    context_status = get_context_status(
        db, book, chapter_no=chapter_no, draft_content=draft_content
    )

    return {
        "reply": reply_text,
        "edits": edits,
        "applied": applied,
        "revert_snapshots": revert_snaps,
        "cards": cards,
        "card_applied": card_applied,
        "actions": actions,
        "user_message_id": user_msg.id,
        "assistant_message_id": assistant_msg.id,
        "session_id": session_id,
        "context_status": context_status,
        "images": parsed.get("images") or [],
    }
