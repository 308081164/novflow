"""选段修改：解析与合并回整章。"""
from app.services.agent_intent import (
    edit_failure_reply,
    finalize_chapter_edit_content,
    is_meta_summary_content,
    merge_selection_into_chapter,
    parse_selection_from_message,
)

SAMPLE = (
    """铁虎前脚刚走，我还没来得及瘫回椅子上喘口气，门又开了。
林晚探头进来，脸色不太对。
「出事了。」她只说两个字。"""
    * 5
)

SELECTION = "铁虎前脚刚走，我还没来得及瘫回椅子上喘口气，门又开了。"

FIXED_SELECTION = "铁虎前脚刚踏出门槛，我还没来得及瘫回椅子上喘口气，门又被推开了。"


def test_parse_selection_from_message():
    msg = f"【选段 · 第2章】\n> {SELECTION}\n\n请针对以上选段：不符合写作规约"
    ch, quote = parse_selection_from_message(msg)
    assert ch == 2
    assert SELECTION in quote


def test_merge_selection_short_reply():
    merged = merge_selection_into_chapter(SAMPLE, SELECTION, FIXED_SELECTION)
    assert merged is not None
    assert FIXED_SELECTION in merged
    assert "林晚探头" in merged


def test_finalize_selection_edit():
    result = finalize_chapter_edit_content(
        FIXED_SELECTION,
        chapter_no=2,
        original_content=SAMPLE,
        edit_scope="selection",
        selection_quote=SELECTION,
    )
    assert result is not None
    assert len(result) >= len(SAMPLE) * 0.8
    assert not is_meta_summary_content(result)


def test_edit_failure_reply_selection():
    msg = edit_failure_reply(edit_scope="selection", target_chapter_nos=[2])
    assert "选段" in msg
    assert "未被修改" in msg
