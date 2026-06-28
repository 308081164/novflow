"""chat_turn 集成测试（mock LLM）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.task_planner import plan_write_task
from app.services.write_agent_routing import WriteRouteContext, execute_route, resolve_route_name


def test_resolve_route_analyze_only():
    ctx = MagicMock()
    ctx.understanding = {"intent": "consistency_check"}
    ctx.task_plan = {"execution_mode": "analyze_only"}
    assert resolve_route_name(ctx) == "consistency_analysis"


def test_resolve_route_apply_plan():
    ctx = MagicMock()
    ctx.understanding = {"intent": "cross_sync", "execute_prior_plan": True}
    assert resolve_route_name(ctx) == "cross_sync_apply"


def test_plan_analyze_only_mode():
    understanding = {
        "intent": "consistency_check",
        "topic": "outline",
        "summary": "检查冲突",
        "allow_edits": False,
        "allow_cards": True,
    }
    plan = plan_write_task("检查大纲和角色卡冲突", understanding, book_index={"characters": [], "chapter_plans": []})
    assert plan["execution_mode"] == "analyze_only"


@pytest.mark.asyncio
async def test_route_consistency_analysis_parsed_shape():
    ctx = WriteRouteContext(
        db=MagicMock(),
        user=MagicMock(),
        book=MagicMock(),
        message="检查大纲和角色卡有没有冲突",
        chapter_no=1,
        draft_content=None,
        understanding={"intent": "consistency_check"},
        task_plan={"execution_mode": "analyze_only", "resources": ["outline", "characters"], "steps": []},
        book_index={"characters": [], "chapter_plans": []},
        messages=[{"role": "user", "content": "test"}],
        target_chapter_nos=[],
        chapter_contents={},
        edit_context={},
        merged_history=[],
        last_preview="",
        llm_tracker=MagicMock(call_count=0, estimated_tokens=0, calls=[]),
        session_id="sess-1",
    )
    mock_result = {
        "reply": "分析完成",
        "cards": [{"id": "c1", "type": "outline", "status": "draft", "data": {}}],
        "apply_card_ids": [],
        "analysis": {"conflicts": []},
    }
    with patch(
        "app.services.write_agent_routing.execute_consistency_analysis",
        new=AsyncMock(return_value=mock_result),
    ):
        route_name, parsed = await execute_route(ctx)
    assert route_name == "consistency_analysis"
    assert parsed["reply"] == "分析完成"
    assert parsed["edits"] == []
    assert parsed["apply_card_ids"] == []


@pytest.mark.asyncio
async def test_route_cross_sync_apply_with_chapter_targets():
    sequential = {
        "reply": "已改第1章",
        "edits": [{"chapter_no": 1, "content": "正文"}],
        "applied": [{"chapter_no": 1}],
        "revert_snapshots": [],
    }
    apply_result = {
        "card_applied": [{"type": "character", "ok": True}],
        "chapter_target_nos": [1],
        "reply_parts": ["设定已写入"],
        "plan_summary": "统一方案",
        "cards": [],
        "analysis": {},
    }
    ctx = WriteRouteContext(
        db=MagicMock(),
        user=MagicMock(),
        book=MagicMock(),
        message="开始执行",
        chapter_no=1,
        draft_content=None,
        understanding={"intent": "cross_sync", "execute_prior_plan": True},
        task_plan={"execution_mode": "apply_plan", "resources": ["chapters"], "steps": []},
        book_index={},
        messages=[],
        target_chapter_nos=[1],
        chapter_contents={1: "旧正文"},
        edit_context={},
        merged_history=[],
        last_preview="",
        llm_tracker=MagicMock(call_count=0, estimated_tokens=0, calls=[]),
        session_id="sess-2",
        execute_sequential_chapter_edits=AsyncMock(return_value=sequential),
        chapter_contents_map=MagicMock(return_value={1: "旧正文"}),
        edit_context_from_understanding=MagicMock(return_value={"edit_scope": "chapter"}),
    )
    with patch(
        "app.services.write_agent_routing.execute_consistency_apply",
        new=AsyncMock(return_value=apply_result),
    ):
        route_name, parsed = await execute_route(ctx)
    assert route_name == "cross_sync_apply"
    assert "设定已写入" in parsed["reply"]
    assert ctx.sequential_result is not None
