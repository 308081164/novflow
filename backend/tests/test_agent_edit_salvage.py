"""智能体正文写入与 reply 回收测试。"""
from app.services.agent_intent import (
    reply_implies_edit_success,
    salvage_edits_from_chapter_sections,
    split_reply_by_chapter_sections,
)

CH1_OLD = """# 第001章 开业

「我叫铁虎。」壮汉自报家门，「铁拳会的会长，S级能力【钢筋铁骨】。」
"""

CH1_NEW = """# 第001章 开业

「我叫铁虎。」壮汉自报家门，「铁拳会的副会长，C级能力【钢筋铁骨】。」
"""


def test_reply_implies_edit_success_detects_false_claims():
    assert reply_implies_edit_success("以下是第1、3、7章的修改后完整正文")
    assert reply_implies_edit_success("已修改第 2 章并写入编辑器。")
    assert not reply_implies_edit_success("排查发现以下矛盾点，建议修改。")


def test_split_reply_by_chapter_sections():
    reply = """排查完成。修改如下：

# 第001章 开业

「我叫铁虎。」壮汉自报家门，「铁拳会的副会长，C级能力【钢筋铁骨】。」

# 第003章 测试

第二段正文。
"""
    sections = split_reply_by_chapter_sections(reply)
    assert len(sections) == 2
    assert sections[0][0] == 1
    assert "副会长" in sections[0][1]
    assert sections[1][0] == 3


def test_salvage_edits_from_chapter_sections_skips_unchanged():
    reply = f"以下是修改后正文：\n\n{CH1_NEW}\n\n# 第003章 其他\n\n新章内容足够长。" + "正文。" * 50
    contents = {1: CH1_OLD.strip(), 3: "旧第三章" + "内容。" * 80}
    edits = salvage_edits_from_chapter_sections(reply, [1, 3], contents)
    nos = {e["chapter_no"] for e in edits}
    assert 1 in nos
    assert all("副会长" in e["content"] for e in edits if e["chapter_no"] == 1)


def test_salvage_ignores_unchanged_chapter():
    reply = f"# 第001章 开业\n\n{CH1_OLD.split(chr(10), 2)[-1].strip()}"
    edits = salvage_edits_from_chapter_sections(reply, [1], {1: CH1_OLD.strip()})
    assert edits == []
