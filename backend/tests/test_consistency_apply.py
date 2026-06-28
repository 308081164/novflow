"""一致性分析后「开始执行」路由与方案回收测试。"""
from app.services.agent_intent import _merge_write_understanding, _rule_write_intent
from app.services.task_planner import plan_write_task
from app.services.write_task_executor import (
    coerce_consistency_apply_understanding,
    extract_chapter_nos_from_plan,
    is_execute_plan_message,
    was_consistency_analysis_context,
)


def test_is_execute_plan_message():
    assert is_execute_plan_message("可以，请你开始执行")
    assert is_execute_plan_message("按方案执行修改")
    assert is_execute_plan_message("确认采纳")
    assert is_execute_plan_message("采纳")
    assert not is_execute_plan_message("帮我检查一下大纲")


def test_was_consistency_analysis_context():
    history = [
        {
            "role": "assistant",
            "content": "**任务计划**\n1. 对照各资源\n**冲突清单** 铁虎 S级 vs C级",
        },
    ]
    assert was_consistency_analysis_context(history)


def test_rule_intent_execute_after_analysis():
    history = [
        {
            "role": "assistant",
            "content": "冲突：铁虎角色卡为 S 级，大纲为 C 级。建议统一为 C 级。",
        },
    ]
    rule = _rule_write_intent("可以，请你开始执行", history)
    assert rule["intent"] == "cross_sync"
    assert rule.get("execute_prior_plan") is True
    assert rule.get("auto_apply") is True
    assert rule.get("allow_edits") is True


def test_rule_intent_confirm_adopt_after_analysis():
    history = [
        {
            "role": "assistant",
            "content": "**冲突清单** 大纲第1章与角色卡不一致。建议修正角色卡与大纲。",
        },
    ]
    rule = _rule_write_intent("确认采纳", history)
    assert rule["intent"] == "cross_sync"
    assert rule.get("execute_prior_plan") is True
    assert rule.get("auto_apply") is True


def test_coerce_consistency_apply_from_draft_card():
    history = [
        {
            "role": "assistant",
            "content": "冲突：角色卡与大纲不一致。",
        },
    ]
    understanding = {"intent": "draft_card", "topic": "other", "allow_cards": True}
    coerced = coerce_consistency_apply_understanding("确认采纳", history, understanding)
    assert coerced["intent"] == "cross_sync"
    assert coerced.get("execute_prior_plan") is True


def test_merge_preserves_execute_prior_plan():
    rule = {
        "intent": "cross_sync",
        "topic": "outline",
        "execute_prior_plan": True,
        "auto_apply": True,
        "allow_edits": True,
        "allow_cards": True,
        "must_do": ["写入设定"],
        "must_not_do": [],
    }
    llm = {"intent": "draft_card", "topic": "other", "summary": "采纳方案", "allow_cards": True}
    merged = _merge_write_understanding(llm, rule)
    assert merged["intent"] == "cross_sync"
    assert merged.get("execute_prior_plan") is True


def test_was_consistency_analysis_context_draft_cards():
    history = [
        {
            "role": "assistant",
            "content": "（助手曾输出outline卡片「大纲第1章修正版」状态=draft，共 1 章）",
        },
    ]
    assert was_consistency_analysis_context(history)


def test_extract_chapter_nos_from_plan():
    text = "第1章正文写铁虎为S级；第7章需重写以符合C级设定。"
    analysis = {
        "conflicts": [
            {
                "summary": "铁虎等级冲突",
                "outline_ref": "大纲第7章",
                "suggestion": "修正第1章提及",
            },
        ],
    }
    nos = extract_chapter_nos_from_plan(text, analysis)
    assert 1 in nos
    assert 7 in nos


def test_plan_apply_mode():
    understanding = {
        "intent": "cross_sync",
        "execute_prior_plan": True,
        "auto_apply": True,
        "allow_edits": True,
        "summary": "执行统一方案",
    }
    plan = plan_write_task("开始执行", understanding)
    assert plan["execution_mode"] == "apply_plan"
    assert plan["allow_edits"] is True
