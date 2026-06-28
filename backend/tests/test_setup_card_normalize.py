"""卡片 schema 规范化测试。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.setup_agent import _normalize_cards_list


def test_normalize_cards_adds_missing_id():
    raw = [{"type": "outline", "data": {"chapters": [{"chapter_no": 11, "plot_points": "x"}]}}]
    out = _normalize_cards_list(raw)
    assert len(out) == 1
    assert out[0]["id"]
    assert out[0]["status"] == "draft"
    assert out[0]["title"] == "outline"
    assert out[0]["data"]["chapters"][0]["chapter_no"] == 11
