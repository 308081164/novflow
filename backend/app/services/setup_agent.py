"""创书向导：多轮对话 + 结构化卡片 + 无感写入设定。"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models import Book, Character, Chapter, ChapterPlan, SetupMessage, User, Worldview
from app.services.ai_assist import _chat
from app.services.ai_assist import generate_writing_rules
from app.services.agent_intent import (
    execute_brainstorm_plain,
    extract_title_from_message,
    is_apply_book_meta_message,
    setup_execution_hint,
    understand_setup_message,
)
from app.services.character_cards import dedupe_characters_by_name, ingest_character_cards, sync_character_card
from app.services.card_handlers import OUTLINE_MAX_BATCH, apply_card_by_type
from app.services.observability import StreamEmit

PHASES = {
    1: "作品定位（类型、梗概、卖点）",
    2: "世界观（时代、舞台、基调、禁忌）",
    3: "角色卡（主角与关键配角）",
    4: "剧情走向与章节大纲",
    5: "收尾确认，准备写作",
}

GUIDANCE_KEYWORDS = ("下一步", "接下来", "然后", "做什么", "怎么办", "建议", "引导", "然后呢", "干什么", "去哪")
WRITING_KEYWORDS = ("写作", "试笔", "写第", "开始写", "动笔", "正文", "进入写作", "试一试笔")
OUTLINE_KEYWORDS = ("大纲", "章节规划", "规划章", "章节目录", "分章", "开始规划")
OUTLINE_REFINE_KEYWORDS = ("按检查结果修订", "修订大纲", "修正大纲", "根据检查", "重新规划大纲")
CHARACTER_KEYWORDS = ("角色", "人物", "配角", "反派", "女主", "男主")

WELCOME = (
    "你好！我是你的创作搭档。我们可以一起头脑风暴：从一句话灵感出发，逐步完善世界观、角色和剧情走向。"
    "你可以随意聊想法，我会把讨论成果整理成卡片；觉得合适就点「采纳」，设定会自动写入作品。"
)


def _card_id() -> str:
    return uuid.uuid4().hex[:12]


def _worldview_complete(wv: Worldview | None) -> bool:
    if not wv:
        return False
    return bool(wv.content.strip() or (wv.era.strip() and wv.setting.strip()))


def _max_chapter_in_text(text: str | None) -> int | None:
    """从「551-750」「第751～900章」等文本提取最大章号。"""
    if not text:
        return None
    nums = [int(x) for x in re.findall(r"\d+", str(text))]
    return max(nums) if nums else None


def _infer_total_chapters_from_plot_data(data: dict[str, Any]) -> int | None:
    """从 plot 卡片 data 推断全书目标章数。"""
    if not isinstance(data, dict):
        return None
    if data.get("total_chapters"):
        try:
            return int(data["total_chapters"])
        except (TypeError, ValueError):
            pass
    candidates: list[int] = []
    for key in ("phases", "units"):
        for item in data.get(key) or []:
            if not isinstance(item, dict):
                continue
            for field in ("chapter_range", "name", "description", "title"):
                end = _max_chapter_in_text(item.get(field))
                if end:
                    candidates.append(end)
    for field in ("summary", "title"):
        end = _max_chapter_in_text(data.get(field))
        if end:
            candidates.append(end)
    return max(candidates) if candidates else None


def resolve_effective_target_chapters(book: Book) -> int:
    """权威目标章数：book.target_chapters 与 plot_framework 取较大值。"""
    candidates = [int(book.target_chapters or 0)]
    pf = book.plot_framework
    if isinstance(pf, dict) and pf:
        inferred = _infer_total_chapters_from_plot_data(pf)
        if inferred:
            candidates.append(inferred)
        if pf.get("total_chapters"):
            try:
                candidates.append(int(pf["total_chapters"]))
            except (TypeError, ValueError):
                pass
    positive = [c for c in candidates if c > 0]
    return max(positive) if positive else 100


def sync_target_chapters_from_plot_framework(book: Book) -> bool:
    """若 plot_framework 含更高章数目标，回写 book.target_chapters。"""
    resolved = resolve_effective_target_chapters(book)
    if resolved > int(book.target_chapters or 0):
        book.target_chapters = resolved
        return True
    return False


def _parse_requested_outline_range(user_message: str) -> tuple[int, int] | None:
    """解析用户指定的章号范围，如「第21-25章」「21～25章」。"""
    patterns = (
        r"第\s*(\d+)\s*[~～\-—到至]\s*(\d+)\s*章",
        r"(\d+)\s*[~～\-—到至]\s*(\d+)\s*章",
        r"第\s*(\d+)\s*章\s*[到至\-—]\s*第?\s*(\d+)\s*章",
    )
    for pat in patterns:
        m = re.search(pat, user_message)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            return min(a, b), max(a, b)
    return None


def _plot_framework_block(book: Book) -> str:
    pf = book.plot_framework
    if not isinstance(pf, dict) or not pf:
        return "（尚未采纳长线剧情框架）"
    lines = []
    if pf.get("summary"):
        lines.append(f"- 框架摘要：{str(pf['summary'])[:400]}")
    total = resolve_effective_target_chapters(book)
    lines.append(f"- 目标章数（权威）：{total} 章")
    for phase in pf.get("phases") or []:
        if not isinstance(phase, dict):
            continue
        name = phase.get("name") or "阶段"
        cr = phase.get("chapter_range") or ""
        desc = (phase.get("description") or "")[:200]
        lines.append(f"  · {name} {cr}：{desc}")
    return "\n".join(lines) if lines else "（plot_framework 已存档但内容为空）"


def _build_progress(db: Session, book: Book) -> dict[str, Any]:
    wv = db.query(Worldview).filter(Worldview.book_id == book.id).first()
    chars = db.query(Character).filter(Character.book_id == book.id).all()
    outline_written = (
        db.query(ChapterPlan)
        .filter(ChapterPlan.book_id == book.id, ChapterPlan.plot_points != "")
        .count()
    )
    premise_text = (book.premise or book.blurb or "").strip()
    premise_ok = bool(book.genre.strip() and premise_text)
    wv_ok = _worldview_complete(wv)
    char_ok = len(chars) >= 2
    target_chapters = resolve_effective_target_chapters(book)
    outline_min = min(5, max(1, target_chapters // 20))
    outline_ok = outline_written >= outline_min

    checklist = [
        {"id": "premise", "label": "作品定位", "done": premise_ok},
        {"id": "worldview", "label": "世界观", "done": wv_ok},
        {"id": "characters", "label": f"角色卡（{len(chars)} 人）", "done": char_ok},
        {
            "id": "outline",
            "label": f"章节大纲（{outline_written}/{target_chapters} 章）",
            "done": outline_ok,
        },
    ]
    completed = [c["label"] for c in checklist if c["done"]]
    pending = [c["label"] for c in checklist if not c["done"]]

    if not premise_ok:
        next_step, next_action = 1, "完善作品定位：类型、梗概与目标章数"
    elif not wv_ok:
        next_step, next_action = 2, "建立世界观：时代背景、主舞台、基调与禁忌"
    elif not char_ok:
        next_step, next_action = 3, f"补充核心角色（已存档 {len(chars)} 人，建议至少 2～3 人）"
    elif not outline_ok:
        next_step, next_action = (
            4,
            f"规划章节大纲（已规划 {outline_written} 章，可先出第 1～10 章）",
        )
    else:
        next_step, next_action = 5, "设定已基本齐全，可确认本书写作偏好并开始写第 1 章"

    return {
        "checklist": checklist,
        "completed": completed,
        "pending": pending,
        "next_step": next_step,
        "next_action": next_action,
        "character_names": [c.name for c in chars],
        "outline_written": outline_written,
        "outline_target": target_chapters,
        "has_author_preferences": bool(book.writing_rules.strip()),
        "has_writing_rules": bool(book.writing_rules.strip()),
    }


def _detect_intent(user_message: str) -> str:
    msg = user_message.strip()
    if any(k in msg for k in GUIDANCE_KEYWORDS):
        return "guidance"
    if any(k in msg for k in WRITING_KEYWORDS):
        return "writing"
    if any(k in msg for k in OUTLINE_REFINE_KEYWORDS):
        return "outline"
    if any(k in msg for k in OUTLINE_KEYWORDS):
        return "outline"
    if any(k in msg for k in CHARACTER_KEYWORDS):
        return "character"
    return "general"


def _suggest_writing_actions(db: Session, book: Book) -> list[dict]:
    plan = (
        db.query(ChapterPlan)
        .filter(ChapterPlan.book_id == book.id, ChapterPlan.plot_points != "")
        .order_by(ChapterPlan.chapter_no)
        .first()
    )
    chapter_no = plan.chapter_no if plan else 1
    label = f"写第 {chapter_no} 章"
    if plan and plan.title:
        label = f"写第 {chapter_no} 章：{plan.title}"
    return [
        {"type": "write_chapter", "label": label, "chapter_no": chapter_no},
        {"type": "open_outline", "label": "查看章节大纲"},
        {"type": "open_overview", "label": "返回书籍概览"},
    ]


def _intent_hint(intent: str, progress: dict[str, Any], user_message: str) -> str:
    if intent == "guidance":
        return f"""【本轮用户意图：询问进度 / 下一步怎么做】
用户原话：{user_message}
请基于下方「作品存档」如实回答，不要答非所问，不要说「少要几个角色」除非用户正在批量要角色。
- 已完成：{'、'.join(progress['completed']) or '暂无'}
- 待完成：{'、'.join(progress['pending']) or '无'}
- 系统判断建议下一步：{progress['next_action']}
- 已存档角色：{('、'.join(progress['character_names']) if progress['character_names'] else '无')}
reply 须列出 2～3 条可执行建议；cards 可为空；若应进入大纲阶段可主动提议并输出 outline 卡片。"""

    if intent == "outline":
        range_hint = ""
        req = _parse_requested_outline_range(user_message)
        if req:
            range_hint = f"\n- 用户指定本批章号：**第 {req[0]}～{req[1]} 章**（必须按此范围输出 outline 卡片，禁止改用其他章号）"
        return f"""【本轮用户意图：规划章节大纲】
- 已规划 {progress['outline_written']} / {progress['outline_target']} 章（outline_target 为权威目标，勿用旧默认值 100）
- 已存档角色：{'、'.join(progress['character_names']) or '无'}{range_hint}
下方系统消息已注入**完整角色卡、写作偏好、长线框架、前序大纲**；你必须严格参照。
请输出 type=outline 卡片（每批最多 {OUTLINE_MAX_BATCH} 章），每章 plot_points 须具体可写，cast 须用角色卡姓名。
reply 须说明如何承接前序、如何落在当前 plot 阶段；规划完成后会自动做一致性自检。"""

    if intent == "writing":
        return f"""【本轮用户意图：进入写作阶段】
用户原话：{user_message}
- 已规划 {progress['outline_written']} / {progress['outline_target']} 章
- 已存档角色：{'、'.join(progress['character_names']) or '无'}
规则：
1. **禁止**在 cards 中输出 outline、chapter_draft 或任何正文草稿卡片。
2. reply 简短鼓励用户去专用写作编辑器动笔，可简要回顾本章要点。
3. 在 actions 数组中给出导航按钮（write_chapter / open_outline / open_overview），不要依赖卡片。
4. setup_step 设为 5。"""

    if intent == "character":
        return """【本轮用户意图：设计角色】
每次 cards 最多 3 张 character；content 150 字内。若用户一次要太多，说明下批继续。"""

    return ""


def _guidance_fallback(progress: dict[str, Any]) -> str:
    done = "、".join(progress["completed"]) if progress["completed"] else "暂无"
    todo = "、".join(progress["pending"]) if progress["pending"] else "无"
    lines = [
        "根据当前作品存档，进度如下：",
        f"✓ 已完成：{done}",
        f"○ 待完成：{todo}",
        "",
        f"**建议下一步：{progress['next_action']}**",
    ]
    if progress["next_step"] == 4:
        lines.append("你可以说「规划第 1～10 章大纲」，我会按章节生成大纲卡片供你采纳。")
    elif progress["next_step"] == 5:
        lines.append("点击右上角「完成设定，开始写作」，或让我帮你过一遍整体剧情走向。")
    elif progress["next_step"] == 3:
        names = progress["character_names"]
        if names:
            lines.append(f"已有角色：{'、'.join(names)}。可继续补充反派/配角，或说「开始规划大纲」。")
    return "\n".join(lines)


def _book_snapshot(db: Session, book: Book) -> dict[str, Any]:
    wv = db.query(Worldview).filter(Worldview.book_id == book.id).first()
    chars = db.query(Character).filter(Character.book_id == book.id).all()
    plans = (
        db.query(ChapterPlan)
        .filter(ChapterPlan.book_id == book.id, ChapterPlan.plot_points != "")
        .order_by(ChapterPlan.chapter_no)
        .limit(8)
        .all()
    )
    return {
        "title": book.title,
        "genre": book.genre or "",
        "premise": book.premise or book.blurb or "",
        "target_chapters": resolve_effective_target_chapters(book),
        "plot_framework_summary": _plot_framework_block(book),
        "setup_step": book.setup_step,
        "phase": PHASES.get(min(book.setup_step, 5), PHASES[5]),
        "worldview": {
            "era": wv.era if wv else "",
            "setting": wv.setting if wv else "",
            "tone": wv.tone if wv else "",
            "content": (wv.content[:300] + "…") if wv and len(wv.content) > 300 else (wv.content if wv else ""),
        },
        "characters": [{"id": c.id, "name": c.name, "role": c.role, "summary": c.summary} for c in chars],
        "outline_preview": [
            {"chapter_no": p.chapter_no, "title": p.title, "plot_points": p.plot_points[:120]}
            for p in plans
        ],
        "plot_summary": book.blurb or "",
        "progress": _build_progress(db, book),
    }


def _progress_block(progress: dict[str, Any]) -> str:
    checklist_lines = "\n".join(
        f"  - [{'x' if c['done'] else ' '}] {c['label']}" for c in progress["checklist"]
    )
    return f"""## 作品存档（权威进度，优先于对话猜测）
{checklist_lines}
- 建议下一步（第 {progress['next_step']} 步）：{progress['next_action']}
- 已采纳角色：{('、'.join(progress['character_names']) if progress['character_names'] else '无')}
- 大纲进度：{progress['outline_written']} / {progress['outline_target']} 章

## 对话策略
- 用户问「下一步/做什么/接下来」→ 根据存档给出**具体**引导，cards 可为空。
- 用户说「开始规划大纲」→ 输出 outline 卡片，不要回到角色阶段。
- 用户要改书名、简介、类型 → 输出 premise 卡片（含 title、genre、premise/blurb），采纳后写入书籍。
- 用户确认「可以/好的」→ 结合上一轮讨论产出对应卡片或推进 setup_step。
- 不要忽视已存档内容；不要重复已完成步骤，除非用户要求修改。"""


def _system_prompt(book: Book, snapshot: dict[str, Any]) -> str:
    progress = snapshot.get("progress") or {}
    return f"""你是 NovFlow 网文创作向导，通过对话帮用户头脑风暴并结构化产出设定。

## 当前作品
- 书名：{book.title}
- 系统阶段：第 {book.setup_step} 步 — {snapshot['phase']}
- 类型：{snapshot['genre'] or '未设定'}
- 梗概：{snapshot['premise'] or '未设定'}
- 计划章数：{snapshot['target_chapters']}（含已采纳 plot 框架，以此为准）

## 已采纳长线剧情框架
{snapshot.get('plot_framework_summary') or _plot_framework_block(book)}

{_progress_block(progress)}

## 你的职责
1. 用自然、有启发性的中文与用户对话，主动提问、给选项、帮用户拓展灵感。
2. 当讨论出可落稿的内容时，在 cards 里给出结构化草案（不必等用户明确说「生成」）。
3. 用户说「可以」「采纳」「就这样」等确认时，把对应 card 的 id 放进 apply_card_ids 自动写入。
4. 根据进度建议推进 setup_step（1定位→2世界观→3角色→4大纲→5完成）。
5. 每次回复必须输出**纯 JSON**（不要 markdown 代码块），格式：

{{
  "reply": "给用户看的对话正文，可含追问与建议",
  "cards": [
    {{
      "id": "唯一字符串",
      "type": "premise|worldview|character|outline|plot|writing_prefs",
      "title": "卡片标题",
      "status": "draft",
      "data": {{ ... 见下方类型说明 ... }}
    }}
  ],
  "apply_card_ids": [],
  "setup_step": {book.setup_step},
  "actions": [
    {{
      "type": "write_chapter|open_outline|open_overview",
      "label": "按钮文字",
      "chapter_no": 1,
      "description": "可选说明"
    }}
  ]
}}

## cards.data 类型说明
- premise: {{ "title", "genre", "premise", "blurb", "target_chapters" }}
- worldview: {{ "era", "setting", "tone", "timeline_text", "taboos", "content" }}
- character: {{ "character_id": null或已有id, "name", "role", "summary", "voice_notes", "content" }}
- outline: {{ "chapters": [{{ "chapter_no", "title", "plot_points", "scene", "comedy_core", "cast": ["角色名"], "events": ["大事件"], "entrances": ["新登场"], "exits": ["退场"] }}] }}
- plot: {{ "summary", "total_chapters", "style", "phases": [{{"name", "chapter_range", "description"}}], "units": [{{"name", "episodes_per_arc", "description"}}] }}
- writing_prefs: {{ "content": "Markdown 写作偏好", "mode": "replace|append" }}

## 规则
- **reply 必填**：至少 2 句话，不能为空字符串；即使 cards 很多也要写简短说明。
- 一次最多输出 **3 张卡片**（角色类优先分批，每批 2～3 个）；避免单次 JSON 过长。
- character 的 content 控制在 150 字内；voice_notes 一句话即可。
- cards 可为空数组；有草案时务必给完整 data。
- character 的 role 用 protagonist/antagonist/support 等。
- outline 一次最多 {OUTLINE_MAX_BATCH} 章；chapter_no 从已有最大章号+1 或用户指定处开始。
- 不要编造用户未讨论过的重大设定；不确定时先问。
- 绝对不要在 reply 里写任何 [已输出卡片...] 内部标记。
- 长篇（>30章）必须先 plot 框架再分批评 outline，每批最多 {OUTLINE_MAX_BATCH} 章。
- reply 里不要重复粘贴 cards 全文，卡片会单独展示。
- actions 为可选数组；用户要「开始写/试笔/进入写作」时务必输出 actions，cards 应为空。"""


def _extract_json_array_after_key(text: str, key: str) -> list | None:
    """从可能截断的 JSON 文本中提取数组（如 cards）。"""
    m = re.search(rf'"{key}"\s*:\s*\[', text)
    if not m:
        return None
    start = m.end() - 1
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                chunk = text[start : i + 1]
                try:
                    val = json.loads(chunk)
                    return val if isinstance(val, list) else None
                except json.JSONDecodeError:
                    return _salvage_json_objects(chunk)
    return _salvage_json_objects(text[start:])


def _salvage_json_objects(text: str) -> list:
    """从截断的数组文本中 salvage 完整的 {...} 对象。"""
    items: list = []
    depth = 0
    obj_start: int | None = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and obj_start is not None:
                try:
                    obj = json.loads(text[obj_start : i + 1])
                    if isinstance(obj, dict):
                        items.append(obj)
                except json.JSONDecodeError:
                    pass
                obj_start = None
    return items


def _normalize_cards_list(cards: list) -> list[dict]:
    normalized: list[dict] = []
    for c in cards:
        if not isinstance(c, dict):
            continue
        card = dict(c)
        if not card.get("id"):
            card["id"] = _card_id()
        card.setdefault("status", "draft")
        card.setdefault("title", card.get("type", "设定"))
        card.setdefault("data", {})
        if card.get("type") == "outline":
            from app.services.outline_planner import normalize_outline_data

            card["data"] = normalize_outline_data(card.get("data"))
        normalized.append(card)
    return normalized


def _fallback_reply(cards: list[dict]) -> str:
    if not cards:
        return ""
    labels = {
        "premise": "作品定位",
        "worldview": "世界观",
        "character": "角色",
        "outline": "章节大纲",
        "plot": "剧情走向",
    }
    parts = []
    for c in cards:
        t = c.get("type", "")
        title = c.get("title") or labels.get(t, "设定")
        data = c.get("data") or {}
        if t == "character" and data.get("name"):
            parts.append(f"「{data['name']}」")
        else:
            parts.append(f"「{title}」")
    return f"我为你整理了 {len(cards)} 张设定卡片：{'、'.join(parts)}。请查看下方卡片，满意的话点「采纳」写入作品；如需调整可以告诉我或点编辑。"


# AI 偶发照抄的历史/泄漏格式（含全角/半角间隔符）
LEAKED_CARD_RE = re.compile(
    r"\[已输出卡片[·.．](?P<type>\w+)[-－](?P<status>\w+)\]\s*(?P<title>[^\n\[]+)",
)
INTERNAL_MARK_RE = re.compile(r"\[已输出卡片[·.．]")


def _outline_chapter_nums(card: dict) -> list[int]:
    """从 outline 卡片 data 或标题解析章节号列表。"""
    from app.services.outline_planner import normalize_outline_data

    data = normalize_outline_data(card.get("data"))
    chapters = data.get("chapters") or []
    nums = [int(ch.get("chapter_no", 0)) for ch in chapters if isinstance(ch, dict) and ch.get("chapter_no")]
    if nums:
        return sorted(set(nums))
    title = card.get("title") or ""
    m = re.search(r"第\s*(\d+)\s*[~～\-—]\s*(\d+)\s*章", title)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return list(range(min(a, b), max(a, b) + 1))
    m2 = re.search(r"第\s*(\d+)\s*章", title)
    if m2:
        return [int(m2.group(1))]
    return []


def _card_matches_target(c: dict, card_id: str | None, card_type: str | None, card_title: str) -> bool:
    if not isinstance(c, dict):
        return False
    if card_id and c.get("id") == card_id:
        return True
    if card_type and c.get("type") == card_type and card_title and (c.get("title") or "").strip() == card_title:
        return True
    return False


def _recover_cards_from_leaked_text(text: str, stable_prefix: str = "") -> tuple[str, list[dict]]:
    """从泄漏的正文中回收卡片，并返回清理后的正文。"""
    if not text or not INTERNAL_MARK_RE.search(text):
        return text, []
    cards: list[dict] = []
    idx = 0
    for m in LEAKED_CARD_RE.finditer(text):
        ctype = m.group("type")
        if "draft" in ctype:
            continue
        title = m.group("title").strip()
        status = m.group("status")
        data: dict[str, Any] = {}
        if ctype == "plot":
            data = {"summary": title, "title": title}
        elif ctype == "outline":
            data = {"chapters": [], "note": title}
        cid = f"{stable_prefix}_{idx}" if stable_prefix else _card_id()
        cards.append(
            {
                "id": cid,
                "type": ctype,
                "title": title,
                "status": status,
                "data": data,
            }
        )
        idx += 1
    cleaned = LEAKED_CARD_RE.sub("", text).strip()
    cleaned = INTERNAL_MARK_RE.sub("", cleaned).strip()
    return cleaned, _normalize_cards_list(cards)


def _compute_shard_plan(book: Book, progress: dict[str, Any], user_message: str) -> dict[str, Any] | None:
    """长篇连载：计算下一批应生成的章节范围。"""
    total = int(progress.get("outline_target") or resolve_effective_target_chapters(book))
    written = int(progress.get("outline_written") or 0)

    req_range = _parse_requested_outline_range(user_message)
    if req_range:
        start, end = req_range
        end = min(end, total)
        if start > end:
            start, end = end, start
        return {
            "total_chapters": total,
            "batch_size": min(end - start + 1, OUTLINE_MAX_BATCH),
            "next_start": start,
            "next_end": min(end, start + OUTLINE_MAX_BATCH - 1),
            "outline_written": written,
            "explicit_range": True,
        }

    m_total = re.search(r"(?:共|总计|目标|计划|写|长篇)\s*(\d{2,4})\s*章", user_message)
    if m_total:
        total = max(total, int(m_total.group(1)))

    pf = book.plot_framework
    has_long_plot = isinstance(pf, dict) and bool(pf.get("phases"))
    if total <= 30 and not has_long_plot:
        return None

    batch = OUTLINE_MAX_BATCH
    start = written + 1
    end = min(start + batch - 1, total)
    return {
        "total_chapters": total,
        "batch_size": batch,
        "next_start": start,
        "next_end": end,
        "outline_written": written,
    }


def _long_form_hint(shard: dict[str, Any], user_message: str) -> str:
    return f"""【长篇分片模式 · 目标约 {shard['total_chapters']} 章】
用户原话：{user_message}
规则：
1. 禁止一次输出超过 {shard['batch_size']} 章的 outline。
2. 若用户在谈整体结构/单元剧/长线框架：只输出 1 张 plot 卡片（含 phases、units、summary、total_chapters），cards 中不要塞章节数组。
3. 若用户在规划具体章节：outline 卡片仅含第 {shard['next_start']}～{shard['next_end']} 章。
4. reply 说明本批范围，并提示「采纳本批后可继续生成下一批」。
5. 绝对不要在 reply 里写 [已输出卡片·...] 这种内部标记。"""


def repair_setup_message(m: SetupMessage) -> bool:
    """修复历史消息：泄漏文本 → 卡片 + 清理正文。"""
    if m.role != "assistant":
        return False
    cards = list(m.cards_json or []) if isinstance(m.cards_json, list) else []
    content = (m.content or "").strip()
    changed = False
    if not cards and INTERNAL_MARK_RE.search(content):
        content, recovered = _recover_cards_from_leaked_text(content, stable_prefix=f"m{m.id}")
        if recovered:
            cards = recovered
            changed = True
    if INTERNAL_MARK_RE.search(content):
        content, _ = _recover_cards_from_leaked_text(content, stable_prefix=f"m{m.id}")
        changed = True
    if m.role == "assistant" and cards:
        normalized = _normalize_cards_list(cards)
        if any(not isinstance(c, dict) or not c.get("id") for c in cards):
            cards = normalized
            changed = True
    if changed:
        m.content = content or (_fallback_reply(cards) if cards else content)
        m.cards_json = cards
    return changed


def repair_all_setup_messages(db: Session, book_id: int) -> int:
    """批量修复书籍下所有助手消息的泄漏卡片。"""
    msgs = db.query(SetupMessage).filter(SetupMessage.book_id == book_id).all()
    n = 0
    for m in msgs:
        if repair_setup_message(m):
            n += 1
    if n:
        db.commit()
    return n


def _sanitize_reply(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    if INTERNAL_MARK_RE.search(t) or t.startswith("（助手曾输出"):
        return ""
    return t


def mark_card_applied_in_messages(db: Session, book_id: int, card: dict) -> None:
    """采纳卡片后，将对应消息里的卡片状态持久化为 applied。"""
    card_id = card.get("id")
    card_type = card.get("type")
    card_title = (card.get("title") or "").strip()
    if not card_id and not (card_type and card_title):
        return
    msgs = (
        db.query(SetupMessage)
        .filter(SetupMessage.book_id == book_id, SetupMessage.role == "assistant")
        .order_by(SetupMessage.id.desc())
        .all()
    )
    any_updated = False
    for m in msgs:
        cards = m.cards_json or []
        if not isinstance(cards, list):
            continue
        updated = False
        new_cards: list = []
        for c in cards:
            if _card_matches_target(c, card_id, card_type, card_title):
                new_cards.append({**c, **card, "status": "applied"})
                updated = True
            else:
                new_cards.append(c)
        if updated:
            m.cards_json = new_cards
            flag_modified(m, "cards_json")
            any_updated = True
    if any_updated:
        db.commit()


def reconcile_cards_with_book(db: Session, book: Book, cards: list) -> list:
    """根据作品存档，恢复卡片「已采纳」状态（兼容历史消息）。"""
    if not cards:
        return cards
    char_names = {c.name for c in db.query(Character).filter(Character.book_id == book.id).all()}
    wv = db.query(Worldview).filter(Worldview.book_id == book.id).first()
    plans_by_no = {
        p.chapter_no: p
        for p in db.query(ChapterPlan).filter(ChapterPlan.book_id == book.id).all()
    }
    result: list = []
    for c in cards:
        if not isinstance(c, dict):
            continue
        card = dict(c)
        if card.get("status") == "applied":
            result.append(card)
            continue
        t = card.get("type")
        data = card.get("data") or {}
        applied = False
        if t == "character" and data.get("name") in char_names:
            applied = True
        elif t == "worldview" and wv and _worldview_complete(wv):
            if data.get("setting") and wv.setting and data.get("setting") == wv.setting:
                applied = True
            elif not data.get("setting"):
                applied = True
        elif t == "premise" and book.genre.strip() and (book.premise or book.blurb or "").strip():
            applied = True
        elif t == "plot":
            pf = book.plot_framework
            if isinstance(pf, dict) and pf:
                applied = True
        elif t == "outline":
            nums = _outline_chapter_nums(card)
            if nums and all(
                n in plans_by_no and (plans_by_no[n].plot_points or "").strip()
                for n in nums
            ):
                applied = True
        if applied:
            card["status"] = "applied"
        result.append(card)
    return result


def sync_reconciled_card_statuses(db: Session, book: Book) -> int:
    """将 reconcile 得到的已采纳状态写回消息表，避免刷新后丢失。"""
    msgs = (
        db.query(SetupMessage)
        .filter(SetupMessage.book_id == book.id, SetupMessage.role == "assistant")
        .all()
    )
    updated = 0
    for m in msgs:
        raw = m.cards_json or []
        if not isinstance(raw, list) or not raw:
            continue
        reconciled = reconcile_cards_with_book(db, book, raw)
        changed = False
        for i, r in enumerate(reconciled):
            if not isinstance(r, dict):
                continue
            o = raw[i] if i < len(raw) else {}
            if isinstance(o, dict) and r.get("status") != o.get("status"):
                changed = True
                break
        if changed:
            m.cards_json = reconciled
            flag_modified(m, "cards_json")
            updated += 1
    if updated:
        db.commit()
    return updated


def _extract_json_blob(text: str) -> str | None:
    text = text.strip()
    if text.startswith("```"):
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            text = m.group(1).strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return None


def _finalize_parsed(
    parsed: dict[str, Any],
    raw: str,
    *,
    progress: dict[str, Any] | None = None,
    intent: str = "general",
) -> dict[str, Any]:
    """确保 reply / cards 至少有一项可用，避免空返回。"""
    cards = parsed.get("cards") or []
    reply = _sanitize_reply(str(parsed.get("reply") or "").strip())

    if not cards and raw.strip():
        salvaged = _extract_json_array_after_key(raw, "cards")
        if salvaged:
            cards = _normalize_cards_list(salvaged)

    if not reply and cards:
        reply = _fallback_reply(cards)
    elif not reply:
        leaked = _strip_json_leak(raw).strip()
        if leaked and not leaked.startswith("{") and not leaked.startswith("（设定"):
            reply = leaked
        elif cards:
            reply = _fallback_reply(cards)
        elif intent == "guidance" and progress:
            reply = _guidance_fallback(progress)
        elif intent == "outline" and progress:
            if cards:
                reply = reply or _fallback_reply(cards)
            else:
                req = _parse_requested_outline_range(str(progress.get("_user_message") or ""))
                if req:
                    reply = (
                        f"抱歉，第 {req[0]}～{req[1]} 章大纲卡片未能生成。"
                        "请重试；若仍失败，可尝试一次 5 章以内的小批次。"
                    )
                else:
                    reply = (
                        f"请指定要规划的章号范围（例如「第 21～25 章」）。"
                        f"当前已规划 {progress['outline_written']} 章，目标共 {progress['outline_target']} 章。"
                    )
        elif intent == "writing":
            reply = (
                "设定已就绪，可以开始动笔了！点击下方按钮进入专用写作编辑器，"
                "那里有更完整的续写、润色与 lint 检查功能。"
            )
        else:
            reply = (
                "这次没能完整解析回复。请重试；若在设计很多角色，建议每批 2～3 个；"
                "若需进度指引，可直接问「下一步做什么」。"
            )

    parsed["reply"] = reply
    parsed["cards"] = cards
    return parsed


def _assistant_content_for_history(m: SetupMessage) -> str:
    text = (m.content or "").strip()
    if INTERNAL_MARK_RE.search(text):
        text, _ = _recover_cards_from_leaked_text(text)
    cards = m.cards_json or []
    parts: list[str] = []
    if text:
        parts.append(text)
    for c in cards:
        if not isinstance(c, dict):
            continue
        status = c.get("status", "draft")
        title = c.get("title") or c.get("type", "设定")
        ctype = c.get("type", "")
        data = c.get("data") or {}
        extra = ""
        if ctype == "character" and data.get("name"):
            extra = f"，角色 {data['name']}"
        elif ctype == "outline" and isinstance(data.get("chapters"), list):
            extra = f"，共 {len(data['chapters'])} 章"
        parts.append(f"（助手曾输出{ctype}卡片「{title}」状态={status}{extra}）")
    if parts:
        return "\n".join(parts)
    return "（助手上一轮未返回文本）"


def _parse_agent_response_core(raw: str) -> dict[str, Any]:
    """解析 AI 原始输出，不做最终兜底（供重试判断）。"""
    blob = _extract_json_blob(raw)
    data: dict[str, Any] | None = None
    if blob:
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            pass

    if not isinstance(data, dict):
        reply_m = re.search(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)"', raw, re.DOTALL)
        cards_raw: list = _extract_json_array_after_key(raw, "cards") or []
        if not cards_raw:
            cards_m = re.search(r'"cards"\s*:\s*(\[[\s\S]*?\])\s*,\s*"apply_card_ids"', raw)
            if not cards_m:
                cards_m = re.search(r'"cards"\s*:\s*(\[[\s\S]*?\])\s*,\s*"setup_step"', raw)
            if cards_m:
                try:
                    cards_raw = json.loads(cards_m.group(1))
                except json.JSONDecodeError:
                    cards_raw = _salvage_json_objects(cards_m.group(1))
        reply = reply_m.group(1).replace("\\n", "\n").replace('\\"', '"') if reply_m else ""
        if reply or cards_raw:
            data = {"reply": reply, "cards": cards_raw, "apply_card_ids": [], "setup_step": None}
        else:
            return {
                "reply": _strip_json_leak(raw),
                "cards": [],
                "apply_card_ids": [],
                "setup_step": None,
            }

    raw_cards = data.get("cards")
    cards = _normalize_cards_list(raw_cards) if isinstance(raw_cards, list) else []
    reply = _sanitize_reply(str(data.get("reply") or "").strip()) or _strip_json_leak(raw)
    if not reply and str(data.get("reply") or "").strip():
        reply, from_leak = _recover_cards_from_leaked_text(str(data.get("reply")))
        if from_leak and not cards:
            cards = from_leak
    if not cards and raw.strip():
        salvaged = _extract_json_array_after_key(raw, "cards")
        if salvaged:
            cards = _normalize_cards_list(salvaged)
    if not cards and '"chapters"' in raw:
        ch_list = _extract_json_array_after_key(raw, "chapters")
        if ch_list:
            title_m = re.search(r'"title"\s*:\s*"([^"]+)"', raw)
            cards = _normalize_cards_list(
                [
                    {
                        "id": _card_id(),
                        "type": "outline",
                        "title": title_m.group(1) if title_m else "章节大纲",
                        "status": "draft",
                        "data": {"chapters": ch_list},
                    }
                ]
            )

    if not cards:
        reply_raw = str(data.get("reply") or raw)
        _, from_leak = _recover_cards_from_leaked_text(reply_raw)
        if from_leak:
            cards = from_leak

    actions_raw = data.get("actions")
    actions = actions_raw if isinstance(actions_raw, list) else []

    return {
        "reply": reply,
        "cards": cards,
        "apply_card_ids": data.get("apply_card_ids") or [],
        "setup_step": data.get("setup_step"),
        "actions": actions,
    }


def _parse_agent_response(
    raw: str,
    *,
    progress: dict[str, Any] | None = None,
    intent: str = "general",
) -> dict[str, Any]:
    return _finalize_parsed(_parse_agent_response_core(raw), raw, progress=progress, intent=intent)


def _outline_response_has_chapters(parsed: dict[str, Any]) -> bool:
    from app.services.outline_planner import extract_outline_chapters_from_cards

    return bool(extract_outline_chapters_from_cards(parsed.get("cards") or []))


def _needs_retry(raw: str, parsed: dict[str, Any], intent: str = "general") -> bool:
    if not raw or not raw.strip():
        return True
    if intent == "outline":
        return not _outline_response_has_chapters(parsed)
    if parsed.get("cards"):
        return False
    reply = str(parsed.get("reply") or "").strip()
    if not reply:
        return True
    # 进度指引 / 写作导航可以没有卡片
    if intent in ("guidance", "writing") and len(reply) >= 15:
        return False
    if reply.startswith("（设定卡片") or reply.startswith("抱歉，"):
        return True
    return False


def _strip_json_leak(text: str) -> str:
    """若整段是 JSON，尽量只保留 reply 字段供展示。"""
    blob = _extract_json_blob(text)
    if not blob:
        return text.strip()
    try:
        obj = json.loads(blob)
        if isinstance(obj, dict) and obj.get("reply"):
            return str(obj["reply"])
    except json.JSONDecodeError:
        pass
    # 无法解析时截断 JSON 块，避免整段刷屏
    if text.strip().startswith("{"):
        return "（设定卡片已生成，请查看下方卡片；若未显示请重试发送）"
    return text.strip()


def _get_or_create_worldview(db: Session, book: Book) -> Worldview:
    wv = db.query(Worldview).filter(Worldview.book_id == book.id).first()
    if not wv:
        wv = Worldview(book_id=book.id)
        db.add(wv)
        db.flush()
    return wv


def apply_card(db: Session, book: Book, card: dict[str, Any]) -> dict[str, Any]:
    """将卡片数据写入数据库，返回应用结果摘要。"""
    t = str(card.get("type") or "")
    data = card.get("data") or {}
    result = apply_card_by_type(db, book, t, data)
    if result.get("ok"):
        db.commit()
        db.refresh(book)
    return result



def sync_settings_from_messages(db: Session, book: Book) -> dict[str, Any]:
    """将 AI 创作助手中标记「已采纳」的卡片同步到 DB（角色 / 大纲等）。"""
    stats: dict[str, Any] = {
        "cards_applied": 0,
        "outline_chapters": 0,
        "characters_synced": 0,
        "duplicates_removed": 0,
        "errors": [],
    }
    msgs = (
        db.query(SetupMessage)
        .filter(SetupMessage.book_id == book.id, SetupMessage.role == "assistant")
        .order_by(SetupMessage.id)
        .all()
    )
    char_cards: list[dict] = []
    seen_ids: set[str] = set()
    for m in msgs:
        for card in m.cards_json or []:
            if not isinstance(card, dict) or card.get("status") != "applied":
                continue
            card_type = card.get("type")
            if card_type == "character":
                char_cards.append(card)
                continue
            card_id = str(card.get("id") or "")
            if card_type in ("worldview", "premise", "plot", "outline") and card_id:
                if card_id in seen_ids:
                    continue
                seen_ids.add(card_id)
            try:
                apply_card(db, book, {**card, "status": "applied"})
                stats["cards_applied"] += 1
            except Exception as e:
                stats["errors"].append(str(e)[:200])
    if char_cards:
        try:
            from app.services.character_cards import list_character_cards

            existing = list_character_cards(db, book.id)
            # Prefer longer DB fields; do not wipe imported character cards with partial message cards.
            ingest_character_cards(db, book, char_cards + existing, overwrite=False)
            stats["characters_synced"] = len(char_cards)
            stats["cards_applied"] += 1
        except Exception as e:
            stats["errors"].append(str(e)[:200])
    stats["duplicates_removed"] = dedupe_characters_by_name(db, book)
    from app.services.pipeline import ensure_book_chapter_slots, count_outline_planned

    sync_target_chapters_from_plot_framework(book)
    ensure_book_chapter_slots(db, book)
    planned = resolve_effective_target_chapters(book)
    outline_planned = count_outline_planned(db, book.id)
    stats["outline_planned_count"] = outline_planned
    stats["outline_chapters"] = outline_planned
    stats["planned_chapters"] = planned
    stats["target_chapters"] = planned
    return stats


def list_messages(db: Session, book_id: int) -> list[SetupMessage]:
    return (
        db.query(SetupMessage)
        .filter(SetupMessage.book_id == book_id)
        .order_by(SetupMessage.id)
        .all()
    )


def ensure_welcome(db: Session, book: Book) -> SetupMessage | None:
    if list_messages(db, book.id):
        return None
    msg = SetupMessage(
        book_id=book.id,
        role="assistant",
        content=WELCOME,
        cards_json=[],
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


async def chat_turn(
    db: Session,
    user: User,
    book: Book,
    user_message: str,
    *,
    stream_emit: StreamEmit | None = None,
) -> tuple[SetupMessage, SetupMessage, list[dict]]:
    """处理一轮对话，返回 (user_msg, assistant_msg, applied_results)。"""
    def _progress(step: str, detail: str = "", **extra: Any) -> None:
        if stream_emit:
            stream_emit("progress", {"step": step, "detail": detail, **extra})

    _progress("understand", "理解您的指令…")
    if sync_target_chapters_from_plot_framework(book):
        db.commit()
        db.refresh(book)
    history = list_messages(db, book.id)
    snapshot = _book_snapshot(db, book)
    progress = snapshot["progress"]
    progress["_user_message"] = user_message

    history_for_ai: list[dict] = []
    for m in history:
        if m.role == "system":
            continue
        content = _assistant_content_for_history(m) if m.role == "assistant" else m.content
        history_for_ai.append({"role": m.role, "content": content})

    # 阶段一：语义理解
    understanding = await understand_setup_message(user, user_message, history_for_ai, snapshot)
    intent = understanding.get("intent") or _detect_intent(user_message)
    if understanding.get("intent") == "brainstorm":
        intent = "general"  # 创书助手用 general + hint 处理 brainstorm

    messages_for_ai: list[dict] = [{"role": "system", "content": _system_prompt(book, snapshot)}]
    messages_for_ai.append({"role": "system", "content": setup_execution_hint(understanding, user_message)})
    for m in history:
        if m.role == "system":
            continue
        content = _assistant_content_for_history(m) if m.role == "assistant" else m.content
        messages_for_ai.append({"role": m.role, "content": content})

    hint = _intent_hint(intent, progress, user_message)
    if hint:
        messages_for_ai.append({"role": "system", "content": hint})

    shard = _compute_shard_plan(book, progress, user_message)
    if shard:
        messages_for_ai.append({"role": "system", "content": _long_form_hint(shard, user_message)})

    outline_ctx: dict[str, Any] | None = None
    if intent == "outline":
        from app.services.outline_planner import (
            build_outline_planning_context,
            delete_chapter_plans_in_range,
            format_outline_planning_block,
            is_outline_regenerate_request,
            resolve_outline_batch_range,
        )

        start_ch, end_ch = resolve_outline_batch_range(book, progress, user_message)
        if is_outline_regenerate_request(user_message):
            _progress("delete_outline", f"删除第 {start_ch}～{end_ch} 章已有大纲…", start=start_ch, end=end_ch)
            removed = delete_chapter_plans_in_range(db, book, start_ch, end_ch)
            db.refresh(book)
            snapshot = _book_snapshot(db, book)
            progress = snapshot["progress"]
            progress["_user_message"] = user_message
            messages_for_ai.append(
                {
                    "role": "system",
                    "content": (
                        f"【系统】用户要求删除第 {start_ch}～{end_ch} 章已有大纲并重新生成。"
                        f"已从作品存档清除 {removed} 章大纲记录。请重新输出该范围的 outline 卡片。"
                    ),
                }
            )

        _progress("context", f"加载设定上下文（第 {start_ch}～{end_ch} 章）…", start=start_ch, end=end_ch)
        outline_ctx = build_outline_planning_context(db, book, start_ch=start_ch, end_ch=end_ch)
        messages_for_ai.append({"role": "system", "content": format_outline_planning_block(outline_ctx)})

    messages_for_ai.append({"role": "user", "content": user_message})

    user_msg = SetupMessage(book_id=book.id, role="user", content=user_message, cards_json=[])
    db.add(user_msg)
    db.flush()

    from app.services.image_gen import maybe_handle_chat_image

    setup_history = [{"role": m.role, "content": m.content} for m in history if m.role != "system"]
    setup_meta = [(m.meta_json or {}) for m in history if m.role == "assistant"]
    img_result = await maybe_handle_chat_image(
        db,
        user,
        book,
        user_message,
        history=setup_history,
        history_meta=setup_meta,
    )
    if img_result and img_result.get("handled"):
        images = img_result.get("images") or []
        assistant_msg = SetupMessage(
            book_id=book.id,
            role="assistant",
            content=str(img_result.get("reply") or ""),
            cards_json=[],
            actions_json=[],
            meta_json={"images": images},
        )
        db.add(assistant_msg)
        db.commit()
        db.refresh(user_msg)
        db.refresh(assistant_msg)
        return user_msg, assistant_msg, []

    chat_temp = 0.65 if intent == "outline" else 0.85
    gen_detail = "AI 正在生成回复…"
    if intent == "outline" and outline_ctx:
        gen_detail = f"AI 正在规划第 {outline_ctx.get('start_ch')}～{outline_ctx.get('end_ch')} 章大纲…"
    _progress("generate", gen_detail)
    raw = await _chat(user, messages_for_ai, temperature=chat_temp, max_tokens=16384, json_object=True)
    parsed_core = _parse_agent_response_core(raw)

    if _needs_retry(raw, parsed_core, intent):
        retry_hint = {
            "guidance": "用户在问下一步指引。请根据作品存档回复，cards 可为空，不要谈角色数量限制。",
            "outline": (
                f"用户要规划大纲。必须输出 cards 数组，且含 type=outline 卡片（最多 {OUTLINE_MAX_BATCH} 章），"
                "每章含 chapter_no/title/plot_points/scene/cast/events；禁止只回复文字而不输出 cards。"
            ),
            "character": "请输出 character 卡片，每批最多 3 个。",
            "writing": "用户要进入写作阶段。cards 必须为空，reply 鼓励去写作编辑器，并输出 actions 数组（write_chapter/open_outline/open_overview）。",
        }.get(intent, "请输出合法 JSON，reply 必填。")
        retry_msgs = messages_for_ai + [{"role": "user", "content": f"上次回复无效。{retry_hint}"}]
        _progress("generate", "上次未生成卡片，正在重试…")
        raw = await _chat(user, retry_msgs, temperature=0.7, max_tokens=16384, json_object=True)
        parsed_core = _parse_agent_response_core(raw)

    if not parsed_core.get("cards"):
        for source in (parsed_core.get("reply", ""), raw):
            _, recovered = _recover_cards_from_leaked_text(str(source))
            if recovered:
                parsed_core["cards"] = recovered
                break

    if intent == "outline" and not _outline_response_has_chapters(parsed_core) and outline_ctx:
        from app.services.outline_planner import generate_outline_cards_for_range

        _progress("generate_fallback", "正在专用通道生成大纲卡片…")
        fallback_cards = await generate_outline_cards_for_range(
            user, outline_ctx, stream_emit=stream_emit
        )
        if fallback_cards:
            parsed_core["cards"] = fallback_cards
            if not str(parsed_core.get("reply") or "").strip():
                parsed_core["reply"] = _fallback_reply(fallback_cards)

    parsed = _finalize_parsed(
        parsed_core, raw, progress={**progress, "_user_message": user_message}, intent=intent
    )

    if understanding.get("intent") == "brainstorm" and not understanding.get("allow_cards"):
        parsed["cards"] = []
        reply = str(parsed.get("reply") or "")
        weak = len(reply) < 80 or (("如下" in reply or "以下" in reply) and "《" not in reply and reply.count("\n") < 2)
        if weak:
            parsed = await execute_brainstorm_plain(user, messages_for_ai, understanding, user_message)
            parsed["cards"] = []
            parsed["apply_card_ids"] = []
            parsed["actions"] = []

    # 保存前：从 reply/raw 回收卡片，杜绝仅泄漏文本无卡片
    if not parsed.get("cards") and understanding.get("intent") != "brainstorm":
        for source in (parsed.get("reply", ""), raw):
            _, recovered = _recover_cards_from_leaked_text(str(source))
            if recovered:
                parsed["cards"] = recovered
                break
    if INTERNAL_MARK_RE.search(str(parsed.get("reply", ""))):
        cleaned, rec = _recover_cards_from_leaked_text(str(parsed["reply"]))
        parsed["reply"] = cleaned or (_fallback_reply(parsed["cards"]) if parsed.get("cards") else "")
        if rec and not parsed.get("cards"):
            parsed["cards"] = rec

    outline_review_meta: dict[str, Any] | None = None
    if intent == "outline" and parsed.get("cards"):
        from app.services.outline_planner import (
            build_outline_planning_context,
            format_outline_review_for_reply,
            resolve_outline_batch_range,
            run_outline_quality_pipeline,
        )

        if outline_ctx is None:
            start_ch, end_ch = resolve_outline_batch_range(book, progress, user_message)
            outline_ctx = build_outline_planning_context(db, book, start_ch=start_ch, end_ch=end_ch)
        revised_cards, review = await run_outline_quality_pipeline(
            user, db, book, parsed["cards"], outline_ctx, auto_fix=True, stream_emit=stream_emit
        )
        parsed["cards"] = revised_cards
        review_suffix = format_outline_review_for_reply(review, review.get("issues") or [])
        if review_suffix and review_suffix not in str(parsed.get("reply") or ""):
            parsed["reply"] = (parsed.get("reply") or "").strip() + review_suffix
        if review.get("fix_reply"):
            parsed["reply"] = (parsed.get("reply") or "").strip() + "\n\n" + str(review["fix_reply"]).strip()
        outline_review_meta = review

    # 写作阶段：剥离草稿卡片，强制导航 actions
    actions: list[dict] = []
    if intent == "writing":
        parsed["cards"] = [
            c for c in (parsed.get("cards") or [])
            if "draft" not in str(c.get("type", ""))
        ]
        raw_actions = parsed.get("actions") or []
        actions = raw_actions if isinstance(raw_actions, list) and raw_actions else _suggest_writing_actions(db, book)
        if not parsed.get("actions"):
            parsed["actions"] = actions
        book.setup_step = 5
        db.commit()
        db.refresh(book)
    elif parsed.get("actions"):
        actions = parsed["actions"] if isinstance(parsed["actions"], list) else []

    applied_results: list[dict] = []
    cards = _normalize_cards_list(parsed.get("cards") or [])
    apply_ids = set(parsed.get("apply_card_ids") or [])

    for card in cards:
        if card.get("id") in apply_ids:
            res = apply_card(db, book, card)
            card["status"] = "applied"
            applied_results.append({**res, "card_id": card["id"]})

    # 改名/改简介：若 LLM 仅口头确认未 apply，补写入
    if is_apply_book_meta_message(user_message) and not any(r.get("type") == "premise" for r in applied_results):
        title = extract_title_from_message(user_message) or extract_title_from_message(str(parsed.get("reply") or ""))
        if title and book.title.strip() != title.strip():
            card = {
                "id": f"premise_{uuid.uuid4().hex[:10]}",
                "type": "premise",
                "title": title,
                "status": "applied",
                "data": {
                    "title": title,
                    "genre": book.genre or "",
                    "premise": book.premise or book.blurb or "",
                    "blurb": book.blurb or book.premise or "",
                    "target_chapters": book.target_chapters,
                },
            }
            res = apply_card(db, book, card)
            cards = [card]
            applied_results.append({**res, "card_id": card["id"]})
            db.refresh(book)

    # 泄漏文本含 draft 类型时确保有 actions
    if intent == "writing" and not actions:
        actions = _suggest_writing_actions(db, book)

    if parsed.get("setup_step") and isinstance(parsed["setup_step"], int):
        step = max(1, min(5, parsed["setup_step"]))
        if step > book.setup_step:
            book.setup_step = step
            db.commit()
            db.refresh(book)

    _progress("finalize", "整理回复并保存…")
    assistant_msg = SetupMessage(
        book_id=book.id,
        role="assistant",
        content=parsed["reply"],
        cards_json=cards,
        actions_json=actions,
        meta_json=(
            {
                "outline_review": {
                    "overall_ok": outline_review_meta.get("overall_ok"),
                    "issues": outline_review_meta.get("issues") or [],
                    "summary": outline_review_meta.get("summary") or "",
                }
            }
            if outline_review_meta
            else {}
        ),
    )
    db.add(assistant_msg)
    db.commit()
    db.refresh(user_msg)
    db.refresh(assistant_msg)
    return user_msg, assistant_msg, applied_results


async def finish_setup(db: Session, user: User, book: Book) -> Book:
    """完成向导：生成本书写作偏好并标记 setup_step=5。"""
    if not book.writing_rules:
        await generate_writing_rules(db, user, book)
    book.setup_step = 5
    db.commit()
    db.refresh(book)
    return book
