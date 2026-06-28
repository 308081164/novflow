from __future__ import annotations

import re
from dataclasses import dataclass, asdict

SENT_SPLIT = re.compile(r"[。！？；]")
SENT_END = frozenset("。！？；")
COMMA = frozenset("，,")
CHAPTER_HEADING_RE = re.compile(r"^#\s*第\d+章")


def _strip_bom(s: str) -> str:
    return s.lstrip("\ufeff")


def _is_heading_line(line: str) -> bool:
    return _strip_bom(line).lstrip().startswith("#")


def has_chapter_title(content: str) -> bool:
    """正文是否已有 Markdown 章标题行（# 第NNN章 …）。"""
    for line in (content or "").splitlines():
        stripped = _strip_bom(line).strip()
        if not stripped:
            continue
        return bool(CHAPTER_HEADING_RE.match(stripped))
    return False


def first_body_line(content: str) -> tuple[int, str]:
    """返回首个正文行（1-based 行号, 行文本）；若仅有标题则 (0, '')。"""
    for i, line in enumerate((content or "").splitlines(), 1):
        stripped = _strip_bom(line).strip()
        if not stripped:
            continue
        if CHAPTER_HEADING_RE.match(stripped):
            return 0, ""
        return i, line
    return 0, ""


@dataclass
class LintResult:
    rule_id: str
    severity: str
    line_no: int
    excerpt: str
    message: str
    auto_fixable: bool = False
    blocking: bool = True

    def to_dict(self):
        return asdict(self)


def comma_count(s: str) -> int:
    return s.count("，") + s.count(",")


def body_text(content: str) -> str:
    lines = content.splitlines()
    return "\n".join(l for l in lines if not l.startswith("#")).strip()


def word_count(content: str) -> int:
    return len(re.sub(r"\s", "", body_text(content)))


def fix_commas_text(text: str) -> str:
    fixed_lines = []
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            fixed_lines.append(line)
            continue
        out: list[str] = []
        cc = 0
        for ch in line:
            if ch in SENT_END:
                cc = 0
                out.append(ch)
            elif ch in COMMA:
                cc += 1
                if cc > 3:
                    out.append("。")
                    cc = 0
                else:
                    out.append(ch)
            else:
                out.append(ch)
        fixed_lines.append("".join(out))
    return "\n".join(fixed_lines)


def fix_em_dash(text: str) -> str:
    return text.replace("——", "。")


def fix_chapter_title(content: str, chapter_no: int, title: str = "") -> str:
    """补全文首 # 第NNN章 标题行，并去掉残缺 # 占位行。"""
    text = content or ""
    if has_chapter_title(text):
        return text
    raw_title = (title or f"第{chapter_no}章").strip()
    subtitle = re.sub(rf"^第\s*0*{chapter_no}\s*章\s*", "", raw_title).strip()
    if not subtitle:
        subtitle = raw_title
    header = f"# 第{chapter_no:03d}章 {subtitle}"
    lines = text.splitlines()
    while lines:
        stripped = _strip_bom(lines[0]).strip()
        if not stripped:
            lines.pop(0)
            continue
        if stripped == "#" or (_is_heading_line(lines[0]) and not CHAPTER_HEADING_RE.match(stripped)):
            lines.pop(0)
            continue
        break
    body = "\n".join(lines).strip("\n")
    if body:
        return f"{header}\n\n{body}"
    return header


def lint_chapter(content: str, chapter_no: int = 1, min_words: int = 2000) -> list[LintResult]:
    issues: list[LintResult] = []
    lines = content.splitlines()
    body = body_text(content)
    wc = len(re.sub(r"\s", "", body))

    if not has_chapter_title(content):
        body_ln, body_line = first_body_line(content)
        issues.append(
            LintResult(
                "chapter_title",
                "error",
                body_ln or 1,
                body_line[:80] if body_line else "",
                "缺少文首 # 第NNN章 标题行",
                True,
            )
        )

    if "——" in body:
        for i, line in enumerate(lines, 1):
            if "——" in line and not line.startswith("#"):
                issues.append(LintResult("no_em_dash", "error", i, line[:80], "含破折号「——」（§2.3 禁）", True))
                break

    if re.search(r"^---\s*$", content, re.M):
        issues.append(LintResult("no_hr", "error", 0, "---", "含 --- 分隔线", False))

    if re.search(r"^(时间|地点|今日|本章)[：:]", body, re.M):
        issues.append(LintResult("no_meta_header", "error", 0, "", "疑似章首说明书/meta 块", False))

    if re.search(r"选项[一二三四]", body):
        issues.append(LintResult("no_option_list", "error", 0, "", "含「选项一/二」清单体", False))

    for ln, line in enumerate(lines, 1):
        if line.startswith("#") or not line.strip():
            continue
        for sent in SENT_SPLIT.split(line):
            sent = sent.strip()
            if comma_count(sent) > 3:
                issues.append(
                    LintResult(
                        "comma_max_3",
                        "error",
                        ln,
                        sent[:80],
                        f"单句逗号>{3}（现 {comma_count(sent)}）",
                        True,
                    )
                )

    if wc < 400:
        issues.append(LintResult("word_min", "error", 0, "", f"正文过短（{wc} 字）", False, blocking=False))
    elif wc < 800:
        issues.append(LintResult("word_min", "warn", 0, "", f"正文偏短（{wc} 字）", False, blocking=False))
    elif chapter_no >= 6 and wc < 1500:
        issues.append(LintResult("word_target", "warn", 0, "", f"低于约2000字目标（现 {wc} 字）", False, blocking=False))

    return issues


def find_line_for_excerpt(content: str, excerpt: str) -> int:
    """根据 excerpt 在正文中定位行号（AI lint 常用）。跳过标题/空行，找不到返回 0。"""
    ex = (excerpt or "").strip()
    if not ex:
        return 0
    lines = content.splitlines()

    def _scan(needle: str) -> int:
        for i, line in enumerate(lines, 1):
            if _is_heading_line(line) or not line.strip():
                continue
            if needle in line:
                return i
        return 0

    hit = _scan(ex)
    if hit:
        return hit
    short = ex[:24]
    if len(short) >= 8:
        return _scan(short)
    return 0


def resolve_issue_line(content: str, line_no: int, excerpt: str) -> int:
    """校验或重算 1-based 行号；excerpt 不在正文中则返回 0（不做行级高亮）。"""
    ex = (excerpt or "").strip()
    if ex:
        return find_line_for_excerpt(content, ex)
    if line_no > 0:
        lines = content.splitlines()
        if 0 < line_no <= len(lines):
            return line_no
    return 0


def normalize_lint_issues(content: str, issues: list[LintResult]) -> list[LintResult]:
    """将 issue 行号与当前正文对齐，避免 stale line_no 或空行误匹配。"""
    out: list[LintResult] = []
    for issue in issues:
        line = resolve_issue_line(content, issue.line_no, issue.excerpt)
        if line == issue.line_no:
            out.append(issue)
        else:
            out.append(
                LintResult(
                    rule_id=issue.rule_id,
                    severity=issue.severity,
                    line_no=line,
                    excerpt=issue.excerpt,
                    message=issue.message,
                    auto_fixable=issue.auto_fixable,
                    blocking=issue.blocking,
                )
            )
    return out


def lint_report_from_issues(content: str, issues: list[LintResult]) -> dict:
    issues = normalize_lint_issues(content, issues)
    errs = [i for i in issues if i.severity == "error"]
    warns = [i for i in issues if i.severity == "warn"]
    return {
        "word_count": word_count(content or ""),
        "issues": [i.to_dict() for i in issues],
        "error_count": len(errs),
        "warn_count": len(warns),
        "passed": len([i for i in errs if i.blocking]) == 0,
    }


def auto_fix_content(
    content: str,
    *,
    chapter_no: int = 0,
    chapter_title: str = "",
    max_passes: int = 5,
) -> str:
    text = content or ""
    if chapter_no > 0 and not has_chapter_title(text):
        text = fix_chapter_title(text, chapter_no, chapter_title)
    for _ in range(max_passes):
        next_text = fix_commas_text(fix_em_dash(text))
        if next_text == text:
            break
        text = next_text
    return text


def auto_fix_issue(
    content: str,
    issue: LintResult | dict,
    *,
    chapter_no: int = 0,
    chapter_title: str = "",
) -> str:
    """修复单条可自动修复的问题。"""
    if isinstance(issue, dict):
        rule_id = str(issue.get("rule_id") or "")
        line_no = int(issue.get("line_no") or 0)
        auto_fixable = bool(issue.get("auto_fixable"))
    else:
        rule_id = issue.rule_id
        line_no = issue.line_no
        auto_fixable = issue.auto_fixable
    if not auto_fixable:
        return content
    if rule_id == "chapter_title" and chapter_no > 0:
        return fix_chapter_title(content, chapter_no, chapter_title)
    if rule_id in ("no_em_dash", "comma_max_3"):
        if line_no > 0:
            lines = content.splitlines()
            if 0 < line_no <= len(lines):
                idx = line_no - 1
                fixed_line = fix_commas_text(fix_em_dash(lines[idx]))
                lines[idx] = fixed_line
                return "\n".join(lines)
        return auto_fix_content(content)
    return content
