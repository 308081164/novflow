"""write_agent chat_turn 意图/模式 → 执行器路由表。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from sqlalchemy.orm import Session

from app.models import Book, User
from app.services.agent_intent import execute_brainstorm_plain
from app.services.observability import LLMCallTracker, StreamEmit
from app.services.task_planner import should_route_chapter_edit
from app.services.write_task_executor import (
    execute_consistency_analysis,
    execute_consistency_apply,
    execute_cross_sync,
)

RouteHandler = Callable[["WriteRouteContext"], Awaitable[dict[str, Any]]]


@dataclass
class WriteRouteContext:
    db: Session
    user: User
    book: Book
    message: str
    chapter_no: int
    draft_content: str | None
    understanding: dict[str, Any]
    task_plan: dict[str, Any]
    book_index: dict[str, Any]
    messages: list[dict]
    target_chapter_nos: list[int]
    chapter_contents: dict[int, str]
    edit_context: dict[str, Any]
    merged_history: list[dict]
    last_preview: str
    llm_tracker: LLMCallTracker
    session_id: str = ""
    stream_emit: StreamEmit | None = None
    # 由 handler 填充或 chat_turn 注入
    parse_agent_json: Callable[[str], dict[str, Any]] | None = None
    apply_understanding_constraints: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    execute_sequential_chapter_edits: Callable[..., Awaitable[dict[str, Any]]] | None = None
    chapter_contents_map: Callable[..., dict[int, str]] | None = None
    edit_context_from_understanding: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    sequential_result: dict[str, Any] | None = field(default=None, init=False)
    cross_sync_applied: list[dict] = field(default_factory=list, init=False)


def resolve_route_name(ctx: WriteRouteContext) -> str:
    intent = str(ctx.understanding.get("intent") or "general")
    if intent in ("consistency_check", "analyze_only"):
        return "consistency_analysis"
    if intent == "cross_sync" and ctx.understanding.get("execute_prior_plan"):
        return "cross_sync_apply"
    if intent == "cross_sync":
        return "cross_sync"
    if should_route_chapter_edit(intent, ctx.task_plan):
        return "chapter_edit"
    return "default_llm"


async def _route_consistency_analysis(ctx: WriteRouteContext) -> dict[str, Any]:
    result = await execute_consistency_analysis(
        ctx.user,
        ctx.messages,
        understanding=ctx.understanding,
        task_plan=ctx.task_plan,
        user_message=ctx.message,
        book_index=ctx.book_index,
    )
    return {
        "reply": result["reply"],
        "edits": [],
        "cards": result.get("cards") or [],
        "apply_card_ids": result.get("apply_card_ids") or [],
        "actions": [],
        "analysis": result.get("analysis"),
    }


async def _route_cross_sync_apply(ctx: WriteRouteContext) -> dict[str, Any]:
    apply_result = await execute_consistency_apply(
        ctx.db,
        ctx.book,
        ctx.user,
        ctx.understanding.get("session_id") or ctx.session_id or "",
        ctx.messages,
        understanding=ctx.understanding,
        task_plan=ctx.task_plan,
        user_message=ctx.message,
        book_index=ctx.book_index,
    )
    ctx.cross_sync_applied = list(apply_result.get("card_applied") or [])
    chapter_targets = list(apply_result.get("chapter_target_nos") or [])
    reply_parts = list(apply_result.get("reply_parts") or [])
    plan_summary = str(apply_result.get("plan_summary") or "").strip()
    sequential_result: dict[str, Any] | None = None

    if chapter_targets and ctx.execute_sequential_chapter_edits and ctx.chapter_contents_map:
        exec_contents = ctx.chapter_contents_map(
            ctx.db,
            ctx.book,
            chapter_targets,
            draft_content=ctx.draft_content,
            focus_chapter_no=ctx.chapter_no,
        )
        exec_understanding = {
            **ctx.understanding,
            "intent": "edit_text",
            "target_chapter_nos": chapter_targets,
            "edit_scope": "multi_chapter" if len(chapter_targets) > 1 else "chapter",
            "allow_edits": True,
            "summary": f"按一致性方案修正第 {', '.join(str(n) for n in chapter_targets)} 章正文",
            "must_do": [
                "按上一轮分析的统一方案修正正文",
                "确保正文与已写入的角色卡/大纲设定一致",
            ],
        }
        exec_message = (
            f"{plan_summary}\n\n用户确认执行：{ctx.message}" if plan_summary else ctx.message
        )
        exec_edit_context = (
            ctx.edit_context_from_understanding(exec_understanding)
            if ctx.edit_context_from_understanding
            else ctx.edit_context
        )
        if ctx.stream_emit:
            ctx.stream_emit("progress", {"phase": "chapter_edits", "chapters": chapter_targets})
        sequential_result = await ctx.execute_sequential_chapter_edits(
            ctx.db,
            ctx.book,
            ctx.user,
            ctx.messages,
            chapter_targets,
            exec_understanding,
            exec_message,
            exec_contents,
            exec_edit_context,
            focus_chapter_no=ctx.chapter_no,
            editor_draft=ctx.draft_content,
            stream_emit=ctx.stream_emit,
            llm_tracker=ctx.llm_tracker,
        )
        ctx.sequential_result = sequential_result
        if sequential_result.get("applied"):
            reply_parts.append(sequential_result["reply"])
        else:
            reply_parts.append(
                sequential_result.get("reply") or "⚠️ 章节正文未能写入，请缩小范围或指定章号后重试。"
            )
    else:
        reply_parts.append(
            "ℹ️ 分析报告中未识别到需改正文的章号；若需改正文请说明章号（如「修正第1、7章」）。"
        )

    if not ctx.cross_sync_applied and not (sequential_result and sequential_result.get("applied")):
        reply_parts.append(
            "⚠️ **未能完成任何写入**（设定与正文均未变更）。请检查上一轮是否有草案卡片，或重新说明要修改的内容。"
        )

    return {
        "reply": "\n\n".join(reply_parts),
        "edits": (sequential_result or {}).get("edits") or [],
        "cards": apply_result.get("cards") or [],
        "apply_card_ids": [],
        "actions": [],
        "analysis": apply_result.get("analysis"),
    }


async def _route_cross_sync(ctx: WriteRouteContext) -> dict[str, Any]:
    cross_result = await execute_cross_sync(
        ctx.db,
        ctx.book,
        ctx.user,
        ctx.messages,
        understanding=ctx.understanding,
        task_plan=ctx.task_plan,
        user_message=ctx.message,
        book_index=ctx.book_index,
    )
    ctx.cross_sync_applied = list(cross_result.get("card_applied") or [])
    return {
        "reply": cross_result["reply"],
        "edits": [],
        "cards": cross_result.get("cards") or [],
        "apply_card_ids": cross_result.get("apply_card_ids") or [],
        "actions": [],
        "analysis": cross_result.get("analysis"),
    }


async def _route_chapter_edit(ctx: WriteRouteContext) -> dict[str, Any]:
    if not ctx.execute_sequential_chapter_edits:
        raise RuntimeError("execute_sequential_chapter_edits not injected")
    if ctx.stream_emit:
        ctx.stream_emit(
            "progress",
            {"phase": "chapter_edits", "chapters": ctx.target_chapter_nos},
        )
    sequential_result = await ctx.execute_sequential_chapter_edits(
        ctx.db,
        ctx.book,
        ctx.user,
        ctx.messages,
        ctx.target_chapter_nos,
        ctx.understanding,
        ctx.message,
        ctx.chapter_contents,
        ctx.edit_context,
        focus_chapter_no=ctx.chapter_no,
        editor_draft=ctx.draft_content,
        stream_emit=ctx.stream_emit,
        llm_tracker=ctx.llm_tracker,
    )
    ctx.sequential_result = sequential_result
    return {
        "reply": sequential_result["reply"],
        "edits": sequential_result["edits"],
        "cards": [],
        "apply_card_ids": [],
        "actions": [],
    }


async def _route_default_llm(ctx: WriteRouteContext) -> dict[str, Any]:
    from app.services.observability import tracked_chat, tracked_chat_stream

    intent = str(ctx.understanding.get("intent") or "general")
    use_json = intent != "brainstorm"
    temperature = 0.65 if use_json else 0.72

    if ctx.stream_emit and not use_json:
        tokens: list[str] = []

        def on_token(t: str) -> None:
            tokens.append(t)
            ctx.stream_emit("token", {"text": t})

        raw = await tracked_chat_stream(
            ctx.llm_tracker,
            ctx.user,
            ctx.messages,
            purpose="write_agent_reply",
            temperature=temperature,
            max_tokens=16384,
            json_object=use_json,
            on_token=on_token,
        )
    elif ctx.stream_emit and use_json:
        raw = await tracked_chat(
            ctx.llm_tracker,
            ctx.user,
            ctx.messages,
            purpose="write_agent_reply",
            temperature=temperature,
            max_tokens=16384,
            json_object=True,
        )
        reply_preview = ""
        if ctx.parse_agent_json:
            try:
                reply_preview = str(ctx.parse_agent_json(raw).get("reply") or "")
            except (ValueError, TypeError):
                reply_preview = raw[:200]
        if reply_preview:
            ctx.stream_emit("reply", {"text": reply_preview})
    else:
        raw = await tracked_chat(
            ctx.llm_tracker,
            ctx.user,
            ctx.messages,
            purpose="write_agent_reply",
            temperature=temperature,
            max_tokens=16384,
            json_object=use_json,
        )

    if not ctx.parse_agent_json or not ctx.apply_understanding_constraints:
        return {"reply": raw, "edits": [], "cards": [], "apply_card_ids": [], "actions": []}

    import json

    try:
        parsed = ctx.parse_agent_json(raw)
    except (json.JSONDecodeError, ValueError):
        from app.services.agent_intent import salvage_reply_from_raw

        salvaged = salvage_reply_from_raw(raw)
        parsed = {
            "reply": salvaged or raw.strip()[:8000],
            "edits": [],
            "cards": [],
            "apply_card_ids": [],
            "actions": [],
        }

    parsed = ctx.apply_understanding_constraints(parsed)

    needs_plain = intent == "brainstorm" and (
        parsed.pop("_needs_brainstorm_retry", False)
        or not str(parsed.get("reply") or "").strip()
    )
    if needs_plain:
        parsed = await execute_brainstorm_plain(ctx.user, ctx.messages, ctx.understanding, ctx.message)
        parsed = ctx.apply_understanding_constraints(parsed)
    elif parsed.pop("_needs_brainstorm_retry", False):
        retry_msgs = ctx.messages + [
            {
                "role": "user",
                "content": "上次回复不合格：用户要头脑风暴内容，你必须在 reply 正文中直接列出完整候选（编号列表），"
                "cards 与 actions 必须为空。请重新回答。",
            }
        ]
        raw2 = await tracked_chat(
            ctx.llm_tracker,
            ctx.user,
            retry_msgs,
            purpose="write_agent_brainstorm_retry",
            temperature=0.55,
            max_tokens=16384,
            json_object=True,
        )
        try:
            parsed = ctx.parse_agent_json(raw2)
            parsed = ctx.apply_understanding_constraints(parsed)
        except (json.JSONDecodeError, ValueError):
            parsed = await execute_brainstorm_plain(ctx.user, ctx.messages, ctx.understanding, ctx.message)
            parsed = ctx.apply_understanding_constraints(parsed)

    return parsed


ROUTE_REGISTRY: dict[str, RouteHandler] = {
    "consistency_analysis": _route_consistency_analysis,
    "cross_sync_apply": _route_cross_sync_apply,
    "cross_sync": _route_cross_sync,
    "chapter_edit": _route_chapter_edit,
    "default_llm": _route_default_llm,
}


async def execute_route(ctx: WriteRouteContext) -> tuple[str, dict[str, Any]]:
    name = resolve_route_name(ctx)
    handler = ROUTE_REGISTRY[name]
    parsed = await handler(ctx)
    return name, parsed
