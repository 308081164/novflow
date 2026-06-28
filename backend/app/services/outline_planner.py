"""章节大纲规划：上下文注入、质量规约与一致性校验。"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import Book, Character, ChapterPlan, Worldview
from app.services.ai_assist import _chat
from app.services.context_limits import (
    CHARACTER_DETAIL_CHARS,
    OUTLINE_FRAMEWORK_CHARS,
    OUTLINE_PLAN_LINE_CHARS,
    WORLD_SETTING_CHARS,
)
from app.services.system_writing_rules import combine_writing_rules, get_system_rules


def _resolve_target_chapters(book: Book) -> int:
    from app.services.setup_agent import resolve_effective_target_chapters

    return resolve_effective_target_chapters(book)


def _parse_range(user_message: str) -> tuple[int, int] | None:
    from app.services.setup_agent import _parse_requested_outline_range

    return _parse_requested_outline_range(user_message)


def _truncate(text: str | None, limit: int) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[: limit - 1] + "…"


def _plot_phase_for_chapters(book: Book, start_ch: int, end_ch: int) -> dict[str, Any] | None:
    pf = book.plot_framework
    if not isinstance(pf, dict):
        return None
    for phase in pf.get("phases") or []:
        if not isinstance(phase, dict):
            continue
        cr = phase.get("chapter_range") or phase.get("name") or ""
        nums = [int(x) for x in re.findall(r"\d+", str(cr))]
        if len(nums) >= 2:
            lo, hi = min(nums[0], nums[1]), max(nums[0], nums[1])
            if start_ch <= hi and end_ch >= lo:
                return phase
        elif len(nums) == 1 and nums[0] == start_ch:
            return phase
    return None


def build_outline_planning_context(
    db: Session,
    book: Book,
    *,
    start_ch: int,
    end_ch: int,
) -> dict[str, Any]:
    """收集大纲规划所需的完整设定上下文。"""
    wv = db.query(Worldview).filter(Worldview.book_id == book.id).first()
    chars = db.query(Character).filter(Character.book_id == book.id).order_by(Character.id).all()
    all_plans = (
        db.query(ChapterPlan)
        .filter(ChapterPlan.book_id == book.id, ChapterPlan.plot_points != "")
        .order_by(ChapterPlan.chapter_no)
        .all()
    )
    prev_plans = [p for p in all_plans if p.chapter_no < start_ch]
    target_total = _resolve_target_chapters(book)
    pf = book.plot_framework if isinstance(book.plot_framework, dict) else {}
    phase = _plot_phase_for_chapters(book, start_ch, end_ch)

    char_entries = []
    known_names: set[str] = set()
    for c in chars:
        known_names.add(c.name.strip())
        char_entries.append(
            {
                "name": c.name,
                "role": c.role,
                "summary": _truncate(c.summary, 400),
                "voice_notes": _truncate(c.voice_notes, 200),
                "content": _truncate(c.content, CHARACTER_DETAIL_CHARS),
            }
        )

    prev_outline_lines = []
    # 优先取紧邻的前 15 章 + 首批 5 章（伏笔回收）
    prev_nums = sorted({p.chapter_no for p in prev_plans})
    tail = [n for n in prev_nums if n >= max(1, start_ch - 15)]
    head = [n for n in prev_nums if n <= 5]
    selected = sorted(set(tail + head))
    plan_by_no = {p.chapter_no: p for p in prev_plans}
    for no in selected:
        p = plan_by_no[no]
        cast = p.character_names or ""
        meta = p.meta_json if isinstance(p.meta_json, dict) else {}
        events = meta.get("events") or []
        ev_text = "；".join(str(e) for e in events[:3]) if events else ""
        prev_outline_lines.append(
            f"第{no}章《{p.title}》\n"
            f"  情节：{_truncate(p.plot_points, OUTLINE_PLAN_LINE_CHARS)}\n"
            f"  场景：{p.scene or '—'} | 出场：{cast or '—'}"
            + (f"\n  关键事件：{ev_text}" if ev_text else "")
        )

    return {
        "start_ch": start_ch,
        "end_ch": end_ch,
        "target_total": target_total,
        "premise": _truncate(book.premise or book.blurb, 800),
        "genre": book.genre or "",
        "writing_rules": _truncate(combine_writing_rules(book), 4000),
        "system_rules_summary": _truncate(get_system_rules(book.platform), 1200),
        "worldview": {
            "era": wv.era if wv else "",
            "setting": wv.setting if wv else "",
            "tone": wv.tone if wv else "",
            "taboos": wv.taboos if wv else "",
            "content": _truncate(wv.content if wv else "", WORLD_SETTING_CHARS),
        },
        "plot_framework": pf,
        "plot_framework_text": _truncate(json.dumps(pf, ensure_ascii=False), OUTLINE_FRAMEWORK_CHARS)
        if pf
        else "",
        "current_phase": phase,
        "characters": char_entries,
        "known_character_names": sorted(known_names),
        "previous_outlines": prev_outline_lines,
        "outline_written_count": len(all_plans),
    }


def format_outline_planning_block(ctx: dict[str, Any]) -> str:
    """格式化为注入 LLM 的大纲规划上下文块。"""
    lines = [
        "## 【大纲规划 · 权威设定上下文】（必须严格参照，禁止与之冲突）",
        f"本批规划范围：第 {ctx['start_ch']}～{ctx['end_ch']} 章（全书目标 {ctx['target_total']} 章，已规划 {ctx['outline_written_count']} 章）",
        "",
        "### 作品定位",
        f"- 类型：{ctx.get('genre') or '未设定'}",
        f"- 梗概：{ctx.get('premise') or '未设定'}",
        "",
        "### 写作规约与偏好（大纲须符合后续正文写法）",
        ctx.get("writing_rules") or "（暂无写作偏好，请遵循平台通用规约）",
        "",
        "### 世界观",
    ]
    wv = ctx.get("worldview") or {}
    if any(wv.values()):
        for k, label in (
            ("era", "时代"),
            ("setting", "舞台"),
            ("tone", "基调"),
            ("taboos", "禁忌"),
            ("content", "详情"),
        ):
            if wv.get(k):
                lines.append(f"- {label}：{wv[k]}")
    else:
        lines.append("（尚未设定世界观）")

    lines.extend(["", "### 长线剧情框架（本批须落在对应阶段内）"])
    phase = ctx.get("current_phase")
    if phase:
        lines.append(
            f"**当前阶段**：{phase.get('name') or '—'} | 章段 {phase.get('chapter_range') or '—'}\n"
            f"{_truncate(phase.get('description') or '', 600)}"
        )
    pf_text = ctx.get("plot_framework_text")
    if pf_text:
        lines.append(f"\n完整框架存档：\n{pf_text}")
    elif not phase:
        lines.append("（尚无 plot 框架；若已有用户讨论过的阶段划分，须保持一致）")

    lines.extend(["", "### 角色卡（cast 只能使用下列姓名，新角色须写在 entrances）"])
    chars = ctx.get("characters") or []
    if chars:
        for c in chars:
            lines.append(
                f"- **{c['name']}**（{c.get('role') or 'support'}）\n"
                f"  摘要：{c.get('summary') or '—'}\n"
                f"  口吻：{c.get('voice_notes') or '—'}\n"
                f"  详情：{c.get('content') or '—'}"
            )
    else:
        lines.append("（暂无角色卡，须先补充核心角色）")

    prev = ctx.get("previous_outlines") or []
    lines.extend(["", "### 已采纳的前序章节大纲（必须承接，禁止吃书/改设定）"])
    if prev:
        lines.extend(prev)
        if ctx["start_ch"] > 1:
            lines.append(
                f"\n⚠ 第 {ctx['start_ch']} 章须直接承接第 {ctx['start_ch'] - 1} 章结尾的情势与人物状态。"
            )
    else:
        lines.append("（尚无已采纳大纲；若为开篇批次，须符合梗概与 plot 第一阶段）")

    lines.extend(
        [
            "",
            "### 大纲输出质量要求",
            "1. 每章必填：chapter_no, title, plot_points（200字以上具体情节）, scene, cast（角色卡姓名）, events（2～4个关键事件）",
            "2. entrances/exits：新登场或退场角色须明确列出",
            "3. 角色能力/等级/身份须与角色卡一致；冲突须符合 worldview 禁忌与 tone",
            "4. 须体现本书写作偏好（POV、节奏、类型元素等）",
            "5. 禁止与已采纳前序大纲矛盾；禁止凭空添加未在 entrances 说明的重要新角色",
            "6. reply 末尾须简要说明：本批如何承接前序、如何落在当前 plot 阶段",
        ]
    )
    return "\n".join(lines)


def resolve_outline_batch_range(
    book: Book,
    progress: dict[str, Any],
    user_message: str,
) -> tuple[int, int]:
    from app.services.setup_agent import _compute_shard_plan

    shard = _compute_shard_plan(book, progress, user_message)
    if shard:
        return int(shard["next_start"]), int(shard["next_end"])
    req = _parse_range(user_message)
    if req:
        return req
    written = int(progress.get("outline_written") or 0)
    start = written + 1
    end = min(start + 4, int(progress.get("outline_target") or _resolve_target_chapters(book)))
    return start, max(start, end)


def _collect_cast_names(ch: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for key in ("cast", "characters"):
        val = ch.get(key)
        if isinstance(val, list):
            names.update(str(x).strip() for x in val if str(x).strip())
        elif isinstance(val, str) and val.strip():
            names.add(val.strip())
    cn = ch.get("character_names")
    if isinstance(cn, str) and cn.strip():
        for part in re.split(r"[、,，/]", cn):
            if part.strip():
                names.add(part.strip())
    return names


def validate_outline_chapters_rule(
    ctx: dict[str, Any],
    chapters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """规则引擎：快速检测大纲与设定/前序的明显冲突。"""
    issues: list[dict[str, Any]] = []
    known = set(ctx.get("known_character_names") or [])
    start_ch, end_ch = ctx["start_ch"], ctx["end_ch"]
    seen_nos: set[int] = set()

    for ch in chapters:
        if not isinstance(ch, dict):
            continue
        try:
            no = int(ch.get("chapter_no") or 0)
        except (TypeError, ValueError):
            no = 0
        if no < 1:
            issues.append(
                {
                    "chapter_no": no,
                    "severity": "error",
                    "category": "format",
                    "message": "缺少有效 chapter_no",
                }
            )
            continue
        if no in seen_nos:
            issues.append(
                {
                    "chapter_no": no,
                    "severity": "error",
                    "category": "format",
                    "message": "章节号重复",
                }
            )
        seen_nos.add(no)
        if no < start_ch or no > end_ch:
            issues.append(
                {
                    "chapter_no": no,
                    "severity": "error",
                    "category": "range",
                    "message": f"章号 {no} 不在本批范围 {start_ch}～{end_ch}",
                }
            )
        plot = (ch.get("plot_points") or ch.get("synopsis") or "").strip()
        if len(plot) < 40:
            issues.append(
                {
                    "chapter_no": no,
                    "severity": "warn",
                    "category": "quality",
                    "message": "plot_points 过短，情节不够具体",
                }
            )
        cast = _collect_cast_names(ch)
        entrances = ch.get("entrances") or []
        if isinstance(entrances, str):
            entrances = [entrances]
        entrance_set = {str(x).strip() for x in entrances if str(x).strip()}
        for name in cast:
            if name not in known and name not in entrance_set:
                issues.append(
                    {
                        "chapter_no": no,
                        "severity": "error",
                        "category": "character",
                        "message": f"出场角色「{name}」不在角色卡中，且未列入 entrances",
                    }
                )

    if start_ch > 1 and not ctx.get("previous_outlines"):
        issues.append(
            {
                "chapter_no": start_ch,
                "severity": "warn",
                "category": "continuity",
                "message": "缺少已采纳前序大纲，请确认承接关系",
            }
        )
    return issues


async def review_outline_chapters_llm(
    user,
    ctx: dict[str, Any],
    chapters: list[dict[str, Any]],
) -> dict[str, Any]:
    """LLM 深度一致性审阅。"""
    if not chapters:
        return {"overall_ok": True, "issues": [], "summary": ""}

    payload = {
        "chapters": chapters,
        "context_summary": {
            "range": f"{ctx['start_ch']}-{ctx['end_ch']}",
            "known_characters": ctx.get("known_character_names"),
            "current_phase": ctx.get("current_phase"),
            "previous_outline_count": len(ctx.get("previous_outlines") or []),
        },
    }
    system = """你是网文大纲质检编辑。根据提供的设定上下文与新大纲批次，检查：
1. 与角色卡（身份/能力/性格）是否矛盾
2. 与长线 plot 阶段目标是否匹配
3. 与前序章节大纲是否衔接
4. 是否符合写作偏好与世界观禁忌
5. 情节是否足够具体、有无逻辑跳跃

输出纯 JSON：
{
  "overall_ok": true/false,
  "summary": "一段话总评",
  "issues": [
    {"chapter_no": 1, "severity": "error|warn", "category": "character|plot|continuity|prefs|quality", "message": "..."}
  ]
}
error=必须修正才能采纳；warn=建议优化。"""

    user_content = (
        format_outline_planning_block(ctx)
        + "\n\n## 待审阅的大纲批次 JSON\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    raw = await _chat(
        user,
        [{"role": "system", "content": system}, {"role": "user", "content": user_content}],
        temperature=0.2,
        max_tokens=4096,
        json_object=True,
    )
    blob = raw.strip()
    if blob.startswith("```"):
        blob = re.sub(r"^```(?:json)?\s*", "", blob)
        blob = re.sub(r"\s*```$", "", blob)
    try:
        data = json.loads(blob)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return {"overall_ok": True, "issues": [], "summary": "", "parse_failed": True}


def merge_outline_issues(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple] = set()
    merged: list[dict[str, Any]] = []
    for group in groups:
        for item in group:
            if not isinstance(item, dict):
                continue
            key = (item.get("chapter_no"), item.get("category"), item.get("message"))
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def format_outline_review_for_reply(review: dict[str, Any], issues: list[dict[str, Any]]) -> str:
    lines = []
    summary = (review.get("summary") or "").strip()
    if summary:
        lines.append(f"\n\n**大纲自检**：{summary}")
    errors = [i for i in issues if i.get("severity") == "error"]
    warns = [i for i in issues if i.get("severity") == "warn"]
    if errors:
        lines.append("\n**须修正的问题**：")
        for i in errors[:8]:
            lines.append(f"- 第{i.get('chapter_no')}章 [{i.get('category')}]: {i.get('message')}")
    if warns:
        lines.append("\n**建议优化**：")
        for i in warns[:5]:
            lines.append(f"- 第{i.get('chapter_no')}章: {i.get('message')}")
    if errors:
        lines.append("\n请说「按检查结果修订大纲」可让我自动修正本批后再采纳。")
    elif not warns and review.get("overall_ok"):
        lines.append("\n✅ 与本批设定、角色卡及前序大纲一致性检查通过，可采纳。")
    return "".join(lines)


def normalize_outline_data(data: Any) -> dict[str, Any]:
    """统一 outline 卡片 data：LLM 偶发直接输出章节数组而非 {chapters: [...]}。"""
    if isinstance(data, list):
        return {"chapters": [c for c in data if isinstance(c, dict)]}
    if isinstance(data, dict):
        batch = data.get("chapters")
        if isinstance(batch, list):
            return data
        if not batch and any(isinstance(v, dict) and v.get("chapter_no") for v in data.values()):
            return {"chapters": [v for v in data.values() if isinstance(v, dict)]}
    return {"chapters": []}


def extract_outline_chapters_from_cards(cards: list[dict]) -> list[dict[str, Any]]:
    chapters: list[dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict) or card.get("type") != "outline":
            continue
        normalized = normalize_outline_data(card.get("data"))
        batch = normalized.get("chapters") or []
        if isinstance(batch, list):
            chapters.extend(c for c in batch if isinstance(c, dict))
    return chapters


def is_outline_regenerate_request(user_message: str) -> bool:
    """用户要求删除指定范围大纲后重新生成。"""
    if not _parse_range(user_message):
        return False
    msg = user_message.strip()
    patterns = (
        r"删除.*重新",
        r"删掉.*再",
        r"清除.*再",
        r"重新生成",
        r"重新规划",
        r"重新写",
        r"重做",
    )
    return any(re.search(p, msg) for p in patterns)


def delete_chapter_plans_in_range(db: Session, book: Book, start_ch: int, end_ch: int) -> int:
    """删除指定章号范围内的大纲（ChapterPlan 清空 plot_points）。"""
    lo, hi = min(start_ch, end_ch), max(start_ch, end_ch)
    plans = (
        db.query(ChapterPlan)
        .filter(
            ChapterPlan.book_id == book.id,
            ChapterPlan.chapter_no >= lo,
            ChapterPlan.chapter_no <= hi,
        )
        .all()
    )
    deleted = 0
    for plan in plans:
        if (plan.plot_points or "").strip():
            plan.plot_points = ""
            plan.title = f"第{plan.chapter_no}章"
            plan.comedy_core = ""
            plan.scene = ""
            plan.character_names = ""
            plan.meta_json = {}
            deleted += 1
    if deleted:
        db.commit()
    return deleted


async def refine_outline_cards_with_issues(
    user,
    ctx: dict[str, Any],
    cards: list[dict],
    issues: list[dict[str, Any]],
) -> tuple[list[dict], str]:
    """根据质检问题自动修订 outline 卡片（一次）。"""
    outline_chs = extract_outline_chapters_from_cards(cards)
    if not outline_chs or not issues:
        return cards, ""

    error_lines = "\n".join(
        f"- 第{i.get('chapter_no')}章 [{i.get('category')}]: {i.get('message')}" for i in issues if i.get("severity") == "error"
    )[:3000]
    system = """你是大纲编辑。根据设定上下文与质检问题，修订 outline 卡片 JSON。
输出格式与创书助手相同：{"reply":"...", "cards":[{type:"outline", ...}], "apply_card_ids":[], "setup_step": null}
只输出一个 outline 卡片，修正所有 error 级问题，保留章号范围不变。"""

    user_content = (
        format_outline_planning_block(ctx)
        + f"\n\n## 当前大纲 JSON\n{json.dumps(outline_chs, ensure_ascii=False)}"
        + f"\n\n## 必须修正\n{error_lines}"
    )
    raw = await _chat(
        user,
        [{"role": "system", "content": system}, {"role": "user", "content": user_content}],
        temperature=0.35,
        max_tokens=12000,
        json_object=True,
    )
    try:
        data = json.loads(raw)
        new_cards = data.get("cards") or []
        if new_cards:
            reply_extra = str(data.get("reply") or "").strip()
            return new_cards, reply_extra
    except json.JSONDecodeError:
        pass
    return cards, ""


def _emit_progress(stream_emit, step: str, detail: str = "", **extra: Any) -> None:
    if stream_emit:
        stream_emit("progress", {"step": step, "detail": detail, **extra})


async def run_outline_quality_pipeline(
    user,
    db: Session,
    book: Book,
    cards: list[dict],
    ctx: dict[str, Any],
    *,
    auto_fix: bool = True,
    stream_emit=None,
) -> tuple[list[dict], dict[str, Any]]:
    """规则 + LLM 审阅；若有 error 且 auto_fix 则尝试自动修订一次。"""
    # 规范化卡片 data，避免后续 .get 报错
    cards = [
        {**c, "data": normalize_outline_data(c.get("data"))} if c.get("type") == "outline" else c
        for c in cards
    ]

    chapters = extract_outline_chapters_from_cards(cards)
    if not chapters:
        return cards, {"overall_ok": True, "issues": [], "summary": ""}

    _emit_progress(stream_emit, "review_rules", "规则一致性校验中…", count=len(chapters))
    rule_issues = validate_outline_chapters_rule(ctx, chapters)

    _emit_progress(stream_emit, "review_llm", "AI 深度审阅大纲逻辑…")
    llm_review = await review_outline_chapters_llm(user, ctx, chapters)
    all_issues = merge_outline_issues(rule_issues, llm_review.get("issues") or [])
    review = {**llm_review, "issues": all_issues}

    errors = [i for i in all_issues if i.get("severity") == "error"]
    if auto_fix and errors:
        _emit_progress(
            stream_emit,
            "auto_fix",
            f"发现 {len(errors)} 处问题，自动修订中…",
            error_count=len(errors),
        )
        new_cards, fix_reply = await refine_outline_cards_with_issues(user, ctx, cards, all_issues)
        if new_cards != cards:
            cards = [
                {**c, "data": normalize_outline_data(c.get("data"))} if c.get("type") == "outline" else c
                for c in new_cards
            ]
            _emit_progress(stream_emit, "review_rules", "修订后再次规则校验…")
            chapters = extract_outline_chapters_from_cards(cards)
            rule_issues2 = validate_outline_chapters_rule(ctx, chapters)
            _emit_progress(stream_emit, "review_llm", "修订后再次 AI 审阅…")
            llm_review2 = await review_outline_chapters_llm(user, ctx, chapters)
            all_issues2 = merge_outline_issues(rule_issues2, llm_review2.get("issues") or [])
            review = {**llm_review2, "issues": all_issues2, "auto_fixed": True, "fix_reply": fix_reply}

    _emit_progress(stream_emit, "review_done", "大纲质检完成")
    return cards, review


async def generate_outline_cards_for_range(
    user,
    ctx: dict[str, Any],
    *,
    stream_emit=None,
) -> list[dict]:
    """主对话未产出 outline 卡片时的专用生成通道（强制 JSON + outline 卡片）。"""
    start_ch = int(ctx["start_ch"])
    end_ch = int(ctx["end_ch"])
    count = end_ch - start_ch + 1

    system = f"""你是网文章节大纲策划。必须输出合法 JSON，格式：
{{"reply":"一句话说明","cards":[{{"id":"outline_xxx","type":"outline","title":"第{start_ch}-{end_ch}章大纲","status":"draft","data":{{"chapters":[...]}}}}],"apply_card_ids":[],"setup_step":null}}

硬性要求：
1. cards 必须含且仅含 1 张 type=outline 卡片，禁止 cards 为空
2. chapters 共 {count} 章，chapter_no 从 {start_ch} 到 {end_ch} 连续无遗漏
3. 每章必填：chapter_no, title, plot_points(200字以上具体情节), scene, cast(角色卡姓名), events(2-4个), entrances, exits
4. 严格参照用户消息中的设定上下文，禁止凭空添加未说明的重要角色"""

    user_content = format_outline_planning_block(ctx)
    _emit_progress(stream_emit, "generate_fallback", f"专用通道生成第 {start_ch}～{end_ch} 章大纲…")

    raw = await _chat(
        user,
        [{"role": "system", "content": system}, {"role": "user", "content": user_content}],
        temperature=0.55,
        max_tokens=16384,
        json_object=True,
    )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    cards_raw = data.get("cards") if isinstance(data, dict) else None
    if not isinstance(cards_raw, list):
        cards_raw = []

    result: list[dict] = []
    for c in cards_raw:
        if not isinstance(c, dict) or c.get("type") != "outline":
            continue
        card = dict(c)
        if not card.get("id"):
            card["id"] = f"outline_{uuid.uuid4().hex[:10]}"
        card.setdefault("status", "draft")
        card.setdefault("title", f"第{start_ch}～{end_ch}章大纲")
        card["data"] = normalize_outline_data(card.get("data"))
        if extract_outline_chapters_from_cards([card]):
            result.append(card)

    if not result and isinstance(data, dict):
        top_chapters = data.get("chapters")
        if isinstance(top_chapters, list) and top_chapters:
            result.append(
                {
                    "id": f"outline_{uuid.uuid4().hex[:10]}",
                    "type": "outline",
                    "title": f"第{start_ch}～{end_ch}章大纲",
                    "status": "draft",
                    "data": {"chapters": [c for c in top_chapters if isinstance(c, dict)]},
                }
            )

    return result
