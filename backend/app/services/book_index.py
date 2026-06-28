"""结构化书籍项目索引：供写作智能体跨章任务快速定位上下文。"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.models import Book, Chapter, ChapterPlan, Character, Worldview
from app.services.chapter_content import get_content
from app.services.character_cards import character_model_to_card
from app.services.prompt_assembler import _format_plot_framework, _format_worldview
from app.services.rule_engine import word_count
from app.services.system_writing_rules import get_author_preferences

EXCERPT_CHARS = 120
INDEX_CHAPTER_BODY_CHARS = 800
MAX_ENTITY_MENTIONS = 12
CHAR_FIELD_PREVIEW = 180
OUTLINE_NODE_CHARS = 220


def _parse_plan_cast(plan: dict[str, Any]) -> list[str]:
    """从章节规划提取出场角色名。"""
    names: list[str] = []
    raw = plan.get("character_names") or ""
    if isinstance(raw, str) and raw.strip():
        for part in re.split(r"[,，、/|；;\s]+", raw):
            p = part.strip()
            if p and p not in names:
                names.append(p)
    meta = plan.get("meta_json") or {}
    if isinstance(meta, dict):
        for key in ("cast", "entrances", "exits"):
            arr = meta.get(key)
            if isinstance(arr, list):
                for x in arr:
                    s = str(x).strip()
                    if s and s not in names:
                        names.append(s)
    return names


def _build_outline_nodes(plans: list) -> list[dict[str, Any]]:
    """结构化大纲节点：章号、标题、情节点、出场角色。"""
    nodes: list[dict[str, Any]] = []
    for p in plans:
        cast = _parse_plan_cast(
            {
                "character_names": getattr(p, "character_names", ""),
                "meta_json": getattr(p, "meta_json", None) or {},
            }
        )
        nodes.append(
            {
                "chapter_no": p.chapter_no,
                "title": p.title or f"第{p.chapter_no}章",
                "plot_points": _truncate(p.plot_points, OUTLINE_NODE_CHARS),
                "scene": getattr(p, "scene", "") or "",
                "cast": cast,
                "comedy_core": _truncate(getattr(p, "comedy_core", "") or "", 80),
            }
        )
    return nodes


def _build_character_summaries(characters: list) -> list[dict[str, Any]]:
    """角色卡字段摘要，供一致性对照。"""
    out: list[dict[str, Any]] = []
    for c in characters:
        out.append(
            {
                "id": c.id,
                "name": c.name,
                "role": c.role or "",
                "summary": _truncate(c.summary or "", CHAR_FIELD_PREVIEW),
                "voice_notes": _truncate(c.voice_notes or "", 100),
                "content_excerpt": _truncate(c.content or "", CHAR_FIELD_PREVIEW),
            }
        )
    return out


def _build_relationship_map(
    characters: list,
    outline_nodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """大纲出场角色 ↔ 角色卡映射。"""
    by_name = {c.name: c for c in characters if c.name}
    edges: list[dict[str, Any]] = []
    for node in outline_nodes:
        for name in node.get("cast") or []:
            ch = by_name.get(name)
            edges.append(
                {
                    "chapter_no": node.get("chapter_no"),
                    "character_name": name,
                    "in_character_db": ch is not None,
                    "character_id": ch.id if ch else None,
                    "character_role": ch.role if ch else "",
                }
            )
    return edges


def _build_cross_reference_hints(
    characters: list,
    outline_nodes: list[dict[str, Any]],
    relationship_map: list[dict[str, Any]],
) -> list[str]:
    """预计算一致性提示，供 LLM 快速定位。"""
    hints: list[str] = []
    by_name = {c.name: c for c in characters if c.name}

    # 大纲提到但未建档的角色
    outline_names: set[str] = set()
    for node in outline_nodes:
        for name in node.get("cast") or []:
            outline_names.add(name)
            if name and name not in by_name:
                hints.append(f"第{node.get('chapter_no')}章大纲出场「{name}」尚无角色卡")

    # 主角/反派角色卡但从未出现在已规划大纲
    important_roles = ("protagonist", "主角", "男主", "antagonist", "反派", "女主")
    appeared = {e["character_name"] for e in relationship_map if e.get("in_character_db")}
    for c in characters:
        role = (c.role or "").lower()
        if any(r in role or r in (c.role or "") for r in important_roles):
            if c.name and c.name not in appeared and outline_nodes:
                hints.append(f"角色「{c.name}」（{c.role}）尚未出现在已规划大纲的 cast 中")

    # 同名角色 role 与大纲描述可能冲突（简单关键词）
    role_keywords = ("会长", "副会长", "师父", "徒弟", "老板", "员工", "S级", "C级", "D级")
    for node in outline_nodes:
        plot = (node.get("plot_points") or "") + (node.get("title") or "")
        for name in node.get("cast") or []:
            ch = by_name.get(name)
            if not ch:
                continue
            card_text = f"{ch.role} {ch.summary} {ch.content}"
            for kw in role_keywords:
                if kw in plot and kw not in card_text and kw in plot:
                    if f"第{node.get('chapter_no')}章大纲含「{kw}」" not in str(hints):
                        hints.append(
                            f"第{node.get('chapter_no')}章大纲含「{kw}」，角色「{name}」卡未提及，建议核对"
                        )
                    break

    return hints[:15]


def _truncate(text: str, limit: int) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[:limit] + "…"


def _paragraph_excerpts(body: str) -> tuple[str, str]:
    """返回首段、末段摘要（跳过空行与纯标题行）。"""
    lines = [ln.strip() for ln in (body or "").split("\n") if ln.strip()]
    paras: list[str] = []
    buf: list[str] = []
    for ln in lines:
        if ln.startswith("#"):
            if buf:
                paras.append(" ".join(buf))
                buf = []
            continue
        buf.append(ln)
        if ln.endswith(("。", "！", "？", "…", "」", "」。")):
            paras.append(" ".join(buf))
            buf = []
    if buf:
        paras.append(" ".join(buf))
    if not paras:
        return "", ""
    first = _truncate(paras[0], EXCERPT_CHARS)
    last = _truncate(paras[-1], EXCERPT_CHARS) if len(paras) > 1 else first
    return first, last


def _extract_key_entities(characters: list[Character], chapter_bodies: dict[int, str]) -> list[dict[str, Any]]:
    """简单实体提及统计：角色名在正文中的出现次数。"""
    names = [c.name.strip() for c in characters if c.name.strip()]
    if not names:
        return []
    combined = "\n".join(chapter_bodies.values())
    counts: list[tuple[str, int]] = []
    for name in names:
        cnt = len(re.findall(re.escape(name), combined))
        if cnt > 0:
            counts.append((name, cnt))
    counts.sort(key=lambda x: -x[1])
    return [{"name": n, "mentions": c} for n, c in counts[:MAX_ENTITY_MENTIONS]]


def build_book_index(
    db: Session,
    book: Book,
    target_chapter_nos: list[int] | None = None,
    *,
    draft_content: str | None = None,
    focus_chapter_no: int | None = None,
) -> dict[str, Any]:
    """构建全书结构化索引快照。"""
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

    focus = focus_chapter_no or (target_chapter_nos[0] if target_chapter_nos else None)
    targets = set(target_chapter_nos or [])

    chapter_entries: list[dict[str, Any]] = []
    bodies: dict[int, str] = {}
    for ch in chapters:
        if focus and ch.chapter_no == focus and draft_content is not None:
            body = draft_content
        else:
            body = get_content(ch)
        bodies[ch.chapter_no] = body
        wc = word_count(body) if body.strip() else 0
        first, last = _paragraph_excerpts(body) if body.strip() else ("", "")
        chapter_entries.append(
            {
                "chapter_no": ch.chapter_no,
                "title": ch.title or f"第{ch.chapter_no}章",
                "status": ch.status,
                "word_count": wc,
                "is_empty": not body.strip(),
                "is_focus": ch.chapter_no == focus,
                "is_target": ch.chapter_no in targets if targets else False,
                "first_excerpt": first,
                "last_excerpt": last,
                "body_preview": _truncate(body.strip(), INDEX_CHAPTER_BODY_CHARS) if body.strip() else "",
            }
        )

    plan_entries = [
        {
            "chapter_no": p.chapter_no,
            "title": p.title,
            "plot_points": _truncate(p.plot_points, 300),
            "scene": p.scene,
            "character_names": p.character_names,
        }
        for p in plans
        if p.plot_points.strip() or p.title.strip()
    ]

    char_cards = [character_model_to_card(c) for c in characters]
    outline_nodes = _build_outline_nodes(plans)
    char_summaries = _build_character_summaries(characters)
    relationship_map = _build_relationship_map(characters, outline_nodes)
    cross_ref_hints = _build_cross_reference_hints(characters, outline_nodes, relationship_map)

    return {
        "book_id": book.id,
        "title": book.title,
        "genre": book.genre,
        "premise": _truncate(book.premise or book.blurb, 400),
        "target_chapters": book.target_chapters,
        "writing_preferences": get_author_preferences(book),
        "writing_rules_summary": _truncate(book.rule_summary or book.writing_rules, 500),
        "worldview_summary": _truncate(_format_worldview(wv, book), 600),
        "plot_framework_summary": _truncate(_format_plot_framework(book.plot_framework), 500),
        "characters": char_cards,
        "character_summaries": char_summaries,
        "chapter_plans": plan_entries,
        "outline_nodes": outline_nodes,
        "relationship_map": relationship_map,
        "cross_reference_hints": cross_ref_hints,
        "chapters": chapter_entries,
        "key_entities": _extract_key_entities(characters, bodies),
        "focus_chapter_no": focus,
        "target_chapter_nos": sorted(targets) if targets else [],
    }


def format_book_index_block(
    index: dict[str, Any],
    *,
    target_chapter_nos: list[int] | None = None,
    compact: bool = False,
    slice_for_chapter: int | None = None,
) -> str:
    """将索引格式化为可注入 system 消息的文本块。"""
    targets = set(target_chapter_nos or index.get("target_chapter_nos") or [])
    lines = ["## 【书籍项目索引 · Book Index】", "结构化全书快照，改文/跨章任务请优先据此定位，勿仅依赖对话历史。"]

    lines += [
        "",
        "### 作品信息",
        f"- 书名：{index.get('title')}",
        f"- 类型：{index.get('genre') or '未设定'}",
        f"- 目标章数：{index.get('target_chapters')}",
    ]
    if index.get("premise"):
        lines.append(f"- 梗概：{index['premise']}")

    lines += ["", "### 写作偏好 / 规约摘要"]
    prefs = (index.get("writing_preferences") or "").strip()
    rules = (index.get("writing_rules_summary") or "").strip()
    lines.append(_truncate(prefs or rules or "（尚未配置）", 800 if not compact else 400))

    if not compact:
        if index.get("worldview_summary"):
            lines += ["", "### 世界观摘要", index["worldview_summary"]]
        if index.get("plot_framework_summary"):
            lines += ["", "### 长线框架摘要", index["plot_framework_summary"]]

    chars = index.get("characters") or []
    if chars:
        lines += ["", "### 角色卡"]
        for card in chars[:20]:
            data = card.get("data") or {}
            name = data.get("name") or card.get("title")
            role = data.get("role") or ""
            summary = _truncate(str(data.get("summary") or data.get("content") or ""), 150 if compact else 250)
            lines.append(f"- **{name}**（{role}）：{summary or '（无摘要）'}")

    entities = index.get("key_entities") or []
    if entities and not compact:
        ent_line = "、".join(f"{e['name']}×{e['mentions']}" for e in entities[:8])
        lines += ["", "### 正文高频实体", ent_line]

    plans = index.get("chapter_plans") or []
    if plans:
        lines += ["", "### 章节大纲 / 规划"]
        for p in plans:
            no = p.get("chapter_no")
            if targets and no not in targets and slice_for_chapter and no != slice_for_chapter:
                if compact:
                    continue
            title = p.get("title") or f"第{no}章"
            pts = p.get("plot_points") or ""
            cast = p.get("character_names") or ""
            line = f"- 第{no}章 {title}：{pts}"
            if cast and not compact:
                line += f" 【出场：{cast}】"
            if pts or cast:
                lines.append(line)

    outline_nodes = index.get("outline_nodes") or []
    if outline_nodes and not compact:
        lines += ["", "### 大纲结构节点（含出场角色）"]
        for node in outline_nodes[:30]:
            cast = node.get("cast") or []
            cast_str = f" · 出场：{', '.join(cast)}" if cast else ""
            lines.append(
                f"- 第{node.get('chapter_no')}章 {node.get('title')}：{node.get('plot_points') or '（无要点）'}{cast_str}"
            )

    hints = index.get("cross_reference_hints") or []
    if hints and not compact:
        lines += ["", "### 一致性提示（预检）"]
        for h in hints[:10]:
            lines.append(f"- ⚠ {h}")

    chapters = index.get("chapters") or []
    if chapters:
        lines += ["", "### 章节正文索引"]
        for ch in chapters:
            no = ch.get("chapter_no")
            if slice_for_chapter and no != slice_for_chapter:
                if targets and no not in targets:
                    continue
                if compact and not ch.get("is_focus") and no not in targets:
                    continue
            title = ch.get("title") or f"第{no}章"
            wc = ch.get("word_count", 0)
            if ch.get("is_empty"):
                lines.append(f"- 第{no}章《{title}》（空）")
                continue
            tags: list[str] = []
            if ch.get("is_focus"):
                tags.append("当前编辑")
            if ch.get("is_target"):
                tags.append("任务目标")
            tag_str = f" · {','.join(tags)}" if tags else ""
            lines.append(f"- 第{no}章《{title}》{wc}字{tag_str}")
            if ch.get("first_excerpt"):
                lines.append(f"  开篇：{ch['first_excerpt']}")
            if ch.get("last_excerpt") and ch.get("last_excerpt") != ch.get("first_excerpt"):
                lines.append(f"  结尾：{ch['last_excerpt']}")
            if not compact and ch.get("body_preview") and (ch.get("is_target") or ch.get("is_focus")):
                lines.append(f"  正文节选：\n{ch['body_preview']}")

    return "\n".join(lines)


def build_prefetch_context_blocks(
    index: dict[str, Any],
    resources: list[str],
) -> list[str]:
    """按检测到的资源类型预取上下文块，注入 system 消息。"""
    blocks: list[str] = []
    res = set(resources or [])

    if "outline" in res:
        nodes = index.get("outline_nodes") or []
        plans = index.get("chapter_plans") or []
        lines = ["## 【预取 · 章节大纲全文】"]
        for node in nodes or plans:
            if isinstance(node, dict):
                no = node.get("chapter_no")
                title = node.get("title") or f"第{no}章"
                pts = node.get("plot_points") or ""
                cast = node.get("cast") or node.get("character_names") or ""
                lines.append(f"### 第{no}章 {title}")
                if pts:
                    lines.append(pts)
                if cast:
                    lines.append(f"出场角色：{cast if isinstance(cast, str) else ', '.join(cast)}")
                if node.get("scene"):
                    lines.append(f"场景：{node['scene']}")
        if len(lines) > 1:
            blocks.append("\n".join(lines))

    if "characters" in res:
        summaries = index.get("character_summaries") or []
        cards = index.get("characters") or []
        lines = ["## 【预取 · 角色卡详情】"]
        items = summaries if summaries else []
        if not items and cards:
            for card in cards:
                data = card.get("data") or {}
                items.append(
                    {
                        "name": data.get("name") or card.get("title"),
                        "role": data.get("role"),
                        "summary": data.get("summary"),
                        "content_excerpt": data.get("content"),
                    }
                )
        for c in items:
            name = c.get("name") or "未命名"
            lines.append(f"### {name}（{c.get('role') or '未标注'}）")
            if c.get("summary"):
                lines.append(f"摘要：{c['summary']}")
            if c.get("voice_notes"):
                lines.append(f"口吻：{c['voice_notes']}")
            if c.get("content_excerpt"):
                lines.append(f"详情：{c['content_excerpt']}")
        if len(lines) > 1:
            blocks.append("\n".join(lines))

    if "worldview" in res:
        wv = (index.get("worldview_summary") or "").strip()
        pf = (index.get("plot_framework_summary") or "").strip()
        if wv or pf:
            parts = ["## 【预取 · 世界观与长线】"]
            if wv:
                parts.append(wv)
            if pf:
                parts.append(pf)
            blocks.append("\n".join(parts))

    if "writing_prefs" in res:
        prefs = (index.get("writing_preferences") or index.get("writing_rules_summary") or "").strip()
        if prefs:
            blocks.append(f"## 【预取 · 写作偏好】\n{prefs[:2000]}")

    hints = index.get("cross_reference_hints") or []
    if hints and res.intersection({"outline", "characters"}):
        blocks.append("## 【预取 · 一致性预检提示】\n" + "\n".join(f"- {h}" for h in hints))

    rel = index.get("relationship_map") or []
    if rel and res.intersection({"outline", "characters"}):
        missing = [e for e in rel if not e.get("in_character_db")]
        if missing:
            lines = ["## 【预取 · 大纲出场 ↔ 角色卡映射】"]
            for e in rel[:40]:
                flag = "✓" if e.get("in_character_db") else "✗ 缺卡"
                lines.append(f"- 第{e.get('chapter_no')}章 · {e.get('character_name')} · {flag}")
            blocks.append("\n".join(lines))

    return blocks


def index_chapter_scope_hint(index: dict[str, Any]) -> str:
    """供语义理解模块使用的简短章范围提示。"""
    written = [c["chapter_no"] for c in (index.get("chapters") or []) if not c.get("is_empty")]
    if not written:
        return "全书尚无正文章节。"
    parts = [f"已有正文：第{min(written)}–{max(written)}章（共{len(written)}章）"]
    targets = index.get("target_chapter_nos") or []
    if targets:
        parts.append(f"当前任务目标章：{', '.join(str(n) for n in targets)}")
    focus = index.get("focus_chapter_no")
    if focus:
        parts.append(f"编辑器聚焦：第{focus}章")
    plans = index.get("chapter_plans") or []
    if plans:
        plan_nos = [p["chapter_no"] for p in plans[:5]]
        parts.append(f"大纲已规划至第{max(p['chapter_no'] for p in plans)}章")
    return " · ".join(parts)
