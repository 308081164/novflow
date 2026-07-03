"""将用户上传的设定文档用 AI 梳理为 NovFlow 结构化格式。"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.models import User
from app.services.ai_assist import _chat
from app.services.api_key import has_api_key
from app.services.card_handlers import OUTLINE_MAX_BATCH
from app.services.deepseek import DeepSeekError
from app.services.outline_planner import normalize_outline_data

log = logging.getLogger(__name__)

# 单次 adapt 送入模型的正文字符上限（不含 prompt 模板）
INPUT_LIMITS: dict[str, int] = {
    "character": 5000,
    "worldview": 6500,
    "outline": 6500,
    "prefs": 5000,
    "conventions": 5000,
}
# 分块摘要：每块原文上限、合并后摘要上限
CHUNK_SIZE = 9000
CHUNK_OVERLAP = 400
COMPRESS_INPUT_MAX = 16000
COMPRESS_OUTPUT_MAX = 3200
PREMISE_CTX_MAX = 280
MAX_OUTLINE_CHAPTERS_LOCAL = OUTLINE_MAX_BATCH
MAX_CHARACTER_FILES = 40

_KIND_KWARGS: dict[str, tuple[str, ...]] = {
    "character": ("name_hint", "book_title", "genre"),
    "worldview": ("book_title", "genre", "premise"),
    "outline": ("book_title", "genre", "premise", "target_chapters", "character_names"),
    "prefs": ("book_title", "genre"),
    "conventions": ("book_title", "genre"),
}

_KIND_LABELS: dict[str, str] = {
    "character": "角色设定",
    "worldview": "世界观",
    "outline": "故事大纲",
    "prefs": "写作偏好",
    "conventions": "写作规约",
}

# 仅匹配「第N章」式标题，避免把「3 硬核节点」误判为章节
_STRICT_CHAPTER_HEAD = re.compile(
    r"^(?:#+\s*)?第\s*([0-9０-９一二三四五六七八九十百千两]+)\s*[章节回集]",
    re.MULTILINE | re.IGNORECASE,
)

_META_TITLE_KEYWORDS = (
    "叙事总原则",
    "角色表",
    "角色设定",
    "分卷",
    "字数",
    "硬核节点",
    "写作规约",
    "时间线",
    "关键时间",
)

_CN_NUM = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "百": 100,
    "千": 1000,
}


def _kind_label(kind: str, label: str = "") -> str:
    return label.strip() or _KIND_LABELS.get(kind, kind)


def _short_premise(premise: str, limit: int = PREMISE_CTX_MAX) -> str:
    t = re.sub(r"\s+", " ", (premise or "").strip())
    if len(t) <= limit:
        return t
    return t[: limit - 3] + "…"


def _clip(text: str, limit: int) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[: limit - 24] + "\n\n…（已截断）"


def _smart_excerpt(text: str, limit: int) -> str:
    """长文截取：保留开头结构 + 结尾，避免只截前半导致丢信息。"""
    t = text.strip()
    if len(t) <= limit:
        return t
    head = int(limit * 0.65)
    tail = limit - head - 40
    return f"{t[:head]}\n\n…（中间省略 {len(t) - head - tail} 字）…\n\n{t[-tail:]}"


def _split_chunks(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    t = text.strip()
    if len(t) <= size:
        return [t]
    chunks: list[str] = []
    start = 0
    while start < len(t):
        end = min(len(t), start + size)
        chunks.append(t[start:end])
        if end >= len(t):
            break
        start = max(0, end - overlap)
    return chunks


def _parse_chapter_no(raw: str) -> int | None:
    s = (raw or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    s = s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if s.isdigit():
        return int(s)
    total = 0
    current = 0
    for ch in s:
        if ch in _CN_NUM:
            val = _CN_NUM[ch]
            if val >= 10:
                current = max(1, current or 1) * val
            else:
                current = current * 10 + val if current else val
        else:
            return None
    total = current or total
    return total if total > 0 else None


def extract_outline_chapters_local(text: str, *, max_chapters: int = MAX_OUTLINE_CHAPTERS_LOCAL) -> list[dict[str, Any]]:
    """严格本地兜底：仅识别「第N章」标题，且正文不过长。"""
    t = text.strip()
    if not t:
        return []
    matches = list(_STRICT_CHAPTER_HEAD.finditer(t))
    if len(matches) < 2:
        return []
    chapters: list[dict[str, Any]] = []
    for i, m in enumerate(matches[:max_chapters]):
        no_raw = m.group(1) or ""
        chapter_no = _parse_chapter_no(no_raw) or (i + 1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(t)
        body = t[start:end].strip()
        title_line = body.splitlines()[0].strip() if body else f"第{chapter_no}章"
        title = re.sub(r"^[#*\s\-]+", "", title_line)[:60] or f"第{chapter_no}章"
        plot = re.sub(r"\s+", " ", body)[:280] if body else ""
        if _looks_like_meta_chapter(title, plot):
            continue
        chapters.append(
            {
                "chapter_no": chapter_no,
                "title": title,
                "plot_points": plot,
                "scene": "",
                "comedy_core": "",
                "cast": [],
                "events": [],
                "entrances": [],
                "exits": [],
            }
        )
    return chapters


def _looks_like_meta_chapter(title: str, plot_points: str) -> bool:
    blob = f"{title} {plot_points}"
    if any(k in blob for k in _META_TITLE_KEYWORDS):
        return True
    if plot_points.count("|") >= 2:
        return True
    if len(plot_points) > 500:
        return True
    return False


def _format_plot_context(plot: dict[str, Any]) -> str:
    if not plot:
        return "（尚未提取）"
    lines = [f"摘要：{plot.get('summary') or '—'}"]
    for ph in plot.get("phases") or []:
        if not isinstance(ph, dict):
            continue
        lines.append(
            f"- {ph.get('name') or '阶段'}（{ph.get('chapter_range') or '?'}）："
            f"{_clip(str(ph.get('description') or ''), 120)}"
        )
    return "\n".join(lines)


def _sanitize_outline_chapters(chapters: list[dict[str, Any]], *, max_chapters: int = OUTLINE_MAX_BATCH) -> list[dict[str, Any]]:
    """清洗 AI 输出的章节，剔除元信息块与过长正文。"""
    cleaned: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw in chapters:
        if not isinstance(raw, dict):
            continue
        try:
            chapter_no = int(raw.get("chapter_no") or 0)
        except (TypeError, ValueError):
            continue
        if chapter_no < 1 or chapter_no in seen:
            continue
        title = re.sub(r"\s+", " ", str(raw.get("title") or f"第{chapter_no}章")).strip()[:60]
        plot = re.sub(r"\s+", " ", str(raw.get("plot_points") or raw.get("synopsis") or "")).strip()
        plot = _clip(plot, 280)
        if not plot or _looks_like_meta_chapter(title, plot):
            continue
        cast = raw.get("cast") or raw.get("characters") or []
        if not isinstance(cast, list):
            cast = [str(cast)] if cast else []
        cast = [str(c).strip() for c in cast if str(c).strip()][:8]
        events = raw.get("events") or []
        if not isinstance(events, list):
            events = [str(events)] if events else []
        events = [str(e).strip() for e in events if str(e).strip()][:4]
        cleaned.append(
            {
                "chapter_no": chapter_no,
                "title": title,
                "plot_points": plot,
                "scene": _clip(str(raw.get("scene") or ""), 80),
                "comedy_core": _clip(str(raw.get("comedy_core") or raw.get("comedy_hook") or ""), 80),
                "cast": cast,
                "events": events,
                "entrances": raw.get("entrances") or [],
                "exits": raw.get("exits") or [],
            }
        )
        seen.add(chapter_no)
        if len(cleaned) >= max_chapters:
            break
    cleaned.sort(key=lambda x: int(x["chapter_no"]))
    return cleaned


async def _adapt_outline_chapters_ai(
    text: str,
    *,
    user: User,
    plot: dict[str, Any],
    target_chapters: int = 300,
    book_title: str = "",
    genre: str = "",
    premise: str = "",
    source_text: str | None = None,
    character_names: list[str] | None = None,
    max_chapters: int = OUTLINE_MAX_BATCH,
) -> list[dict[str, Any]]:
    """AI 深度理解混乱大纲，输出符合 NovFlow 的章节卡片。"""
    body = source_text if source_text is not None else text
    cast_hint = "、".join(character_names[:20]) if character_names else "（从原文推断，须用中文姓名）"
    plot_ctx = _format_plot_context(plot)

    prompt = f"""你是 NovFlow 网文大纲结构化专家。用户导入了一份**可能非常混乱**的大纲（Markdown 表格、分卷统计、角色表、叙事规则与分章情节混在一起）。

请**深度理解**后，提取或推导符合系统要求的**分章情节规划**。

书名：{book_title or '未指定'}
类型：{genre or '未指定'}
计划总章数：{target_chapters}
已知角色：{cast_hint}

## 已提取的宏观框架
{plot_ctx}

## 原始大纲（可能混乱）
{_clip(body, INPUT_LIMITS["outline"])}

输出 JSON（不要 markdown 代码块）：
{{
  "chapters": [
    {{
      "chapter_no": 1,
      "title": "8-16字章名",
      "plot_points": "80-180字，本章核心事件，具体到可直接开写",
      "scene": "主场景",
      "comedy_core": "可空",
      "cast": ["出场角色名"],
      "events": ["关键事件1"],
      "entrances": [],
      "exits": []
    }}
  ]
}}

## 必须遵守
1. **禁止**把「叙事总原则」「角色表/设定」「分卷字数表」「硬核节点说明」「时间线表格」当作章节写入 chapters
2. 若原文有清晰「第N章/第N集」式分章，按顺序整理为规范卡片（最多 {max_chapters} 章）
3. 若原文只有阶段/幕而无分章，根据开篇阶段**合理拆分**第 1–{min(max_chapters, 12)} 章，每章一个可写场景
4. plot_points 必须是**叙述性情节**，禁止粘贴表格、禁止含 | 符号、禁止超过 180 字
5. title 简短，不要带 ###、不要带整段说明
6. cast 优先使用已知角色列表中的姓名
7. chapter_no 从 1 起连续编号，最多 {max_chapters} 章

只输出 JSON。"""

    try:
        data = await _adapt_json(user, prompt, temperature=0.35, max_tokens=6144)
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning("outline chapters AI pass 1 failed: %s", exc)
        data = {}

    batch = normalize_outline_data(data).get("chapters") or []
    chapters = _sanitize_outline_chapters(batch if isinstance(batch, list) else [], max_chapters=max_chapters)
    if chapters:
        return chapters

    # 二次尝试：只规划开篇
    retry = f"""你是网文大纲编辑。混乱大纲无法直接分章，请仅根据下列信息规划**开篇 {min(8, max_chapters)} 章**的可写大纲。

书名：{book_title or '未指定'}
宏观摘要：{_clip(str(plot.get('summary') or premise or text), 600)}

输出 JSON：{{ "chapters": [{{ "chapter_no", "title", "plot_points", "scene", "cast": [], "events": [], "entrances": [], "exits": [] }}] }}
每章 plot_points 80-150字，禁止表格与元规则。只输出 JSON。"""
    data2 = await _adapt_json(user, retry, temperature=0.3, max_tokens=4096)
    batch2 = normalize_outline_data(data2).get("chapters") or []
    return _sanitize_outline_chapters(batch2 if isinstance(batch2, list) else [], max_chapters=max_chapters)


def parse_character_local(text: str, name_hint: str = "") -> dict[str, Any]:
    """AI 不可用时的结构化兜底（仍保留原文）。"""
    t = text.strip()
    name = name_hint or "未命名角色"
    for line in t.splitlines()[:12]:
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(?:#+\s*)?(?:角色名|姓名|名称)[:：]\s*(.+)$", line)
        if m:
            name = m.group(1).strip()[:100]
            break
        if not line.startswith("#") and len(line) <= 24 and not line.endswith("。"):
            name = line[:100]
            break
    head = t[:400]
    role = "support"
    if re.search(r"主角|主人公|男主|女主", head):
        role = "protagonist"
    elif re.search(r"反派|对手|恶人", head):
        role = "antagonist"
    summary = ""
    for line in t.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and len(line) > 8:
            summary = line[:120]
            break
    return {
        "name": name,
        "role": role,
        "summary": summary,
        "voice_notes": "",
        "content": t,
    }


def _pick_kwargs(kind: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    allowed = _KIND_KWARGS.get(kind, ())
    picked = {k: v for k, v in kwargs.items() if k in allowed}
    if "premise" in picked:
        picked["premise"] = _short_premise(str(picked["premise"] or ""))
    return picked


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    raise ValueError("AI 返回非 JSON 对象")


async def _adapt_json(user: User, prompt: str, *, temperature: float = 0.4, max_tokens: int = 4096) -> dict[str, Any]:
    raw = await _chat(
        user,
        [{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
        json_object=True,
    )
    return _parse_json_object(str(raw))


async def _compress_chunk(
    user: User,
    chunk: str,
    kind: str,
    *,
    book_title: str = "",
    genre: str = "",
    part: str = "",
) -> str:
    label = _KIND_LABELS.get(kind, "设定")
    part_hint = f"（第 {part} 部分）" if part else ""
    prompt = f"""你是网文设定编辑。下面是一份较长的「{label}」文档片段{part_hint}，请提炼要点摘要，供后续结构化梳理。

书名：{book_title or '未指定'}
类型：{genre or '未指定'}

## 原文片段
{_clip(chunk, COMPRESS_INPUT_MAX)}

要求：
- 直接输出 Markdown 摘要正文，不要 JSON，不要前言
- 保留全部关键事实、人名、时间线、规则与禁忌，删重复
- {COMPRESS_OUTPUT_MAX} 字以内"""
    raw = await _chat(user, [{"role": "user", "content": prompt}], temperature=0.25, max_tokens=2048)
    return _clip(str(raw).strip(), COMPRESS_OUTPUT_MAX)


async def _merge_compress_parts(user: User, parts: list[str], kind: str, *, book_title: str = "", genre: str = "") -> str:
    if len(parts) == 1:
        return parts[0]
    label = _KIND_LABELS.get(kind, "设定")
    joined = "\n\n---\n\n".join(f"### 片段 {i + 1}\n{p}" for i, p in enumerate(parts))
    prompt = f"""下面是一部长篇「{label}」文档的多段摘要，请合并为一份连贯摘要（Markdown），供后续结构化导入。

书名：{book_title or '未指定'}

{joined}

要求：去重、理顺结构，保留全部关键信息，{COMPRESS_OUTPUT_MAX} 字以内。直接输出正文。"""
    raw = await _chat(user, [{"role": "user", "content": prompt}], temperature=0.25, max_tokens=2048)
    return _clip(str(raw).strip(), COMPRESS_OUTPUT_MAX)


async def _prepare_source_text(
    user: User,
    text: str,
    kind: str,
    *,
    book_title: str = "",
    genre: str = "",
) -> tuple[str, str | None]:
    """超长文档：分块摘要后再 adapt，避免单次 prompt 撑爆上下文。"""
    t = text.strip()
    limit = INPUT_LIMITS.get(kind, 6000)
    if len(t) <= limit:
        return t, None
    log.info("book import %s: compressing %d chars -> adapt budget %d", kind, len(t), limit)
    chunks = _split_chunks(t, CHUNK_SIZE, CHUNK_OVERLAP)
    parts: list[str] = []
    for i, ch in enumerate(chunks):
        parts.append(
            await _compress_chunk(
                user,
                ch,
                kind,
                book_title=book_title,
                genre=genre,
                part=f"{i + 1}/{len(chunks)}" if len(chunks) > 1 else "",
            )
        )
    digest = await _merge_compress_parts(user, parts, kind, book_title=book_title, genre=genre)
    note = f"{_KIND_LABELS.get(kind, kind)}原文较长（{len(t)} 字），已分 {len(chunks)} 段摘要后再梳理"
    return _clip(digest, limit), note


async def adapt_character(
    text: str,
    *,
    user: User,
    name_hint: str = "",
    book_title: str = "",
    genre: str = "",
    source_text: str | None = None,
) -> dict[str, Any]:
    """梳理角色设定为 Character 字段结构。"""
    hint = name_hint or "（从正文推断）"
    body = source_text if source_text is not None else text
    prompt = f"""你是网文角色设定编辑。用户上传了一份角色设定文档，请梳理为 NovFlow 系统字段。

书名：{book_title or '未指定'}
类型：{genre or '未指定'}
文件名角色名提示：{hint}

## 原始文档
{_clip(body, INPUT_LIMITS["character"])}

输出 JSON（不要 markdown 代码块），字段说明：
- name: 角色姓名（优先文件名提示，其次正文）
- role: protagonist / antagonist / support 之一
- summary: 一句话定位，50字内
- voice_notes: 说话风格、口癖要点，一两句话
- content: 完整角色卡 Markdown（300-800字），含外貌、性格、动机、关系；保留原文关键信息

各字符串内换行用 \\n。只输出 JSON。"""
    data = await _adapt_json(user, prompt, temperature=0.35, max_tokens=2048)
    if name_hint and not str(data.get("name") or "").strip():
        data["name"] = name_hint
    # content 以 AI 整理版为主，但若过短则补回原文要点
    content = str(data.get("content") or "").strip()
    if len(content) < 120 and text.strip():
        data["content"] = text.strip()[:4000]
    return data


async def adapt_worldview(
    text: str,
    *,
    user: User,
    book_title: str = "",
    genre: str = "",
    premise: str = "",
    source_text: str | None = None,
) -> dict[str, Any]:
    body = source_text if source_text is not None else text
    prompt = f"""你是网文世界观编辑。用户上传了世界观文档，请重组为 NovFlow 结构化字段。

书名：{book_title or '未指定'}
类型：{genre or '未指定'}
梗概：{_short_premise(premise) or '未指定'}

## 原始文档
{_clip(body, INPUT_LIMITS["worldview"])}

输出 JSON（不要 markdown 代码块）：
- era: 时代背景，50字内
- setting: 主舞台/地点
- tone: 基调与氛围
- timeline_text: 宏观时间线，3-8条，换行分隔
- taboos: 写作禁忌、不可违背的规则
- content: 完整世界观 Markdown（500-1200字），条理清晰

各字符串内换行用 \\n。只输出 JSON。"""
    data = await _adapt_json(user, prompt, temperature=0.35, max_tokens=4096)
    if not str(data.get("content") or "").strip() and text.strip():
        data["content"] = text.strip()[:8000]
    return data


async def _adapt_outline_plot(
    text: str,
    *,
    user: User,
    target_chapters: int = 300,
    book_title: str = "",
    genre: str = "",
    premise: str = "",
    source_text: str | None = None,
) -> dict[str, Any]:
    body = source_text if source_text is not None else text
    prompt = f"""你是网文大纲编辑。请从**可能混乱**的大纲文档中提取宏观 plot 框架（不要输出分章 outline.chapters）。

书名：{book_title or '未指定'}
类型：{genre or '未指定'}
梗概：{_short_premise(premise) or '未指定'}
计划总章数：{target_chapters}

## 原始文档
{_clip(body, INPUT_LIMITS["outline"])}

输出 JSON（不要 markdown 代码块）：
{{
  "plot": {{
    "summary": "全书主线摘要，200-500字，连贯叙述",
    "total_chapters": {target_chapters},
    "style": "叙事风格/类型标签",
    "phases": [{{ "name": "阶段名", "chapter_range": "1-50", "description": "该阶段核心情节与目标" }}],
    "units": []
  }},
  "outline": {{ "chapters": [] }},
  "imported_full": "原文中非分章部分的要点（角色表/规则/时间线等），600字内"
}}

规则：
- phases 按原文幕/卷/阶段划分；表格、角色表、叙事规则写入 imported_full 而非 phases
- 勿编造情节；字符串内换行用 \\n
- 只输出 JSON"""
    return await _adapt_json(user, prompt, temperature=0.3, max_tokens=4096)


async def adapt_outline(
    text: str,
    *,
    user: User,
    target_chapters: int = 300,
    book_title: str = "",
    genre: str = "",
    premise: str = "",
    source_text: str | None = None,
    character_names: list[str] | None = None,
) -> tuple[dict[str, Any], str | None]:
    """梳理故事大纲：先提取 plot 框架，再 AI 结构化分章（不用粗糙正则切分）。"""
    body = source_text if source_text is not None else text
    data = await _adapt_outline_plot(
        text,
        user=user,
        target_chapters=target_chapters,
        book_title=book_title,
        genre=genre,
        premise=premise,
        source_text=body,
    )
    plot = data.get("plot") if isinstance(data.get("plot"), dict) else {}

    chapters = await _adapt_outline_chapters_ai(
        text,
        user=user,
        plot=plot,
        target_chapters=target_chapters,
        book_title=book_title,
        genre=genre,
        premise=premise,
        source_text=body,
        character_names=character_names,
    )

    outline_note: str | None = None
    if chapters:
        outline = data.get("outline") if isinstance(data.get("outline"), dict) else {}
        outline["chapters"] = chapters
        data["outline"] = outline
        outline_note = f"大纲已 AI 结构化首批 {len(chapters)} 章"
        if target_chapters > len(chapters):
            outline_note += f"（全书 {target_chapters} 章，其余可在设定助手继续规划）"
    else:
        outline_note = "未能从混乱大纲提取分章，已保留宏观框架与原文备份"

    if not str(data.get("imported_full") or "").strip() and text.strip():
        data["imported_full"] = _clip(text, 2000)
    return data, outline_note


async def adapt_writing_section(
    text: str,
    *,
    user: User,
    section: str,
    book_title: str = "",
    genre: str = "",
    source_text: str | None = None,
) -> str:
    label = "写作偏好" if section == "prefs" else "写作规约"
    kind = section if section in INPUT_LIMITS else "prefs"
    body = source_text if source_text is not None else text
    prompt = f"""你是网文创作规范编辑。用户上传了「{label}」文档，请整理为条理清晰的 Markdown 正文。

书名：{book_title or '未指定'}
类型：{genre or '未指定'}

## 原始文档
{_clip(body, INPUT_LIMITS.get(kind, 5000))}

要求：
- 直接输出 Markdown 正文，不要 JSON，不要前言
- 用小标题（##）组织：视角/文风、节奏、角色口吻、禁忌等（按原文有则写）
- 保留全部有效约束，800字内为宜"""
    raw = await _chat(user, [{"role": "user", "content": prompt}], temperature=0.3, max_tokens=2048)
    out = str(raw).strip()
    return out or text.strip()[:8000]


def can_adapt_with_ai(user: User | None) -> bool:
    return has_api_key(user)


async def safe_adapt(
    kind: str,
    text: str,
    user: User,
    *,
    label: str = "",
    **kwargs: Any,
) -> tuple[Any | None, str | None, str | None]:
    """尝试 AI 适配。返回 (result, warning, info_note)。"""
    if not text.strip():
        return None, None, None
    if not can_adapt_with_ai(user):
        return None, "未配置 DeepSeek API Key，已按原文导入", None

    tag = _kind_label(kind, label)
    picked = _pick_kwargs(kind, kwargs)
    prep_note: str | None = None
    try:
        source, prep_note = await _prepare_source_text(
            user,
            text,
            kind,
            book_title=str(picked.get("book_title") or ""),
            genre=str(picked.get("genre") or ""),
        )
        if kind == "character":
            result = await adapt_character(text, user=user, source_text=source, **picked)
            return result, None, prep_note
        if kind == "worldview":
            result = await adapt_worldview(text, user=user, source_text=source, **picked)
            return result, None, prep_note
        if kind == "outline":
            result, outline_note = await adapt_outline(text, user=user, source_text=source, **picked)
            return result, None, "；".join(x for x in (prep_note, outline_note) if x)
        if kind in ("prefs", "conventions"):
            content = await adapt_writing_section(text, user=user, section=kind, source_text=source, **picked)
            return content, None, prep_note
    except DeepSeekError as exc:
        log.warning("book import AI adapt DeepSeek error (%s/%s): %s", kind, tag, exc)
        fallback = _local_fallback(kind, text, picked)
        if fallback is not None:
            return fallback, f"{tag}：API 异常，已按原文结构化导入", prep_note
        return None, f"{tag}：AI 梳理失败（{exc}），已按原文导入", prep_note
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning("book import AI adapt parse error (%s/%s): %s", kind, tag, exc)
        fallback = _local_fallback(kind, text, picked)
        if fallback is not None:
            return fallback, f"{tag}：解析失败，已按原文结构化导入", prep_note
        return None, f"{tag}：AI 梳理结果解析失败，已按原文导入", prep_note
    return None, None, prep_note


def _local_fallback(kind: str, text: str, picked: dict[str, Any]) -> Any | None:
    if kind == "character":
        return parse_character_local(text, str(picked.get("name_hint") or ""))
    if kind == "outline":
        chapters = _sanitize_outline_chapters(extract_outline_chapters_local(text))
        if chapters:
            return {
                "plot": {
                    "summary": _clip(text, 500),
                    "total_chapters": picked.get("target_chapters") or 300,
                    "style": "",
                    "phases": [],
                    "units": [],
                },
                "outline": {"chapters": chapters},
                "imported_full": _clip(text, 2000),
            }
        return None
    return None
