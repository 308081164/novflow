"""lint 行号定位与校验。"""
from app.services.rule_engine import (
    find_line_for_excerpt,
    fix_chapter_title,
    has_chapter_title,
    lint_chapter,
    lint_report_from_issues,
    normalize_lint_issues,
    resolve_issue_line,
    auto_fix_content,
    LintResult,
)

SAMPLE = """# 第001章 测试

第一段正文，这里有一些内容。

第二段，逗号，很多，逗号，问题，在这里。
"""

USER_CH3 = "送走雷震天之后，我瘫在椅子上，盯着天花板发呆。\n\n第二段正文。"
USER_CH4 = "铁虎走后的第二天上午，我诊所的门被敲得震天响。"


def test_find_line_for_excerpt_skips_blank_lines():
    content = "# 标题\n\n违规句子在这里\n"
    assert find_line_for_excerpt(content, "违规句子") == 3
    assert find_line_for_excerpt(content, "不存在的内容") == 0


def test_find_line_for_excerpt_does_not_match_empty_line_via_substring():
    """旧 bug：line.strip() in ex 会让空行匹配任意 excerpt。"""
    content = "# 第001章\n\n正文\n"
    assert find_line_for_excerpt(content, "任意 excerpt 文本") == 0


def test_resolve_issue_line_prefers_excerpt_over_stale_line_no():
    content = "a\nb\nc\n"
    assert resolve_issue_line(content, 1, "c") == 3


def test_resolve_issue_line_clears_when_excerpt_missing():
    content = "# 第001章\n\n已修复的正文\n"
    assert resolve_issue_line(content, 5, "已删除的违规片段") == 0


def test_normalize_lint_issues_clears_stale_line():
    issues = [
        LintResult("ai_lint", "error", 2, "已删除片段", "测试", False, True),
    ]
    normalized = normalize_lint_issues("# 标题\n\n", issues)
    assert normalized[0].line_no == 0


def test_lint_report_normalizes_before_return():
    issues = [
        LintResult("comma_max_3", "error", 99, "不存在", "逗号过多", True),
    ]
    report = lint_report_from_issues(SAMPLE, issues)
    assert report["issues"][0]["line_no"] == 0


def test_lint_chapter_line_numbers_match_content():
    content = SAMPLE
    issues = lint_chapter(content, chapter_no=1)
    report = lint_report_from_issues(content, issues)
    lines = content.splitlines()
    for item in report["issues"]:
        ln = item["line_no"]
        if ln <= 0:
            continue
        ex = (item.get("excerpt") or "").strip()
        if ex:
            assert ex in lines[ln - 1], f"excerpt not on line {ln}: {ex!r}"


def test_chapter_title_flags_first_body_line_when_header_missing():
    issues = lint_chapter(USER_CH3, chapter_no=3)
    ct = [i for i in issues if i.rule_id == "chapter_title"]
    assert len(ct) == 1
    assert ct[0].line_no == 1
    assert ct[0].excerpt.startswith("送走雷震天")
    assert ct[0].auto_fixable is True


def test_fix_chapter_title_prepends_markdown_header():
    fixed = fix_chapter_title(USER_CH3, chapter_no=3, title="雷震天")
    assert fixed.startswith("# 第003章 雷震天\n\n")
    assert "送走雷震天之后" in fixed
    assert has_chapter_title(fixed)
    report = lint_report_from_issues(fixed, lint_chapter(fixed, chapter_no=3))
    assert not any(i["rule_id"] == "chapter_title" for i in report["issues"])


def test_auto_fix_content_inserts_title_and_clears_chapter_title_issue():
    fixed = auto_fix_content(USER_CH4, chapter_no=4, chapter_title="铁虎")
    assert has_chapter_title(fixed)
    report = lint_report_from_issues(fixed, lint_chapter(fixed, chapter_no=4))
    assert not any(i["rule_id"] == "chapter_title" for i in report["issues"])


def test_find_line_for_excerpt_skips_chapter_heading():
    content = "# 第002章 社区过关与拼贴梦\n\n楼道里立刻涌进来外卖味。"
    assert find_line_for_excerpt(content, "社区") == 0
    assert find_line_for_excerpt(content, "过关与拼贴梦") == 0
    assert find_line_for_excerpt(content, "楼道里立刻涌进来") == 3


def test_fix_chapter_title_dedupes_db_title_prefix():
    fixed = fix_chapter_title(USER_CH3, chapter_no=3, title="第003章 同行是冤家")
    assert fixed.startswith("# 第003章 同行是冤家\n\n")


def test_fix_chapter_title_strips_lone_hash_line():
    broken = "#\n\n正文第一句。"
    fixed = fix_chapter_title(broken, chapter_no=2, title="测试章")
    assert fixed.startswith("# 第002章 测试章\n\n正文第一句。")
    assert not has_chapter_title("#")
