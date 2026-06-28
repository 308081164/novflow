"""图像生成编排：提示词构建、即梦调用、MinIO 持久化。"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Book, Chapter, ChapterIllustration, Character, User
from app.services.agent_constants import IMAGE_KEYWORDS, IMAGE_REFINE_KEYWORDS
from app.services.api_key import has_jimeng_key, resolve_api_key
from app.services.chapter_content import get_content
from app.services.image_providers.base import generate_and_store, media_url as _media_url_from_provider
from app.services.jimeng_image import JimengError
from app.services.storage import storage

ImageKind = Literal["cover", "character", "illustration"]

REFINE_KEYWORDS = IMAGE_REFINE_KEYWORDS


def media_url(object_key: str) -> str:
    return _media_url_from_provider(object_key)


def is_image_generation_message(msg: str) -> bool:
    t = (msg or "").strip().lower()
    if not t:
        return False
    return any(k.lower() in t for k in IMAGE_KEYWORDS)


def is_image_refine_message(msg: str) -> bool:
    t = (msg or "").strip()
    return any(k in t for k in REFINE_KEYWORDS)


def detect_image_kind(msg: str, chapter_no: int | None = None) -> ImageKind:
    t = (msg or "").strip()
    if any(k in t for k in ("封面", "书封", "cover")):
        return "cover"
    if any(k in t for k in ("角色", "人设", "立绘", "人物图", "character")):
        return "character"
    if chapter_no and any(k in t for k in ("插图", "配图", "场景", "本章", "章节")):
        return "illustration"
    if any(k in t for k in ("插图", "配图", "场景图", "章节插图")):
        return "illustration"
    if chapter_no:
        return "illustration"
    return "cover"


def extract_character_name(msg: str, characters: list[Character]) -> Character | None:
    for ch in characters:
        if ch.name and ch.name in msg:
            return ch
    return characters[0] if len(characters) == 1 else None


def build_cover_prompt(book: Book) -> str:
    parts = [
        f"小说封面设计，书名《{book.title}》",
        f"类型：{book.genre or '网文'}" if book.genre else "",
        f"简介：{book.premise or book.blurb}" if (book.premise or book.blurb) else "",
        "高质量书籍封面，竖版构图，无文字水印，电影感光影，适合网络小说平台",
    ]
    return "，".join(p for p in parts if p)


CHARACTER_PORTRAIT_RATIO = "9:16"


def build_character_prompt(character: Character, extra: str = "") -> str:
    size = settings.jimeng_character_size
    parts = [
        f"角色立绘，{character.name}",
        character.summary or "",
        character.content or "",
        character.voice_notes or "",
        extra.strip(),
        f"严格竖版{CHARACTER_PORTRAIT_RATIO}比例，输出尺寸{size}，全身立绘，人物居中，简洁纯色背景，无文字无水印",
        "strict 9:16 vertical full-body portrait, consistent aspect ratio, plain background, "
        "clear facial features, high-quality digital illustration, novel character reference",
    ]
    return "，".join(p for p in parts if p)


def extract_quoted_passage(message: str) -> str | None:
    """从写作智能体「选段 · 第N章」消息中提取引用正文。"""
    if "【选段" not in (message or ""):
        return None
    idx = message.find("【选段")
    rest = message[idx:]
    rest = re.sub(r"^【选段[^】]*】\s*", "", rest, count=1)
    parts = re.split(r"\n\n(?=[^>\s])", rest, maxsplit=1)
    block = parts[0]
    lines: list[str] = []
    for line in block.splitlines():
        cleaned = re.sub(r"^>\s?", "", line.strip())
        if cleaned:
            lines.append(cleaned)
    text = "\n".join(lines).strip()
    return text or None


def _rule_fallback_scene_brief(passage: str) -> str:
    snippet = re.split(r"[。！？\n]", (passage or "").strip())[0][:80]
    if snippet:
        return (
            f"小说插图场景：{snippet}。"
            "中景构图，人物与环境互动，柔和光线，写实插画，健康全年龄，无文字无水印"
        )
    return "网文章节插图，日常叙事场景，中景构图，柔和光线，写实插画，健康全年龄，无文字无水印"


def is_sensitive_image_error(exc: JimengError) -> bool:
    text = str(exc).lower()
    return "sensitive information" in text or "敏感" in text or "content" in text and "policy" in text


async def build_image_safe_scene_brief(
    user: User,
    book: Book,
    chapter: Chapter,
    passage: str,
) -> str:
    """将正文/选段转为适合即梦文生图的安全场景描述。"""
    passage = (passage or "").strip()
    if not passage:
        return _rule_fallback_scene_brief("")
    if not resolve_api_key(user):
        return _rule_fallback_scene_brief(passage)
    from app.services.ai_assist import _chat

    try:
        brief = await _chat(
            user,
            [
                {
                    "role": "system",
                    "content": "你是网文插图策划，负责把小说片段改写为可安全用于文生图的场景描述。",
                },
                {
                    "role": "user",
                    "content": (
                        f"将下面片段改写为 120~220 字的插图场景描述。\n"
                        f"要求：只写环境、人物位置、动作、光线、氛围与构图；健康全年龄；"
                        f"不要裸露、性暗示、色情用词或敏感部位描写；适合横版小说配图。\n"
                        f"书名《{book.title}》第{chapter.chapter_no}章。\n"
                        f"片段：\n{passage[:1500]}\n"
                        f"只输出场景描述正文。"
                    ),
                },
            ],
            temperature=0.35,
            max_tokens=400,
        )
        cleaned = (brief or "").strip()
        return cleaned[:500] if cleaned else _rule_fallback_scene_brief(passage)
    except Exception:
        return _rule_fallback_scene_brief(passage)


def _characters_for_illustration(characters: list[Character], text: str, limit: int = 3) -> list[Character]:
    if not characters:
        return []
    matched = [c for c in characters if c.name and c.name in (text or "")]
    if matched:
        return matched[:limit]
    return characters[: min(limit, 2)]


def build_illustration_prompt(
    book: Book,
    chapter: Chapter,
    scene_description: str,
    characters: list[Character],
    extra: str = "",
) -> str:
    char_desc = "；".join(
        f"{c.name}：{(c.summary or c.content[:120]).strip()}" for c in characters[:3] if c.name
    )
    parts = [
        f"小说章节插图，《{book.title}》第{chapter.chapter_no}章",
        f"场景描述：{scene_description[:600]}",
        f"出场角色：{char_desc}" if char_desc else "",
        extra.strip() if extra and not extra.startswith("【选段") else "",
        "横版场景插画，叙事感强，内容健康全年龄，无文字，适合网文章节配图",
    ]
    prompt = "，".join(p for p in parts if p)
    return prompt[:800]


def _category_for_kind(kind: ImageKind) -> str:
    return {"cover": "covers", "character": "characters", "illustration": "illustrations"}[kind]


def _new_object_key(book_id: int, kind: ImageKind, ext: str = "png") -> str:
    cat = _category_for_kind(kind)
    return f"images/{book_id}/{cat}/{uuid.uuid4().hex[:16]}.{ext}"


async def _call_and_store(
    user: User,
    book_id: int,
    kind: ImageKind,
    prompt: str,
    reference_keys: list[str] | None = None,
) -> tuple[str, bytes]:
    object_key, image_bytes = await generate_and_store(
        user, book_id, kind, prompt, reference_keys=reference_keys
    )
    return object_key, image_bytes


def _image_record(
    object_key: str,
    prompt: str,
    kind: ImageKind,
    *,
    id: int | None = None,
    parent_id: int | None = None,
    character_id: int | None = None,
    is_active: bool = False,
) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "id": id,
        "url": media_url(object_key),
        "object_key": object_key,
        "kind": kind,
        "prompt": prompt,
        "parent_id": parent_id,
        "created_at": datetime.utcnow().isoformat(),
        "is_active": is_active,
    }
    if character_id:
        rec["character_id"] = character_id
    return rec


def active_portrait_object_key(character: Character) -> str | None:
    arc = character.arc_json or {}
    key = arc.get("active_portrait_object_key")
    return str(key) if key else None


def set_active_portrait_object_key(character: Character, object_key: str) -> None:
    arc = dict(character.arc_json or {})
    arc["active_portrait_object_key"] = object_key
    character.arc_json = arc


def get_character_portrait_for_ref(character: Character) -> dict[str, Any] | None:
    images = character.images_json or []
    if not images:
        return None
    active = active_portrait_object_key(character)
    if active:
        for img in images:
            if isinstance(img, dict) and img.get("object_key") == active:
                return img
    last = images[-1]
    return last if isinstance(last, dict) else None


def enrich_character_images(character: Character) -> list[dict[str, Any]]:
    active = active_portrait_object_key(character)
    result: list[dict[str, Any]] = []
    for i, raw in enumerate(character.images_json or []):
        if not isinstance(raw, dict):
            continue
        rec = dict(raw)
        rec["id"] = rec.get("id") or (i + 1)
        rec["is_active"] = bool(active and rec.get("object_key") == active)
        result.append(rec)
    return result


async def generate_book_cover(
    db: Session,
    user: User,
    book: Book,
    prompt: str | None = None,
) -> dict[str, Any]:
    if not has_jimeng_key(user):
        raise JimengError("请先在设置中配置即梦 API Key")
    final_prompt = (prompt or "").strip() or build_cover_prompt(book)
    object_key, _ = await _call_and_store(user, book.id, "cover", final_prompt)
    book.cover_image_key = object_key
    db.commit()
    db.refresh(book)
    return _image_record(object_key, final_prompt, "cover")


async def generate_character_image(
    db: Session,
    user: User,
    book: Book,
    character: Character,
    prompt: str | None = None,
    parent_object_key: str | None = None,
) -> dict[str, Any]:
    if not has_jimeng_key(user):
        raise JimengError("请先在设置中配置即梦 API Key")
    extra = (prompt or "").strip()
    final_prompt = build_character_prompt(character, extra)
    refs = [parent_object_key] if parent_object_key else None
    object_key, _ = await _call_and_store(user, book.id, "character", final_prompt, reference_keys=refs)
    images = list(character.images_json or [])
    rec = _image_record(object_key, final_prompt, "character", character_id=character.id)
    images.append(rec)
    character.images_json = images
    arc = dict(character.arc_json or {})
    if not arc.get("active_portrait_object_key"):
        arc["active_portrait_object_key"] = object_key
        character.arc_json = arc
    db.commit()
    db.refresh(character)
    rec["id"] = len(images)
    rec["is_active"] = active_portrait_object_key(character) == object_key
    return rec


async def generate_chapter_illustration(
    db: Session,
    user: User,
    book: Book,
    chapter: Chapter,
    passage: str | None = None,
    prompt: str | None = None,
    parent_id: int | None = None,
    parent_object_key: str | None = None,
    character_ids: list[int] | None = None,
) -> dict[str, Any]:
    if not has_jimeng_key(user):
        raise JimengError("请先在设置中配置即梦 API Key")

    all_characters = db.query(Character).filter(Character.book_id == book.id).all()
    if character_ids:
        scoped = [c for c in all_characters if c.id in character_ids]
    else:
        scoped = all_characters

    body = passage or get_content(chapter)
    raw_passage = (body or "").strip()[:2000]
    extra = (prompt or "").strip()

    scene_brief = await build_image_safe_scene_brief(user, book, chapter, raw_passage)
    scene_chars = _characters_for_illustration(scoped, f"{raw_passage}\n{scene_brief}")

    parent_key: str | None = None
    if parent_object_key:
        parent_key = parent_object_key.strip() or None
    elif parent_id:
        parent = db.query(ChapterIllustration).filter(
            ChapterIllustration.id == parent_id,
            ChapterIllustration.chapter_id == chapter.id,
        ).first()
        if parent:
            parent_key = parent.object_key

    ref_keys: list[str] = []
    if parent_key:
        ref_keys.append(parent_key)

    final_prompt = build_illustration_prompt(book, chapter, scene_brief, scene_chars, extra)

    async def _generate(prompt_text: str, refs: list[str] | None) -> tuple[str, bytes]:
        return await _call_and_store(user, book.id, "illustration", prompt_text, reference_keys=refs)

    try:
        object_key, _ = await _generate(final_prompt, ref_keys or None)
    except JimengError as exc:
        if not is_sensitive_image_error(exc):
            raise
        fallback_brief = _rule_fallback_scene_brief(raw_passage)
        final_prompt = build_illustration_prompt(book, chapter, fallback_brief, scene_chars[:1], "")
        object_key, _ = await _generate(final_prompt, None)

    ill = ChapterIllustration(
        chapter_id=chapter.id,
        object_key=object_key,
        prompt=final_prompt,
        parent_id=parent_id,
    )
    db.add(ill)
    db.commit()
    db.refresh(ill)
    return _image_record(object_key, final_prompt, "illustration", id=ill.id, parent_id=parent_id)


def find_last_image_from_history(history: list[dict], meta_list: list[dict] | None = None) -> dict | None:
    for source in reversed(meta_list or []):
        imgs = source.get("images") if isinstance(source, dict) else None
        if isinstance(imgs, list) and imgs:
            return imgs[-1] if isinstance(imgs[-1], dict) else None
    for h in reversed(history):
        imgs = h.get("images")
        if isinstance(imgs, list) and imgs:
            last = imgs[-1]
            if isinstance(last, dict):
                return last
    return None


async def maybe_handle_chat_image(
    db: Session,
    user: User,
    book: Book,
    message: str,
    *,
    chapter_no: int | None = None,
    history: list[dict] | None = None,
    history_meta: list[dict] | None = None,
) -> dict[str, Any] | None:
    """若用户消息为图像生成意图，执行生成并返回回复结构。"""
    msg = (message or "").strip()
    if not is_image_generation_message(msg) and not is_image_refine_message(msg):
        return None
    if not has_jimeng_key(user):
        return {
            "reply": "生成图片需要配置即梦 API Key。请前往「账号设置」填写火山方舟 API Key 后重试。",
            "images": [],
            "handled": True,
        }

    kind = detect_image_kind(msg, chapter_no)
    refine = is_image_refine_message(msg)
    last_img = find_last_image_from_history(history or [], history_meta) if refine else None

    characters = db.query(Character).filter(Character.book_id == book.id).all()

    try:
        if kind == "cover" or (refine and last_img and last_img.get("kind") == "cover"):
            parent_key = str(last_img.get("object_key") or "") if last_img else None
            prompt = msg if refine else None
            if parent_key:
                final_prompt = f"{build_cover_prompt(book)}。调整要求：{msg}"
                object_key, _ = await _call_and_store(
                    user, book.id, "cover", final_prompt, reference_keys=[parent_key]
                )
                book.cover_image_key = object_key
                db.commit()
                img = _image_record(object_key, final_prompt, "cover")
            else:
                img = await generate_book_cover(db, user, book, prompt)
            return {
                "reply": f"已为《{book.title}》生成封面图，可在书籍详情页查看。如需调整，可继续说「把封面改成…」。",
                "images": [img],
                "handled": True,
            }

        if kind == "character" or (refine and last_img and last_img.get("kind") == "character"):
            ch = extract_character_name(msg, characters)
            if not ch and characters:
                ch = characters[0]
            if not ch:
                return {
                    "reply": "请先创建角色卡，或说明要为哪个角色生成形象图（如「给男主生成角色图」）。",
                    "images": [],
                    "handled": True,
                }
            parent_key = str(last_img.get("object_key") or "") if last_img else None
            img = await generate_character_image(db, user, book, ch, msg if refine else None, parent_key)
            return {
                "reply": f"已为角色「{ch.name}」生成形象图。可在角色管理页查看，或继续说「调整这张图…」。",
                "images": [img],
                "handled": True,
            }

        # illustration
        chapter = db.query(Chapter).filter(Chapter.book_id == book.id, Chapter.chapter_no == (chapter_no or 1)).first()
        if not chapter:
            return {"reply": "未找到对应章节，无法生成插图。", "images": [], "handled": True}

        parent_id = None
        if last_img and last_img.get("kind") == "illustration" and last_img.get("id"):
            parent_id = int(last_img["id"])

        scene_chars = [c for c in characters if c.name and c.name in msg]
        quoted_passage = extract_quoted_passage(msg)
        img = await generate_chapter_illustration(
            db, user, book, chapter,
            passage=quoted_passage,
            prompt=msg if refine else None,
            parent_id=parent_id,
            character_ids=[c.id for c in scene_chars] if scene_chars else None,
        )
        note = "（已根据选段自动转为含蓄的场景描述以满足生图审核）" if quoted_passage else ""
        return {
            "reply": f"已生成第{chapter.chapter_no}章插图，可在章节编辑器末尾查看。{note}如需修改请说「调整这张图…」。",
            "images": [img],
            "handled": True,
        }
    except JimengError as exc:
        return {"reply": f"图片生成失败：{exc}", "images": [], "handled": True}


def list_chapter_illustrations(db: Session, chapter: Chapter) -> list[dict[str, Any]]:
    rows = (
        db.query(ChapterIllustration)
        .filter(ChapterIllustration.chapter_id == chapter.id)
        .order_by(ChapterIllustration.created_at)
        .all()
    )
    return [
        _image_record(r.object_key, r.prompt, "illustration", id=r.id, parent_id=r.parent_id)
        for r in rows
    ]
