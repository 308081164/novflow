"""任务规划与多资源意图路由测试。"""
from app.services.agent_intent import is_edit_text_message, _rule_write_intent
from app.services.task_planner import (
    detect_affected_resources,
    is_multi_resource_analysis_message,
    plan_write_task,
    should_route_chapter_edit,
)


def test_multi_resource_analysis_not_edit_text():
    msg = "帮我检查一下故事大纲和角色卡有没有冲突，并统一一下"
    assert is_multi_resource_analysis_message(msg)
    assert not is_edit_text_message(msg)


def test_chapter_polish_still_edit_text():
    msg = "润色本章，让开头更抓人"
    assert not is_multi_resource_analysis_message(msg)
    assert is_edit_text_message(msg)


def test_rule_intent_consistency_check():
    msg = "检查大纲和角色卡的矛盾，列出冲突"
    rule = _rule_write_intent(msg, [])
    assert rule["intent"] == "consistency_check"
    assert rule["allow_edits"] is False
    assert rule["allow_cards"] is True


def test_rule_intent_cross_sync_with_apply():
    msg = "对照大纲和角色卡，统一设定并应用"
    rule = _rule_write_intent(msg, [])
    assert rule["intent"] == "cross_sync"


def test_plan_write_task_consistency():
    understanding = {
        "intent": "consistency_check",
        "topic": "outline",
        "summary": "检查大纲与角色卡冲突",
        "allow_edits": False,
        "allow_cards": True,
    }
    msg = "检查大纲和角色卡冲突"
    plan = plan_write_task(msg, understanding, book_index={"characters": [], "chapter_plans": []})
    assert plan["execution_mode"] == "analyze_only"
    assert "outline" in plan["resources"]
    assert "characters" in plan["resources"]
    assert len(plan["steps"]) >= 3
    assert not should_route_chapter_edit("consistency_check", plan)


def test_detect_resources_from_message():
    msg = "对比章节大纲和男主角色卡"
    resources = detect_affected_resources(msg, {"intent": "consistency_check", "topic": "outline"})
    assert "outline" in resources
    assert "characters" in resources


def test_sync_chapters_still_edit():
    msg = "同步全书各章，让逻辑一致"
    assert is_edit_text_message(msg)
