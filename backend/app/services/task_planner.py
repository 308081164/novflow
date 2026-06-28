"""写作智能体任务规划：识别受影响资源、分解多步任务、生成执行计划。"""
from __future__ import annotations

import re
from typing import Any

from app.services.agent_constants import (
    ANALYSIS_ACTION_KEYWORDS,
    APPLY_ACTION_KEYWORDS,
    CHARACTER_RESOURCE_KEYWORDS,
    CHAPTER_RESOURCE_KEYWORDS,
    OUTLINE_RESOURCE_KEYWORDS,
    PREFS_RESOURCE_KEYWORDS,
    SYNC_ACTION_KEYWORDS,
    WORLDVIEW_RESOURCE_KEYWORDS,
)

CHAPTER_NO_RE = re.compile(r"第\s*(\d+)\s*章")

def detect_affected_resources(
    message: str,
    understanding: dict[str, Any] | None = None,
    *,
    book_index: dict[str, Any] | None = None,
) -> list[str]:
    """从用户消息与理解结果推断涉及的资源类型。"""
    msg = (message or "").strip()
    u = understanding or {}
    topic = str(u.get("topic") or "")
    resources: set[str] = set()

    if any(k in msg for k in OUTLINE_RESOURCE_KEYWORDS) or topic == "outline":
        resources.add("outline")
    if any(k in msg for k in CHARACTER_RESOURCE_KEYWORDS) or topic == "character":
        resources.add("characters")
    if any(k in msg for k in CHAPTER_RESOURCE_KEYWORDS) or topic == "chapter":
        resources.add("chapters")
    if any(k in msg for k in PREFS_RESOURCE_KEYWORDS) or topic == "writing_prefs":
        resources.add("writing_prefs")
    if any(k in msg for k in WORLDVIEW_RESOURCE_KEYWORDS) or topic in ("worldview", "plot"):
        resources.add("worldview")

    if u.get("target_chapter_nos") and u.get("intent") == "edit_text":
        resources.add("chapters")

    if "【选段" in msg:
        resources.add("chapters")

    # 无显式资源但意图为一致性 → 默认大纲 + 角色
    intent = u.get("intent", "")
    if intent in ("consistency_check", "cross_sync") and len(resources) < 2:
        resources.update({"outline", "characters"})

    # 索引侧：若大纲规划里有人物而用户提到人物名
    if book_index and not resources.intersection({"outline", "characters"}):
        chars = book_index.get("characters") or []
        for card in chars:
            data = (card.get("data") or {}) if isinstance(card, dict) else {}
            name = str(data.get("name") or card.get("title") or "")
            if name and len(name) >= 2 and name in msg:
                resources.add("characters")
                break

    return sorted(resources)


def _step(
    step_id: str,
    action: str,
    description: str,
    resources: list[str],
    *,
    depends_on: list[str] | None = None,
    auto_apply: bool = False,
) -> dict[str, Any]:
    return {
        "id": step_id,
        "action": action,
        "description": description,
        "resources": resources,
        "depends_on": depends_on or [],
        "auto_apply": auto_apply,
        "status": "pending",
    }


def plan_write_task(
    message: str,
    understanding: dict[str, Any],
    book_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """将用户请求分解为结构化任务计划。"""
    msg = (message or "").strip()
    intent = str(understanding.get("intent") or "general")
    resources = detect_affected_resources(msg, understanding, book_index=book_index)
    summary = str(understanding.get("summary") or msg[:200])
    steps: list[dict[str, Any]] = []
    execution_mode = "default"
    auto_apply = bool(understanding.get("auto_apply"))
    execute_prior = bool(understanding.get("execute_prior_plan"))
    has_analysis = any(k in msg for k in ANALYSIS_ACTION_KEYWORDS)
    has_sync = any(k in msg for k in SYNC_ACTION_KEYWORDS)
    has_apply = any(k in msg for k in APPLY_ACTION_KEYWORDS)
    multi_resource = len(resources) >= 2

    if execute_prior:
        execution_mode = "apply_plan"
        intent = "cross_sync"
        steps = [
            _step("load", "load_context", "加载上一轮分析方案与草案设定", resources),
            _step("apply_cards", "apply_fixes", "写入统一后的角色卡/大纲设定", resources, depends_on=["load"], auto_apply=True),
            _step("edit_chapters", "edit_chapters", "按方案修正涉及章节正文并写入", ["chapters"] + [r for r in resources if r != "chapters"], depends_on=["apply_cards"]),
        ]

    elif intent == "consistency_check" or (
        multi_resource and has_analysis and intent not in ("edit_text", "brainstorm")
    ):
        execution_mode = "analyze_only"
        intent = "consistency_check"
        steps = [
            _step("load", "load_context", "加载大纲、角色卡及相关设定", resources),
            _step("analyze", "analyze_conflicts", "对照各资源，列出冲突与不一致项", resources, depends_on=["load"]),
            _step(
                "propose",
                "propose_fixes",
                "提出统一方案（角色卡/大纲草案，供采纳）",
                resources,
                depends_on=["analyze"],
            ),
        ]
        if has_sync or has_apply:
            steps.append(
                _step(
                    "apply",
                    "apply_fixes",
                    "应用已明确的修正到设定（需用户确认或自动采纳）",
                    resources,
                    depends_on=["propose"],
                    auto_apply=auto_apply,
                )
            )
            execution_mode = "cross_sync"
            intent = "cross_sync"

    elif intent == "cross_sync" or (multi_resource and has_sync and intent != "edit_text"):
        execution_mode = "cross_sync"
        steps = [
            _step("load", "load_context", "加载相关设定与大纲", resources),
            _step("analyze", "analyze_conflicts", "分析跨资源不一致", resources, depends_on=["load"]),
            _step("propose", "propose_fixes", "生成统一后的设定草案", resources, depends_on=["analyze"]),
            _step(
                "apply",
                "apply_fixes",
                "写入统一后的设定（卡片采纳）",
                resources,
                depends_on=["propose"],
                auto_apply=auto_apply or has_apply,
            ),
        ]

    elif intent == "edit_text":
        execution_mode = "chapter_edit"
        target_nos = understanding.get("target_chapter_nos") or []
        ch_desc = f"修改第 {', '.join(str(n) for n in target_nos)} 章正文" if target_nos else "修改当前章正文"
        steps = [
            _step("load", "load_context", "加载章节正文与连续性上下文", ["chapters"] + [r for r in resources if r != "chapters"]),
            _step("edit", "edit_chapters", ch_desc, ["chapters"], depends_on=["load"]),
        ]

    elif intent in ("plan_outline", "draft_card", "show_card"):
        execution_mode = "setting_edit"
        res = resources or ["outline" if intent == "plan_outline" else "characters"]
        steps = [_step("load", "load_context", "加载相关设定", res), _step("edit", "edit_settings", summary, res, depends_on=["load"])]

    else:
        execution_mode = "discuss"
        if resources:
            steps = [_step("load", "load_context", "加载相关背景", resources)]

    return {
        "intent": intent,
        "execution_mode": execution_mode,
        "summary": summary,
        "resources": resources,
        "steps": steps,
        "multi_resource": multi_resource,
        "requires_analysis": execution_mode in ("analyze_only", "cross_sync", "apply_plan"),
        "allow_edits": (
            execution_mode in ("chapter_edit", "apply_plan")
            or bool(understanding.get("allow_edits") and execution_mode == "chapter_edit")
        ),
        "allow_cards": execution_mode in ("cross_sync", "setting_edit") or bool(understanding.get("allow_cards")),
    }


def format_task_plan_for_user(plan: dict[str, Any]) -> str:
    """供 assistant reply 前缀展示的任务计划（Markdown）。"""
    steps = plan.get("steps") or []
    if len(steps) <= 1 and not plan.get("multi_resource"):
        return ""
    lines = ["**任务计划**"]
    for i, s in enumerate(steps, 1):
        desc = s.get("description") or s.get("action") or ""
        res = s.get("resources") or []
        tag = f"（{', '.join(res)}）" if res else ""
        lines.append(f"{i}. {desc}{tag}")
    mode = plan.get("execution_mode", "")
    if mode == "analyze_only":
        lines.append("\n> 本轮为**分析/对照**任务，不会直接改写章节正文。")
    elif mode == "cross_sync":
        lines.append("\n> 多资源同步：先分析冲突，再输出可采纳的设定草案。")
    elif mode == "apply_plan":
        lines.append("\n> **执行方案**：写入设定卡片并修正涉及章节正文。")
    return "\n".join(lines)


def format_task_plan_system_block(plan: dict[str, Any]) -> str:
    """注入 system 消息的任务计划块。"""
    lines = [
        "## 【任务计划 · Task Plan】",
        f"- 执行模式：{plan.get('execution_mode', 'default')}",
        f"- 涉及资源：{', '.join(plan.get('resources') or []) or '（未指定）'}",
        f"- 需求摘要：{plan.get('summary') or '（无）'}",
    ]
    for s in plan.get("steps") or []:
        deps = s.get("depends_on") or []
        dep_str = f" ← 依赖 {', '.join(deps)}" if deps else ""
        lines.append(f"- [{s.get('id')}] {s.get('description')} · action={s.get('action')}{dep_str}")
    if plan.get("requires_analysis"):
        lines += [
            "",
            "**分析任务约束**：",
            "- 必须先完成冲突/对照分析，再提出修正方案。",
            "- 禁止跳过分析直接输出 edits 改写章节正文。",
            "- 修正方案用 cards（character / outline）草案呈现；用户确认后再 apply_card_ids。",
        ]
    return "\n".join(lines)


def should_route_chapter_edit(intent: str, plan: dict[str, Any] | None) -> bool:
    """是否应走逐章正文改写路径。"""
    if intent != "edit_text":
        return False
    if not plan:
        return True
    return plan.get("execution_mode") == "chapter_edit"


def is_multi_resource_analysis_message(message: str) -> bool:
    """规则：多资源 + 分析/一致性语义，且非明确正文改写。"""
    msg = (message or "").strip()
    if "【选段" in msg:
        return False
    if CHAPTER_NO_RE.search(msg) and any(k in msg for k in ("润色", "改写", "修改正文", "改正文", "扩写")):
        return False
    if any(k in msg for k in CHAPTER_RESOURCE_KEYWORDS) and any(
        k in msg for k in ("润色", "改写", "修改", "删", "补全", "优化")
    ):
        return False

    has_outline = any(k in msg for k in OUTLINE_RESOURCE_KEYWORDS)
    has_char = any(k in msg for k in CHARACTER_RESOURCE_KEYWORDS)
    has_analysis = any(k in msg for k in ANALYSIS_ACTION_KEYWORDS)
    has_sync_only = any(k in msg for k in SYNC_ACTION_KEYWORDS) and not has_analysis

    if has_outline and has_char and (has_analysis or has_sync_only):
        return True
    if has_analysis and has_outline and has_char:
        return True
    return False
