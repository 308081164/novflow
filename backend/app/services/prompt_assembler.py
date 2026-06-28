from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Book, Chapter, ChapterPlan, Character, Worldview
from app.services.chapter_content import get_content
from app.services.context_limits import (
    AUTHOR_PREFS_CHARS,
    CHARACTER_DETAIL_CHARS,
    CORPUS_CHARS,
    NEARBY_PLAN_PLOT_CHARS,
    OUTLINE_FRAMEWORK_CHARS,
    PREV_CHAPTER_ASSEMBLE_CHARS,
    WORLD_SETTING_CHARS,
    WRITING_RULES_CHARS,
)
from app.services.system_writing_rules import (
    DEFAULT_AUTHOR_HINT,
    combine_writing_rules,
    get_author_preferences,
)


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n…（已截断）"


def _format_worldview(wv: Worldview | None, book: Book) -> str:
    parts: list[str] = []
    if wv:
        for label, field in (
            ("时代", "era"),
            ("主舞台", "setting"),
            ("基调", "tone"),
            ("时间线", "timeline_text"),
            ("禁忌", "taboos"),
        ):
            val = getattr(wv, field, "") or ""
            if val.strip():
                parts.append(f"{label}：{val.strip()}")
        if wv.content.strip():
            parts.append(wv.content.strip())
    if not parts:
        return book.premise or book.blurb or "（暂无世界观，请参考作品简介）"
    return "\n".join(parts)


def _format_plot_framework(pf: dict | None) -> str:
    if not pf or not isinstance(pf, dict):
        return "（暂无长线框架）"
    parts: list[str] = []
    if pf.get("imported_full") and pf.get("source") == "import":
        parts.append(str(pf["imported_full"])[:8000])
    elif pf.get("summary"):
        parts.append(str(pf["summary"]))
    if pf.get("style"):
        parts.append(f"风格：{pf['style']}")
    if pf.get("total_chapters"):
        parts.append(f"目标章数：{pf['total_chapters']}")
    phases = pf.get("phases") or []
    if phases:
        parts.append("阶段划分：")
        for p in phases:
            if not isinstance(p, dict):
                continue
            parts.append(
                f"- {p.get('name', '阶段')}（{p.get('chapter_range', '')}）：{p.get('description', '')}"
            )
    units = pf.get("units") or []
    if units:
        parts.append("单元结构：")
        for u in units:
            if not isinstance(u, dict):
                continue
            parts.append(f"- {u.get('name', '单元')}：{u.get('description', '')}")
    return "\n".join(parts) if parts else "（暂无长线框架）"


def _format_plan_synopsis(plan: ChapterPlan | None) -> str:
    if not plan:
        return "（本章暂无详细规划，请依据作品简介与相邻章节推断）"
    parts: list[str] = []
    if plan.plot_points.strip():
        parts.append(plan.plot_points.strip())
    if plan.scene.strip():
        parts.append(f"场景：{plan.scene.strip()}")
    meta = plan.meta_json or {}
    if meta.get("events"):
        events = meta["events"]
        if isinstance(events, list):
            parts.append("关键事件：" + "、".join(str(e) for e in events))
    cast = meta.get("cast") or plan.character_names
    if cast:
        if isinstance(cast, list):
            parts.append("出场角色：" + "、".join(str(c) for c in cast))
        else:
            parts.append(f"出场角色：{cast}")
    if meta.get("entrances"):
        parts.append("新登场：" + "、".join(str(x) for x in meta["entrances"]))
    return "\n".join(parts) if parts else plan.title or "（待补充骨架）"


def assemble_context(db: Session, book: Book, chapter_no: int) -> dict:
    wv = db.query(Worldview).filter(Worldview.book_id == book.id).first()
    plans = (
        db.query(ChapterPlan)
        .filter(ChapterPlan.book_id == book.id)
        .order_by(ChapterPlan.chapter_no)
        .all()
    )
    plan = next((p for p in plans if p.chapter_no == chapter_no), None)
    chapter = (
        db.query(Chapter)
        .filter(Chapter.book_id == book.id, Chapter.chapter_no == chapter_no)
        .first()
    )

    prev_chapters = (
        db.query(Chapter)
        .filter(Chapter.book_id == book.id, Chapter.chapter_no < chapter_no)
        .order_by(Chapter.chapter_no.desc())
        .limit(2)
        .all()
    )
    prev_chapters = list(reversed(prev_chapters))

    characters = db.query(Character).filter(Character.book_id == book.id).order_by(Character.id).all()
    char_blocks: list[str] = []
    for c in characters:
        block = f"### {c.name}（{c.role}）"
        if c.summary.strip():
            block += f"\n{c.summary.strip()}"
        if c.voice_notes.strip():
            block += f"\n口吻：{c.voice_notes.strip()}"
        if c.content.strip():
            block += f"\n{_truncate(c.content.strip(), CHARACTER_DETAIL_CHARS)}"
        char_blocks.append(block)

    prev_summary: list[str] = []
    for ch in prev_chapters:
        body = get_content(ch)
        if not body.strip():
            continue
        if body.startswith("#"):
            body = "\n".join(body.splitlines()[1:])
        prev_summary.append(f"第{ch.chapter_no}章 {ch.title}\n{_truncate(body.strip(), PREV_CHAPTER_ASSEMBLE_CHARS)}")

    nearby_plans: list[str] = []
    for p in plans:
        if abs(p.chapter_no - chapter_no) <= 2:
            line = f"第{p.chapter_no}章 {p.title}：{_truncate(p.plot_points, NEARBY_PLAN_PLOT_CHARS)}"
            if p.comedy_core.strip():
                line += f"（喜剧核：{p.comedy_core}）"
            nearby_plans.append(line)

    author_preferences = get_author_preferences(book) or DEFAULT_AUTHOR_HINT
    writing_rules = combine_writing_rules(book)

    corpus = (book.corpus or "").strip()

    return {
        "book_title": book.title,
        "blurb": book.blurb or book.premise or "",
        "genre": book.genre or "",
        "author_preferences": _truncate(author_preferences, AUTHOR_PREFS_CHARS),
        "writing_rules": _truncate(writing_rules, WRITING_RULES_CHARS),
        "world_setting": _truncate(_format_worldview(wv, book), WORLD_SETTING_CHARS),
        "outline": _truncate(_format_plot_framework(book.plot_framework), OUTLINE_FRAMEWORK_CHARS),
        "corpus": _truncate(corpus, CORPUS_CHARS),
        "characters": "\n\n".join(char_blocks) if char_blocks else "（暂无角色，请依据大纲与简介创作）",
        "chapter_no": chapter_no,
        "chapter_title": (plan.title if plan and plan.title else None) or (chapter.title if chapter else f"第{chapter_no}章"),
        "chapter_synopsis": _format_plan_synopsis(plan),
        "chapter_scene": plan.scene if plan else "",
        "comedy_hook": plan.comedy_core if plan else "",
        "target_words": book.words_per_chapter or 2000,
        "prev_chapters": "\n\n---\n\n".join(prev_summary) if prev_summary else "（无前文）",
        "nearby_plans": "\n".join(nearby_plans),
    }


def build_generate_messages(
    ctx: dict,
    instruction: str = "",
    *,
    job_type: str = "draft",
    current_content: str = "",
) -> list[dict]:
    chapter_no = int(ctx["chapter_no"])
    chapter_title = ctx["chapter_title"]
    target_words = int(ctx.get("target_words") or 2000)

    system = f"""你是专业网文写手，正在为《{ctx["book_title"]}》撰写正文。

作品类型：{ctx.get("genre") or "未指定"}
作品简介：{_truncate(ctx.get("blurb") or "", 600)}

必须严格遵守写作规约：
{ctx["writing_rules"]}

世界观与背景：
{ctx["world_setting"]}

长线剧情框架：
{ctx["outline"]}

角色设定：
{ctx["characters"]}"""

    if (ctx.get("corpus") or "").strip():
        system += f"""

角色语料库（口头禅、梗、对话范例，写作时可参考）：
{ctx["corpus"]}"""

    system += """

输出要求：
- Markdown 格式，首行必须是 # 第{chapter_no:03d}章 {chapter_title}
- 正文约 {target_words} 汉字（可浮动 ±200）
- 只输出章节正文，不要解释、前言或 meta 说明"""

    if job_type == "expand":
        user = f"""请在不改变情节走向的前提下，将以下章节扩写到约 {target_words} 字。
保留已有优点，增补细节、对话与氛围，不要重复堆砌。

当前正文：
{current_content}

输出完整章节（含 # 标题行）。"""
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    if job_type == "fix":
        user = f"""请根据写作规约修订以下章节，保持情节不变，修正违规表达。
输出完整修订后章节（含 # 标题行）。

当前正文：
{current_content}"""
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    user_parts = [
        f"## 本章规划\n第{chapter_no}章 {chapter_title}\n{ctx['chapter_synopsis']}",
    ]
    if ctx.get("chapter_scene"):
        user_parts.append(f"场景：{ctx['chapter_scene']}")
    if ctx.get("comedy_hook"):
        user_parts.append(f"喜剧核：{ctx['comedy_hook']}")
    if ctx.get("nearby_plans"):
        user_parts.append(f"## 相邻章节规划\n{ctx['nearby_plans']}")
    if ctx.get("prev_chapters") and ctx["prev_chapters"] != "（无前文）":
        user_parts.append(f"## 前文摘要\n{ctx['prev_chapters']}")
    if instruction.strip():
        user_parts.append(f"## 额外指令\n{instruction.strip()}")
    user_parts.append("请撰写本章完整正文。")

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]


def build_expand_messages(ctx: dict, content: str, target_words: int, focus: str) -> list[dict]:
    return build_generate_messages(
        ctx,
        focus,
        job_type="expand",
        current_content=content,
    )


def build_fix_messages(ctx: dict, content: str, issues_text: str) -> list[dict]:
    system_extra = f"\n\n待修复问题：\n{issues_text}" if issues_text else ""
    msgs = build_generate_messages(ctx, job_type="fix", current_content=content)
    msgs[0]["content"] += system_extra
    return msgs
