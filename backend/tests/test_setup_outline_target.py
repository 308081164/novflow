"""setup_agent 大纲目标章数与分片规划测试。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import Book
from app.services.setup_agent import (
    _compute_shard_plan,
    _infer_total_chapters_from_plot_data,
    _parse_requested_outline_range,
    resolve_effective_target_chapters,
    sync_target_chapters_from_plot_framework,
)


def _book(**kwargs) -> Book:
    b = Book(id=1, user_id=1, title="测试", target_chapters=100)
    for k, v in kwargs.items():
        setattr(b, k, v)
    return b


def test_infer_total_from_phases():
    data = {
        "phases": [
            {"name": "第一阶段", "chapter_range": "1-200", "description": "开局"},
            {"name": "第五阶段", "chapter_range": "751-900", "description": "终局"},
        ]
    }
    assert _infer_total_chapters_from_plot_data(data) == 900


def test_resolve_effective_target_chapters():
    book = _book(
        plot_framework={
            "phases": [{"chapter_range": "751-900"}],
            "summary": "900章长篇",
        }
    )
    assert resolve_effective_target_chapters(book) == 900


def test_sync_target_from_plot_framework():
    book = _book(plot_framework={"total_chapters": 900, "phases": []})
    assert sync_target_chapters_from_plot_framework(book) is True
    assert book.target_chapters == 900


def test_parse_requested_outline_range():
    assert _parse_requested_outline_range("请继续规划第21-25章大纲") == (21, 25)
    assert _parse_requested_outline_range("规划21～25章") == (21, 25)


def test_compute_shard_plan_explicit_range():
    book = _book(target_chapters=100, plot_framework={"phases": [{"chapter_range": "751-900"}]})
    progress = {"outline_written": 20, "outline_target": 900}
    shard = _compute_shard_plan(book, progress, "请继续规划第21-25章大纲")
    assert shard is not None
    assert shard["next_start"] == 21
    assert shard["next_end"] == 25
    assert shard["total_chapters"] == 900


def test_compute_shard_plan_not_confuse_range_with_total():
    book = _book(target_chapters=900)
    progress = {"outline_written": 20, "outline_target": 900}
    shard = _compute_shard_plan(book, progress, "请继续规划第21-25章大纲")
    assert shard["total_chapters"] == 900
