"""过滤 AI lint 中的非违规/通过项，避免「格式正确」等被标红。"""
from __future__ import annotations

import re

# 明确表示「无问题 / 已通过」
_PASS_RE = re.compile(
    r"格式正确|符合(?:要求|偏好|规约|标准|规范|设定)|"
    r"未发现(?:明显|任何|相关)?(?:问题|违规|违反)?|"
    r"无明显(?:问题|违规|违反)?|"
    r"无其他(?:格式|规则|问题)?(?:问题)?|"
    r"无问题|没有问题|未违反|满足要求|已通过|"
    r"延续.{0,12}符合|"
    r"但.{0,24}正确|"
    r"无(?:明显|其他)(?:格式|规则|问题)"
)

# 明确违规信号
_VIOLATION_RE = re.compile(
    r"不符合|违反|禁(?:止|用)|缺少|缺失|不应|不要|"
    r"过多|不足|错误|违规|超标|超限|"
    r"需(?:要)?(?:修改|调整|删除|补充|改写|重写)|"
    r"建议(?:修改|调整|删除|补充|改写|避免|减少)|"
    r"存在(?:问题|风险)|"
    r"太(?:多|长|短|少)|"
    r"含(?:有)?(?:破折号|meta|清单|分隔线)"
)

# 纯观察性描述（非 actionable）
_NEUTRAL_RE = re.compile(
    r"^(本章)?未(?:使用|出现|包含|检测到)|^(本章)?无(?:明显|相关)"
)


def is_actionable_ai_lint_issue(message: str, severity: str = "warn") -> bool:
    """AI 返回的 issue 是否应展示给用户。"""
    msg = (message or "").strip()
    if len(msg) < 4:
        return False
    if _PASS_RE.search(msg):
        return False
    if _VIOLATION_RE.search(msg):
        return True
    if _NEUTRAL_RE.search(msg):
        return False
    # 无明确违规信号时，warn 一律丢弃；error 保留（保守）
    return severity == "error"


def filter_ai_lint_items(items: list[dict]) -> list[dict]:
    """过滤 AI lint issue 列表。"""
    out: list[dict] = []
    for item in items:
        msg = str(item.get("message") or "")
        sev = str(item.get("severity") or "warn")
        if is_actionable_ai_lint_issue(msg, sev):
            out.append(item)
    return out
