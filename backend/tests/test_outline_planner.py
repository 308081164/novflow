"""outline_planner 规则校验测试。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.outline_planner import (
    extract_outline_chapters_from_cards,
    is_outline_regenerate_request,
    normalize_outline_data,
    validate_outline_chapters_rule,
)


def test_normalize_outline_data_list():
    data = [{"chapter_no": 11, "plot_points": "test"}]
    normalized = normalize_outline_data(data)
    assert normalized["chapters"] == data


def test_extract_outline_chapters_when_data_is_list():
    cards = [
        {
            "type": "outline",
            "data": [{"chapter_no": 11, "plot_points": "a"}, {"chapter_no": 12, "plot_points": "b"}],
        }
    ]
    chapters = extract_outline_chapters_from_cards(cards)
    assert len(chapters) == 2
    assert chapters[0]["chapter_no"] == 11


def test_is_outline_regenerate_request():
    assert is_outline_regenerate_request("请删除并重新生成11-20章大纲")
    assert not is_outline_regenerate_request("规划第21-25章大纲")


def test_unknown_character_without_entrance():
    ctx = {
        "start_ch": 21,
        "end_ch": 25,
        "known_character_names": ["陈默", "铁虎"],
        "previous_outlines": ["第20章 …"],
    }
    chapters = [
        {
            "chapter_no": 21,
            "plot_points": "陈默与神秘人张三在诊所对峙，铁虎在门外偷听，局面一触即发。",
            "cast": ["陈默", "张三"],
        }
    ]
    issues = validate_outline_chapters_rule(ctx, chapters)
    assert any(i["category"] == "character" and "张三" in i["message"] for i in issues)


def test_valid_cast_with_entrance():
    ctx = {
        "start_ch": 21,
        "end_ch": 25,
        "known_character_names": ["陈默"],
        "previous_outlines": [],
    }
    chapters = [
        {
            "chapter_no": 21,
            "plot_points": "新角色李医师正式登场，陈默与其切磋针灸术。",
            "cast": ["陈默", "李医师"],
            "entrances": ["李医师"],
        }
    ]
    issues = validate_outline_chapters_rule(ctx, chapters)
    assert not any(i["severity"] == "error" for i in issues)
