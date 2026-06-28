"""系统内置写作规约：平台合规与语言规范，用户不可见、不可编辑。"""

from __future__ import annotations

from app.models import Book

SYSTEM_WRITING_RULES = """
【输出格式】
- 文首一行：# 第NNN章 标题（三位章号）
- 禁止章首说明书/meta 块（时间地点交代、「本章」「今日」等旁白式开场）
- 禁止 --- 分隔线
- 只输出章节正文，不要解释、前言或自检说明

【语言规范】
- 禁止破折号「——」作补充说明
- 单句中文逗号不超过 3 个
- 避免排比句、选项清单式罗列
- 减少「仿佛」「宛如」「不禁」「目光微凝」「心中一凛」等 AI 味句式
- 比喻克制：每段「像/仿佛/如同」类比喻最多 1 个

【平台合规（通用）】
- 口语化、自然的中文网文文风
- 不涉及色情、暴力、政治敏感等违规内容
- 避免过度猎奇、血腥细节描写
""".strip()

_PLATFORM_EXTRA: dict[str, str] = {
    "fanqie": """
【番茄小说】
- 开篇 3 章内要有清晰钩子与冲突
- 段落宜短，对话与动作交替
- 节奏紧凑，避免大段抒情与说明
""".strip(),
    "qidian": """
【起点中文网】
- 注重世界观铺垫与人物弧光
- 章节末尾留悬念或情绪落点
""".strip(),
}

DEFAULT_AUTHOR_HINT = "保持与作品设定、人物口吻一致；只输出正文。"

# 模板书（chase-comedy）作者偏好：角色/POV 等本书特有规则，不含平台通用规范
CHASE_COMEDY_AUTHOR_PREFS = """
【叙事】主线陆沉舟第一人称「我」；Restricted POV，未见面者不得出现姓名。
【苏令仪】仅隔章章末短切第三人称，本章若无 pov_switch 则不要切。
【顾念】一本正经误用梗；禁止梗后解释（不要「指……」「……原文」）。
【陆沉舟】本章至少一处他拍板的决定；嘴贱内化，对外克制。
【体量】目标约2000汉字。
""".strip()


def get_system_rules(platform: str = "fanqie") -> str:
    key = (platform or "fanqie").strip().lower()
    extra = _PLATFORM_EXTRA.get(key, "")
    if extra:
        return f"{SYSTEM_WRITING_RULES}\n\n{extra}"
    return SYSTEM_WRITING_RULES


def get_author_preferences(book: Book) -> str:
    return (book.writing_rules or "").strip()


def combine_writing_rules(book: Book) -> str:
    system = get_system_rules(getattr(book, "platform", None) or "fanqie")
    author = get_author_preferences(book)
    if author:
        return f"{system}\n\n【本书写作偏好】\n{author}"
    return system


def get_combined_for_lint(book: Book) -> str:
    return combine_writing_rules(book)
