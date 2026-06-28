"""setup_agent 大纲空卡片重试逻辑测试。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.setup_agent import _needs_retry, _outline_response_has_chapters


def test_outline_needs_retry_when_no_cards():
    parsed = {"reply": "好的，我来规划第 11～20 章大纲。", "cards": []}
    assert _needs_retry('{"reply":"..."}', parsed, "outline") is True


def test_outline_no_retry_when_has_chapters():
    parsed = {
        "reply": "已生成",
        "cards": [
            {
                "type": "outline",
                "data": {"chapters": [{"chapter_no": 11, "plot_points": "x" * 50}]},
            }
        ],
    }
    assert _outline_response_has_chapters(parsed) is True
    assert _needs_retry("{}", parsed, "outline") is False


def test_guidance_no_retry_without_cards():
    parsed = {"reply": "建议先完善世界观设定，再规划章节大纲。", "cards": []}
    assert _needs_retry("{}", parsed, "guidance") is False
