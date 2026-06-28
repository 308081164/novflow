"""章节正文写入校验：防止改动说明被当作正文覆盖章节。"""
from app.services.agent_intent import is_meta_summary_content, is_valid_chapter_edit_content

BUG_SUMMARY = (
    '已修正第2章中"铁虎被扎笑"的错误引用，删除该句，'
    "并通读全章排查所有依赖该前提的表述。"
)

SAMPLE_CHAPTER = """铁虎站在巷口，风把他的衣角吹得猎猎作响。
「你确定要这么做？」林晚低声问。
他没有回答，只是握紧了手里的刀柄。""" * 20


def test_meta_summary_detects_operation_description():
    assert is_meta_summary_content(BUG_SUMMARY) is True


def test_valid_rejects_summary_as_chapter():
    assert is_valid_chapter_edit_content(
        BUG_SUMMARY, chapter_no=2, original_content=SAMPLE_CHAPTER
    ) is False


def test_valid_accepts_full_chapter():
    assert is_valid_chapter_edit_content(
        SAMPLE_CHAPTER, chapter_no=2, original_content=SAMPLE_CHAPTER
    ) is True


def test_valid_rejects_too_short_replacement():
    short = "铁虎站在巷口，风把他的衣角吹得猎猎作响。"
    assert is_valid_chapter_edit_content(
        short, chapter_no=2, original_content=SAMPLE_CHAPTER
    ) is False
