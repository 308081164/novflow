from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from app.models import Book, Character, Chapter, ChapterPlan, User, Worldview
from app.services.api_key import resolve_api_key
from app.services.deepseek import DeepSeekError, chat_completion


async def _chat(
    user: User,
    messages: list[dict],
    *,
    temperature: float = 0.75,
    max_tokens: int = 4096,
    json_object: bool = False,
) -> str:
    key = resolve_api_key(user)
    if not key:
        raise DeepSeekError("请先在「设置」中配置 DeepSeek API Key")
    return await chat_completion(
        messages,
        api_key=key,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False,
        json_object=json_object,
    )  # type: ignore


def _parse_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return json.loads(text)


async def generate_worldview(db: Session, user: User, book: Book) -> Worldview:
    wv = db.query(Worldview).filter(Worldview.book_id == book.id).first()
    if not wv:
        wv = Worldview(book_id=book.id)
        db.add(wv)

    prompt = f"""你是网文策划。根据以下信息，生成结构化世界观（JSON），用于长篇连载。

书名：{book.title}
类型：{book.genre or '未指定'}
一句话梗概：{book.premise or book.blurb}

输出 JSON（不要 markdown 代码块）：
{{
  "era": "时代背景，50字内",
  "setting": "主舞台/地点",
  "tone": "基调与禁忌",
  "timeline_text": "宏观时间线，3-8条，每行一条",
  "taboos": "写作禁忌，如超能力、降智设定等",
  "content": "完整世界观 Markdown，500-800字，含时代、舞台、社会氛围、核心矛盾"
}}"""
    raw = await _chat(user, [{"role": "user", "content": prompt}], temperature=0.7)
    data = _parse_json(raw)
    wv.era = data.get("era", "")
    wv.setting = data.get("setting", "")
    wv.tone = data.get("tone", "")
    wv.timeline_text = data.get("timeline_text", "")
    wv.taboos = data.get("taboos", "")
    wv.content = data.get("content", "")
    db.commit()
    db.refresh(wv)
    return wv


async def generate_character(db: Session, user: User, book: Book, hint: str) -> Character:
    wv = db.query(Worldview).filter(Worldview.book_id == book.id).first()
    wv_text = wv.content[:600] if wv and wv.content else "（尚未设定世界观）"
    prompt = f"""你是网文角色设计师。为下列作品设计一个角色，输出 JSON。

书名：{book.title}
梗概：{book.premise or book.blurb}
世界观摘要：{wv_text}
用户要求：{hint or '主角或重要配角，与梗概匹配'}

{{
  "name": "姓名",
  "role": "protagonist/antagonist/support/ai 等",
  "summary": "一句话定位",
  "voice_notes": "说话风格要点",
  "content": "完整角色卡 Markdown，300-500字：基本信息、性格、动机、与其他角色关系、章段表现建议"
}}"""
    raw = await _chat(user, [{"role": "user", "content": prompt}], temperature=0.8)
    data = _parse_json(raw)
    ch = Character(
        book_id=book.id,
        name=data.get("name", "未命名"),
        role=data.get("role", "support"),
        summary=data.get("summary", ""),
        voice_notes=data.get("voice_notes", ""),
        content=data.get("content", ""),
    )
    db.add(ch)
    db.commit()
    db.refresh(ch)
    return ch


async def generate_outline(db: Session, user: User, book: Book, start: int = 1, count: int = 10) -> list[ChapterPlan]:
    chars = db.query(Character).filter(Character.book_id == book.id).all()
    char_text = "\n".join(f"- {c.name}（{c.role}）：{c.summary}" for c in chars) or "（暂无角色）"
    wv = db.query(Worldview).filter(Worldview.book_id == book.id).first()
    wv_text = wv.content[:500] if wv and wv.content else ""

    prompt = f"""你是网文大纲策划。为下列作品生成第{start}章起共{count}章的章节规划，输出 JSON 数组。

书名：{book.title}
类型：{book.genre}
梗概：{book.premise or book.blurb}
世界观：{wv_text}
角色：{char_text}
全书目标约 {book.target_chapters} 章，每章约 {book.words_per_chapter} 字

[{{"chapter_no": {start}, "title": "章节标题", "plot_points": "本章核心事件，2-3句", "comedy_core": "喜剧/梗核，可空", "scene": "主场景"}}]

只输出 JSON 数组，不要解释。"""
    raw = await _chat(user, [{"role": "user", "content": prompt}], temperature=0.75, max_tokens=8192)
    data = _parse_json(raw if raw.strip().startswith("[") else f"[{raw}]")
    if isinstance(data, dict):
        data = data.get("chapters", [data])
    updated = []
    for item in data:
        no = int(item.get("chapter_no", start))
        plan = (
            db.query(ChapterPlan)
            .filter(ChapterPlan.book_id == book.id, ChapterPlan.chapter_no == no)
            .first()
        )
        if not plan:
            plan = ChapterPlan(book_id=book.id, chapter_no=no)
            db.add(plan)
        plan.title = item.get("title", f"第{no}章")
        plan.plot_points = item.get("plot_points", item.get("synopsis", ""))
        plan.comedy_core = item.get("comedy_core", item.get("comedy_hook", ""))
        plan.scene = item.get("scene", "")
        updated.append(plan)
        ch = db.query(Chapter).filter(Chapter.book_id == book.id, Chapter.chapter_no == no).first()
        if not ch:
            ch = Chapter(book_id=book.id, chapter_no=no, title=plan.title, status="planned")
            db.add(ch)
        else:
            ch.title = plan.title
    db.commit()
    return updated


async def generate_writing_rules(db: Session, user: User, book: Book) -> str:
    prompt = f"""为下列网文生成本书写作偏好（800字内 Markdown）。
只包含作者可定制的内容：叙事视角/POV、主要角色口吻与声音、节奏与章节结构偏好、本书特有规则。
不要包含平台合规、通用语言禁忌、输出格式等（系统已自动注入，无需重复）。

书名：{book.title}
类型：{book.genre}
梗概：{book.premise or book.blurb}

直接输出偏好正文，不要前言。"""
    text = await _chat(user, [{"role": "user", "content": prompt}], temperature=0.5)
    book.writing_rules = text.strip()
    db.commit()
    return book.writing_rules
