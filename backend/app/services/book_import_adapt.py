"""将用户上传的设定文档用 AI 梳理为 NovFlow 结构化格式。"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.models import User
from app.services.ai_assist import _chat, _parse_json
from app.services.api_key import has_api_key
from app.services.deepseek import DeepSeekError

log = logging.getLogger(__name__)

MAX_INPUT_CHARS = 12000


def _clip(text: str, limit: int = MAX_INPUT_CHARS) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[: limit - 20] + "\n\n…（原文过长，已截断供 AI 梳理）"


async def _adapt_json(user: User, prompt: str, *, temperature: float = 0.4, max_tokens: int = 4096) -> dict[str, Any]:
    raw = await _chat(
        user,
        [{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
        json_object=True,
    )
    data = _parse_json(str(raw))
    if not isinstance(data, dict):
        raise ValueError("AI 返回非 JSON 对象")
    return data


async def adapt_character(
    text: str,
    *,
    user: User,
    name_hint: str = "",
    book_title: str = "",
    genre: str = "",
) -> dict[str, Any]:
    """梳理角色设定为 Character 字段结构。"""
    hint = name_hint or "（从正文推断）"
    prompt = f"""你是网文角色设定编辑。用户上传了一份角色设定文档，请梳理为 NovFlow 系统字段。

书名：{book_title or '未指定'}
类型：{genre or '未指定'}
文件名角色名提示：{hint}

## 原始文档
{_clip(text)}

输出 JSON（不要 markdown 代码块），字段说明：
- name: 角色姓名（优先文件名提示，其次正文）
- role: protagonist / antagonist / support 之一
- summary: 一句话定位，50字内
- voice_notes: 说话风格、口癖要点，一两句话
- content: 完整角色卡 Markdown（300-800字），含外貌、性格、动机、关系、章段表现；保留原文关键信息，条理清晰

只输出 JSON。"""
    data = await _adapt_json(user, prompt, temperature=0.35)
    if name_hint and not str(data.get("name") or "").strip():
        data["name"] = name_hint
    return data


async def adapt_worldview(
    text: str,
    *,
    user: User,
    book_title: str = "",
    genre: str = "",
    premise: str = "",
) -> dict[str, Any]:
    """梳理世界观为 Worldview 模型字段。"""
    prompt = f"""你是网文世界观编辑。用户上传了世界观文档，请重组为 NovFlow 结构化字段。

书名：{book_title or '未指定'}
类型：{genre or '未指定'}
梗概：{premise or '未指定'}

## 原始文档
{_clip(text)}

输出 JSON（不要 markdown 代码块）：
- era: 时代背景，50字内
- setting: 主舞台/地点
- tone: 基调与氛围
- timeline_text: 宏观时间线，3-8条，换行分隔
- taboos: 写作禁忌、不可违背的规则
- content: 完整世界观 Markdown（500-1200字），条理清晰，保留原文要点

只输出 JSON。"""
    return await _adapt_json(user, prompt, temperature=0.35, max_tokens=6144)


async def adapt_outline(
    text: str,
    *,
    user: User,
    target_chapters: int = 300,
    book_title: str = "",
    genre: str = "",
    premise: str = "",
) -> dict[str, Any]:
    """梳理故事大纲：宏观 plot 框架，及可识别的分章 outline。"""
    prompt = f"""你是网文大纲编辑。用户上传了故事大纲/剧情规划文档，请梳理为 NovFlow 可用结构。

书名：{book_title or '未指定'}
类型：{genre or '未指定'}
梗概：{premise or '未指定'}
计划总章数：{target_chapters}

## 原始文档
{_clip(text)}

输出 JSON（不要 markdown 代码块）：
{{
  "plot": {{
    "summary": "全书主线摘要，200-500字",
    "total_chapters": {target_chapters},
    "style": "叙事风格/类型标签，可空",
    "phases": [{{ "name": "阶段名", "chapter_range": "1-50", "description": "该阶段要点" }}],
    "units": [{{ "name": "单元名", "episodes_per_arc": 10, "description": "可选" }}]
  }},
  "outline": {{
    "chapters": [
      {{
        "chapter_no": 1,
        "title": "章标题",
        "plot_points": "本章核心事件",
        "scene": "主场景",
        "comedy_core": "可空",
        "cast": ["角色名"],
        "events": ["大事件"],
        "entrances": [],
        "exits": []
      }}
    ]
  }},
  "imported_full": "若原文难以拆分，在此保留整理后的完整 Markdown 大纲"
}}

规则：
- plot.summary 必填；phases 按原文阶段划分，无则留空数组
- outline.chapters 仅当原文有明确分章/集数时填写，最多 15 章；无分章则 chapters 为空数组
- imported_full 保留梳理后的全文备份，便于后续参考
- 不要编造原文没有的重大情节

只输出 JSON。"""
    return await _adapt_json(user, prompt, temperature=0.35, max_tokens=8192)


async def adapt_writing_section(
    text: str,
    *,
    user: User,
    section: str,
    book_title: str = "",
    genre: str = "",
) -> str:
    """梳理写作偏好或规约为 Markdown 正文。"""
    label = "写作偏好" if section == "prefs" else "写作规约"
    prompt = f"""你是网文创作规范编辑。用户上传了「{label}」文档，请整理为条理清晰的 Markdown 正文。

书名：{book_title or '未指定'}
类型：{genre or '未指定'}

## 原始文档
{_clip(text)}

要求：
- 直接输出 Markdown 正文，不要 JSON，不要前言
- 用小标题（##）组织：视角/文风、节奏、角色口吻、禁忌、平台或本书特有规则等（按原文有则写）
- 保留原文全部有效约束，删去重复废话
- 800字内为宜，可略超"""
    raw = await _chat(user, [{"role": "user", "content": prompt}], temperature=0.3, max_tokens=2048)
    return str(raw).strip()


def can_adapt_with_ai(user: User | None) -> bool:
    return has_api_key(user)


async def safe_adapt(
    kind: str,
    text: str,
    user: User,
    **kwargs: Any,
) -> tuple[Any | None, str | None]:
    """尝试 AI 适配，失败时返回 (None, warning)。"""
    if not text.strip():
        return None, None
    if not can_adapt_with_ai(user):
        return None, "未配置 DeepSeek API Key，已按原文导入"
    try:
        if kind == "character":
            return await adapt_character(text, user=user, **kwargs), None
        if kind == "worldview":
            return await adapt_worldview(text, user=user, **kwargs), None
        if kind == "outline":
            return await adapt_outline(text, user=user, **kwargs), None
        if kind in ("prefs", "conventions"):
            content = await adapt_writing_section(text, user=user, section=kind, **kwargs)
            return content, None
    except DeepSeekError as exc:
        log.warning("book import AI adapt DeepSeek error (%s): %s", kind, exc)
        return None, f"AI 梳理失败（{exc}），已按原文导入"
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        log.warning("book import AI adapt parse error (%s): %s", kind, exc)
        return None, "AI 梳理结果解析失败，已按原文导入"
    return None, None
