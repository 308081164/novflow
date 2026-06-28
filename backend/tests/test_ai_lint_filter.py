"""AI lint 过滤回归测试。"""
from app.services.ai_lint_filter import filter_ai_lint_items, is_actionable_ai_lint_issue

# 用户截图中的误报样例
FALSE_POSITIVES = [
    ("format", "error", "章号应为三位数，当前为007，但格式正确；无其他格式问题。"),
    ("language", "warn", "本章未发现明显排比或罗列"),
    ("language", "warn", "本章未使用比喻"),
    ("compliance", "error", "本章延续冲突，符合要求"),
    ("preference", "warn", "叙事视角符合偏好"),
    ("preference", "warn", "角色口吻符合要求"),
    ("preference", "warn", "节奏符合偏好"),
]

TRUE_VIOLATIONS = [
    ("comma_max_3", "error", "单句逗号超过3个，建议拆句"),
    ("no_em_dash", "error", "含破折号——违反§2.3禁"),
    ("writing_convention", "warn", "不符合写作规约，章首不应出现说明书"),
    ("format", "error", "章号格式不正确，应为三位数"),
]


def test_false_positive_messages_filtered():
    for typ, sev, msg in FALSE_POSITIVES:
        assert not is_actionable_ai_lint_issue(msg, sev), f"should filter: {msg}"


def test_true_violations_kept():
    for typ, sev, msg in TRUE_VIOLATIONS:
        assert is_actionable_ai_lint_issue(msg, sev), f"should keep: {msg}"


def test_filter_ai_lint_items():
    raw = [{"type": t, "severity": s, "message": m, "line": 0, "excerpt": ""} for t, s, m in FALSE_POSITIVES]
    raw += [{"type": t, "severity": s, "message": m, "line": 1, "excerpt": "违规句"} for t, s, m in TRUE_VIOLATIONS]
    out = filter_ai_lint_items(raw)
    assert len(out) == len(TRUE_VIOLATIONS)
    assert all(is_actionable_ai_lint_issue(i["message"], i["severity"]) for i in out)
