"""写作智能体多资源任务执行：一致性分析、跨资源同步。"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.models import Book, User
from app.services.agent_constants import (
    ADOPT_PLAN_KEYWORDS,
    APPLY_SETTING_KEYWORDS,
    EXECUTE_PLAN_KEYWORDS,
)
from app.services.ai_assist import _chat
from app.services.book_index import build_prefetch_context_blocks, format_book_index_block
from app.services.setup_agent import _normalize_cards_list, apply_card, reconcile_cards_with_book
from app.services.character_cards import sync_character_card
from app.services.task_planner import format_task_plan_for_user, CHAPTER_NO_RE
from app.services.agent_intent import _extract_json_object, salvage_reply_from_raw
from app.services.write_agent_context import list_visible_session_messages

PRIOR_PLAN_MARKERS = (
    "冲突", "不一致", "任务计划", "一致性", "对照", "统一方案", "建议修正", "冲突清单",
    "设定冲突", "矛盾点",
)
DRAFT_CARD_HISTORY_MARKERS = ("状态=draft", "outline卡片", "character卡片", "修正版")

CONSISTENCY_SYSTEM = """你是 NovFlow 写作智能体的「设定一致性分析模块」。
用户要求对照大纲、角色卡、世界观等设定，找出冲突并 propose 统一方案。

## 输出格式（合法 JSON）
{
  "reply": "给用户看的 Markdown 分析报告：先列冲突清单，再列建议修正（编号列表）",
  "analysis": {
    "conflicts": [
      {
        "id": "c1",
        "severity": "high|medium|low",
        "resources": ["outline", "characters"],
        "summary": "一句话描述冲突",
        "outline_ref": "大纲侧依据",
        "character_ref": "角色卡侧依据",
        "suggestion": "建议如何统一"
      }
    ],
    "aligned": ["已一致的项目简述"],
    "open_questions": ["需用户确认的点"]
  },
  "cards": [
    {
      "id": "唯一字符串",
      "type": "character|outline",
      "title": "卡片标题",
      "status": "draft",
      "data": { }
    }
  ],
  "apply_card_ids": [],
  "actions": [],
  "edits": []
}

## 规则
1. **禁止**输出 edits 或非空的 apply_card_ids（除非用户明确说「采纳/应用/写入」且方案无歧义）。
2. 必须先完成 analysis.conflicts 再写 reply；reply 与 analysis 内容一致。
3. 冲突项要具体：引用大纲章号/情节点与角色卡字段（role/summary/content）。
4. 修正方案用 cards 草案（status=draft）；character 含 character_id；outline 含 chapters 数组。
5. 若未发现冲突，conflicts=[]，reply 说明已对齐之处。
6. 不要改写章节正文；不要输出 open_outline 除非用户要跳转查看。"""


def _parse_consistency_response(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    data: dict[str, Any] | None = None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    data = _extract_json_object(text)
    if not data:
        reply = salvage_reply_from_raw(text) or text[:8000]
        return {
            "reply": reply,
            "analysis": {"conflicts": [], "aligned": [], "open_questions": []},
            "cards": [],
            "apply_card_ids": [],
            "actions": [],
            "edits": [],
        }

    reply = str(data.get("reply") or "").strip()
    analysis = data.get("analysis") if isinstance(data.get("analysis"), dict) else {}
    cards_raw = data.get("cards") or []
    cards = _normalize_cards_list(cards_raw)[:3] if isinstance(cards_raw, list) else []
    apply_ids = [str(x) for x in (data.get("apply_card_ids") or []) if x]
    return {
        "reply": reply or "已完成一致性分析。",
        "analysis": {
            "conflicts": analysis.get("conflicts") or [],
            "aligned": analysis.get("aligned") or [],
            "open_questions": analysis.get("open_questions") or [],
        },
        "cards": cards,
        "apply_card_ids": apply_ids,
        "actions": [],
        "edits": [],
    }


def _format_analysis_appendix(analysis: dict[str, Any]) -> str:
    conflicts = analysis.get("conflicts") or []
    if not conflicts:
        return ""
    lines = ["", "---", "**冲突清单（结构化）**"]
    for i, c in enumerate(conflicts[:8], 1):
        if not isinstance(c, dict):
            continue
        sev = c.get("severity") or "medium"
        summary = c.get("summary") or ""
        suggestion = c.get("suggestion") or ""
        lines.append(f"{i}. [{sev}] {summary}")
        if suggestion:
            lines.append(f"   → 建议：{suggestion}")
    return "\n".join(lines)


async def execute_consistency_analysis(
    user: User,
    messages: list[dict],
    *,
    understanding: dict[str, Any],
    task_plan: dict[str, Any],
    user_message: str,
    book_index: dict[str, Any],
    auto_apply: bool = False,
) -> dict[str, Any]:
    """分析大纲/角色卡等一致性，返回结构化报告 + 可选设定草案（不改正文）。"""
    resources = task_plan.get("resources") or ["outline", "characters"]
    prefetch = build_prefetch_context_blocks(book_index, resources)
    index_block = format_book_index_block(book_index, compact=False)

    exec_msgs: list[dict] = [{"role": "system", "content": CONSISTENCY_SYSTEM}]
    exec_msgs.append({"role": "system", "content": index_block})
    for block in prefetch:
        exec_msgs.append({"role": "system", "content": block})
    exec_msgs.append(
        {
            "role": "system",
            "content": f"## 用户需求\n{understanding.get('summary') or user_message}\n\n"
            f"涉及资源：{', '.join(resources)}\n"
            "请完成对照分析；若无用户明确「采纳/应用」，apply_card_ids 必须为空，edits 必须为空。",
        }
    )
    for h in messages:
        if h.get("role") in ("user", "assistant"):
            content = str(h.get("content") or "").strip()
            if content and not content.startswith("## 【"):
                exec_msgs.append({"role": h["role"], "content": content[-4000:]})

    raw = await _chat(user, exec_msgs, temperature=0.35, max_tokens=16384, json_object=True)
    parsed = _parse_consistency_response(raw)

    plan_prefix = format_task_plan_for_user(task_plan)
    reply = parsed["reply"]
    if plan_prefix:
        reply = f"{plan_prefix}\n\n{reply}"
    appendix = _format_analysis_appendix(parsed.get("analysis") or {})
    if appendix and appendix not in reply:
        reply += appendix

    open_q = (parsed.get("analysis") or {}).get("open_questions") or []
    if open_q and not auto_apply:
        reply += "\n\n**待确认**：" + "；".join(str(q) for q in open_q[:3])

    cards = parsed.get("cards") or []
    apply_ids = list(parsed.get("apply_card_ids") or [])
    if auto_apply and cards and not apply_ids:
        apply_ids = [str(c.get("id")) for c in cards if c.get("id")]

    return {
        "reply": reply,
        "edits": [],
        "cards": cards,
        "apply_card_ids": apply_ids if auto_apply else [],
        "actions": [],
        "analysis": parsed.get("analysis"),
        "task_plan": task_plan,
    }


async def execute_cross_sync(
    db: Session,
    book: Book,
    user: User,
    messages: list[dict],
    *,
    understanding: dict[str, Any],
    task_plan: dict[str, Any],
    user_message: str,
    book_index: dict[str, Any],
) -> dict[str, Any]:
    """多资源同步：先分析，再可选自动应用设定卡片。"""
    auto_apply = bool(
        understanding.get("auto_apply")
        or any(k in user_message for k in APPLY_SETTING_KEYWORDS)
    )
    result = await execute_consistency_analysis(
        user,
        messages,
        understanding=understanding,
        task_plan=task_plan,
        user_message=user_message,
        book_index=book_index,
        auto_apply=auto_apply,
    )

    cards = reconcile_cards_with_book(db, book, result.get("cards") or [])
    result["cards"] = cards
    apply_ids = set(result.get("apply_card_ids") or [])
    card_applied: list[dict] = []

    if auto_apply and apply_ids:
        for card in cards:
            if card.get("id") not in apply_ids or card.get("status") == "applied":
                continue
            if card.get("type") == "character":
                res = sync_character_card(db, book, {**card, "status": "applied"}, overwrite=True)
                card_applied.append({"type": "character", "ok": True, "character_id": res.id, "card_id": card["id"]})
            else:
                res = apply_card(db, book, {**card, "status": "applied"})
                card_applied.append({**res, "card_id": card["id"]})
            card["status"] = "applied"
        if card_applied:
            db.commit()
            names = "、".join(str(x.get("card_id", "")) for x in card_applied)
            result["reply"] += f"\n\n✅ 已写入设定：{names}"

    result["card_applied"] = card_applied
    return result


def was_consistency_analysis_context(
    history: list[dict] | None,
    *,
    last_assistant_preview: str = "",
) -> bool:
    """最近对话是否处于「一致性分析 / 统一方案」上下文。"""
    preview = (last_assistant_preview or "").strip()
    if preview and any(k in preview for k in PRIOR_PLAN_MARKERS):
        return True
    if preview and any(k in preview for k in DRAFT_CARD_HISTORY_MARKERS):
        return True
    for h in reversed((history or [])[-8:]):
        if h.get("role") != "assistant":
            continue
        content = str(h.get("content") or "").strip()
        if not content:
            continue
        if any(k in content for k in PRIOR_PLAN_MARKERS):
            return True
        if any(k in content for k in DRAFT_CARD_HISTORY_MARKERS):
            return True
    return False


def is_execute_plan_message(message: str) -> bool:
    """用户是否要求执行上一轮分析方案（非重新分析）。"""
    msg = (message or "").strip()
    if not msg:
        return False
    if any(k in msg for k in EXECUTE_PLAN_KEYWORDS):
        return True
    if any(k in msg for k in ADOPT_PLAN_KEYWORDS):
        return True
    short_confirm = len(msg) <= 40
    if short_confirm and any(k in msg for k in ("可以", "好的", "行", "没问题", "嗯", "妥", "OK", "ok")):
        return any(k in msg for k in ("执行", "开始", "修改", "统一", "采纳", "应用"))
    if short_confirm and any(k in msg for k in ("采纳", "确认", "应用")):
        return True
    return False


def coerce_consistency_apply_understanding(
    message: str,
    history: list[dict] | None,
    understanding: dict[str, Any],
    *,
    last_assistant_preview: str = "",
) -> dict[str, Any]:
    """一致性分析后用户确认采纳/开始执行 → 强制走 execute_prior_plan 路径。"""
    if understanding.get("execute_prior_plan"):
        return {
            **understanding,
            "intent": "cross_sync",
            "auto_apply": True,
            "allow_edits": True,
            "allow_cards": True,
        }
    if not was_consistency_analysis_context(history, last_assistant_preview=last_assistant_preview):
        return understanding
    if not is_execute_plan_message(message):
        return understanding
    return {
        **understanding,
        "intent": "cross_sync",
        "topic": "outline",
        "execute_prior_plan": True,
        "auto_apply": True,
        "allow_edits": True,
        "allow_cards": True,
        "is_follow_up": True,
        "summary": understanding.get("summary") or "执行上一轮一致性分析方案（写入设定并修正正文）",
        "must_do": list(dict.fromkeys(
            (understanding.get("must_do") or [])
            + [
                "必须应用上一轮草案 character/outline 卡片到数据库",
                "必须对分析中涉及的章节正文执行实际修改并写入",
            ]
        ))[:8],
        "must_not_do": list(dict.fromkeys(
            (understanding.get("must_not_do") or []) + ["禁止只口头描述已完成而未写入数据库"]
        ))[:8],
    }


def collect_prior_plan_from_session(
    db: Session,
    book: Book,
    session_id: str,
) -> dict[str, Any]:
    """从会话消息中回收上一轮分析的报告、草案卡片与结构化 analysis。"""
    rows = list_visible_session_messages(db, book, session_id)
    prior_cards: list[dict] = []
    seen_card_ids: set[str] = set()
    prior_analysis: dict[str, Any] | None = None
    prior_reply = ""
    prior_task_plan: dict[str, Any] | None = None

    for m in reversed(rows):
        if m.role != "assistant":
            continue
        meta = m.meta_json or {}
        if meta.get("welcome"):
            continue
        for c in m.cards_json or []:
            if not isinstance(c, dict):
                continue
            cid = str(c.get("id") or "")
            if not cid or cid in seen_card_ids:
                continue
            if c.get("status") == "applied":
                continue
            seen_card_ids.add(cid)
            prior_cards.append(dict(c))
        if meta.get("analysis") and isinstance(meta.get("analysis"), dict) and not prior_analysis:
            prior_analysis = meta["analysis"]
        if meta.get("task_plan") and isinstance(meta.get("task_plan"), dict) and not prior_task_plan:
            prior_task_plan = meta["task_plan"]
        content = (m.content or "").strip()
        draft_cards_in_msg = [
            c for c in (m.cards_json or [])
            if isinstance(c, dict) and c.get("status") != "applied"
        ]
        if content and not prior_reply:
            if any(k in content for k in PRIOR_PLAN_MARKERS) or (meta.get("task_plan") or meta.get("analysis")):
                prior_reply = content
            elif draft_cards_in_msg:
                prior_reply = content
        if prior_cards and prior_reply:
            break

    return {
        "cards": prior_cards,
        "analysis": prior_analysis,
        "reply": prior_reply,
        "task_plan": prior_task_plan,
    }


def extract_chapter_nos_from_plan(
    text: str,
    analysis: dict[str, Any] | None = None,
) -> list[int]:
    """从分析报告或结构化 conflicts 中提取需改正文的章号。"""
    nos: set[int] = set()
    blob = (text or "")
    for m in CHAPTER_NO_RE.finditer(blob):
        nos.add(int(m.group(1)))
    conflicts = (analysis or {}).get("conflicts") or []
    for c in conflicts:
        if not isinstance(c, dict):
            continue
        for field in ("summary", "outline_ref", "character_ref", "suggestion", "resources"):
            val = c.get(field)
            if isinstance(val, list):
                blob = " ".join(str(x) for x in val)
            else:
                blob = str(val or "")
            for m in CHAPTER_NO_RE.finditer(blob):
                nos.add(int(m.group(1)))
    return sorted(n for n in nos if n > 0)


def apply_prior_plan_cards(
    db: Session,
    book: Book,
    prior_cards: list[dict],
) -> tuple[list[dict], list[dict]]:
    """将上一轮草案卡片写入数据库（角色卡 PATCH / 大纲采纳）。"""
    cards = reconcile_cards_with_book(db, book, _normalize_cards_list(prior_cards))
    card_applied: list[dict] = []
    for card in cards:
        if card.get("status") == "applied":
            continue
        if card.get("type") == "character":
            res = sync_character_card(db, book, {**card, "status": "applied"}, overwrite=True)
            card_applied.append(
                {"type": "character", "ok": True, "character_id": res.id, "card_id": card.get("id")}
            )
        else:
            res = apply_card(db, book, {**card, "status": "applied"})
            card_applied.append({**res, "card_id": card.get("id")})
        card["status"] = "applied"
    if card_applied:
        db.commit()
    return cards, card_applied


async def execute_consistency_apply(
    db: Session,
    book: Book,
    user: User,
    session_id: str,
    messages: list[dict],
    *,
    understanding: dict[str, Any],
    task_plan: dict[str, Any],
    user_message: str,
    book_index: dict[str, Any],
) -> dict[str, Any]:
    """
    执行上一轮一致性分析方案：写入设定卡片，并返回待改正文的章号与方案摘要。
    若无 prior 草案则回退到带 auto_apply 的再分析。
    """
    prior = collect_prior_plan_from_session(db, book, session_id)
    prior_cards = list(prior.get("cards") or [])
    prior_reply = str(prior.get("reply") or "").strip()
    prior_analysis = prior.get("analysis") if isinstance(prior.get("analysis"), dict) else None

    cards: list[dict] = []
    card_applied: list[dict] = []
    reply_parts: list[str] = ["**执行统一方案**"]

    if prior_cards:
        cards, card_applied = apply_prior_plan_cards(db, book, prior_cards)
        if card_applied:
            names = "、".join(
                str(x.get("card_id") or x.get("character_id") or "") for x in card_applied
            )
            reply_parts.append(f"✅ 已写入设定卡片：{names}")
        else:
            reply_parts.append("⚠️ 设定卡片未能写入（可能已全部采纳或无有效草案）")
    else:
        analysis_result = await execute_consistency_analysis(
            user,
            messages,
            understanding=understanding,
            task_plan=task_plan,
            user_message=user_message,
            book_index=book_index,
            auto_apply=True,
        )
        cards = reconcile_cards_with_book(db, book, analysis_result.get("cards") or [])
        apply_ids = set(analysis_result.get("apply_card_ids") or [])
        if not apply_ids and cards:
            apply_ids = {str(c.get("id")) for c in cards if c.get("id")}
        for card in cards:
            if card.get("id") not in apply_ids or card.get("status") == "applied":
                continue
            if card.get("type") == "character":
                res = sync_character_card(db, book, {**card, "status": "applied"}, overwrite=True)
                card_applied.append(
                    {"type": "character", "ok": True, "character_id": res.id, "card_id": card["id"]}
                )
            else:
                res = apply_card(db, book, {**card, "status": "applied"})
                card_applied.append({**res, "card_id": card["id"]})
            card["status"] = "applied"
        if card_applied:
            db.commit()
            reply_parts.append("✅ 已根据本轮分析写入设定卡片")
        else:
            reply_parts.append("⚠️ 未找到可采纳的设定草案，设定未变更")
        prior_reply = str(analysis_result.get("reply") or "").strip() or prior_reply
        if not prior_analysis and isinstance(analysis_result.get("analysis"), dict):
            prior_analysis = analysis_result["analysis"]

    chapter_nos = extract_chapter_nos_from_plan(prior_reply, prior_analysis)
    plan_summary = prior_reply[:4000] if prior_reply else str(understanding.get("summary") or "")

    return {
        "reply_parts": reply_parts,
        "cards": cards,
        "card_applied": card_applied,
        "chapter_target_nos": chapter_nos,
        "plan_summary": plan_summary,
        "analysis": prior_analysis,
        "task_plan": task_plan,
    }
