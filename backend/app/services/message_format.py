"""助手消息格式化（供历史压缩与 LLM 上下文，打破 write_agent ↔ write_agent_context 循环依赖）。"""
from __future__ import annotations

from typing import Any, Protocol


class MessageWithCards(Protocol):
    content: str | None
    cards_json: list | None
    actions_json: list | None


def assistant_content_for_history(m: MessageWithCards) -> str:
    """将助手消息（含卡片/actions 元数据）转为历史摘要文本。"""
    text = (m.content or "").strip()
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
    actions = m.actions_json or []
    for a in actions:
        if isinstance(a, dict) and a.get("label"):
            parts.append(f"（助手提供了跳转：{a['label']}）")
    if parts:
        return "\n".join(parts)
    return "（助手上一轮未返回文本）"
