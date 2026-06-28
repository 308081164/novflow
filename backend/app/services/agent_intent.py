"""智能体语义理解：用户消息 → 结构化意图，供写作/创书助手两阶段执行。"""
from __future__ import annotations

import json
import re
from typing import Any

from app.models import User
from app.services.agent_constants import (
    APPLY_BOOK_META_KEYWORDS,
    BRAINSTORM_TOPIC_KEYWORDS,
    CHAPTER_EDIT_CONTEXT,
    CHAPTER_SYNC_KEYWORDS,
    CONSISTENCY_SETTING_KEYWORDS,
    EDIT_TEXT_KEYWORDS,
    REFINE_KEYWORDS,
    SYNC_EXPAND_KEYWORDS,
)
from app.services.ai_assist import _chat
from app.services.context_limits import INTENT_CHAPTER_REF_CHARS, INTENT_HISTORY_MSG_CHARS

VALID_WRITE_INTENTS = frozenset(
    {
        "edit_text",
        "show_card",
        "draft_card",
        "apply_book_meta",
        "view_outline",
        "plan_outline",
        "brainstorm",
        "discuss",
        "consistency_check",
        "cross_sync",
        "analyze_only",
        "general",
    }
)

VALID_SETUP_INTENTS = frozenset(
    {
        "guidance",
        "outline",
        "writing",
        "character",
        "brainstorm",
        "draft_card",
        "show_card",
        "general",
    }
)

CHAPTER_RANGE_RE = re.compile(r"第?\s*(\d+)\s*[-~～—至到]\s*(\d+)\s*章?")
CHAPTER_NO_RE = re.compile(r"第\s*(\d+)\s*章")
META_SUMMARY_MARKERS = (
    "主要改动", "改动如下", "修改如下", "润色如下", "调整如下", "变更如下",
    "根据当前写作偏好", "根据写作偏好", "我对第", "以下是对", "改动点", "修改点",
    "各章", "分别如下", "具体如下", "改动摘要", "润色摘要",
)
NEGATIVE_CONSTRAINT_RE = re.compile(
    r"(不要|别|不用|无需|不必|不一定|可以不|能否不|减少|弱化|去掉|别总|别老|别一直|不必强调|不一定非要)"
)
TITLE_IN_MESSAGE_RE = re.compile(r"《([^》]{1,120})》")
PREAMBLE_LINE_PREFIXES = (
    "以下是", "修改后的章节", "根据写作偏好", "根据当前写作偏好", "已根据",
    "已按", "已修正", "已修改", "已删除", "已调整", "已润色", "已更新", "已排查",
    "好的，", "好的,", "润色如下", "正文如下", "**edits**", "edits:",
)
_META_ACTION_START_RE = re.compile(
    r"^已(修正|修改|删除|调整|润色|更新|排查|写入|完成|处理|通读)"
)
_META_OPERATION_PHRASES = (
    "通读全章", "错误引用", "删除该句", "删除该", "依赖该前提",
    "排查所有", "排查类似", "类似问题", "相关表述", "错误前提",
    "改动说明", "修改说明", "写入编辑器", "全文替换",
)
_EDIT_DESC_WORDS = (
    "修正", "修改", "删除", "排查", "引用", "表述", "润色", "调整", "改写", "改动", "错误",
)


def unescape_llm_text(text: str) -> str:
    """将 JSON/模型输出中的字面量转义还原为真实换行等。"""
    if not text:
        return ""
    out = text
    if "\\n" in out or "\\t" in out or '\\"' in out:
        out = out.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')
    return out


def looks_like_json_edit_payload(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    lower = t.lower()
    return (
        t.startswith(("[", "{"))
        or '"chapter_no"' in t
        or '"edits"' in lower
        or "**edits**" in lower
        or re.search(r"^\s*\[\s*\{", t, re.MULTILINE) is not None
        or re.search(r"```(?:json)?\s*\[\s*\{", t) is not None
    )


def _strip_code_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json|markdown|md|text)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```$", "", t).strip()
    return t


def _strip_edit_preamble(text: str) -> str:
    lines = (text or "").split("\n")
    kept: list[str] = []
    for line in lines:
        ls = line.strip()
        if not ls:
            if kept:
                kept.append(line)
            continue
        if ls in ("---", "***"):
            continue
        if any(ls.lower().startswith(p.lower()) for p in PREAMBLE_LINE_PREFIXES):
            continue
        if re.match(r"^#+\s", ls):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def extract_edits_from_messy_text(text: str) -> list[dict]:
    """从混杂 JSON / 说明文字的模型输出中提取 edits。"""
    raw = _strip_code_fences(text or "")
    if not raw:
        return []

    candidates: list[dict] = []

    # 1) 完整 JSON 对象含 edits 键
    if raw.lstrip().startswith("{"):
        blob_start = raw.find("{")
        blob_end = raw.rfind("}")
        if blob_end > blob_start:
            try:
                obj = json.loads(raw[blob_start : blob_end + 1])
                if isinstance(obj, dict) and isinstance(obj.get("edits"), list):
                    candidates.extend(e for e in obj["edits"] if isinstance(e, dict))
            except json.JSONDecodeError:
                pass

    # 2) edits 数组片段
    m_key = re.search(r'"edits"\s*:\s*(\[[\s\S]*?\])\s*[,}]', raw)
    if m_key:
        try:
            arr = json.loads(m_key.group(1))
            if isinstance(arr, list):
                candidates.extend(e for e in arr if isinstance(e, dict))
        except json.JSONDecodeError:
            pass

    # 3) 裸数组 [{ chapter_no, content }]（括号匹配）
    start = raw.find("[{")
    if start >= 0:
        depth = 0
        for i in range(start, len(raw)):
            ch = raw[i]
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    try:
                        arr = json.loads(raw[start : i + 1])
                        if isinstance(arr, list):
                            candidates.extend(e for e in arr if isinstance(e, dict))
                    except json.JSONDecodeError:
                        pass
                    break

    # 4) regex 逐条 salvage content 字段
    if not candidates:
        for m in re.finditer(
            r'"chapter_no"\s*:\s*(\d+)[\s\S]*?"content"\s*:\s*"((?:[^"\\]|\\.)*)"',
            raw,
            re.DOTALL,
        ):
            candidates.append(
                {
                    "chapter_no": int(m.group(1)),
                    "content": unescape_llm_text(m.group(2)),
                }
            )

    out: list[dict] = []
    seen: set[int] = set()
    for e in candidates:
        if not isinstance(e, dict):
            continue
        no = int(e.get("chapter_no") or 0)
        content = sanitize_chapter_edit_content(str(e.get("content") or ""), chapter_no=no)
        if no < 1 or not content or no in seen:
            continue
        seen.add(no)
        out.append(
            {
                "chapter_no": no,
                "title": str(e.get("title") or "").strip() or None,
                "content": content,
                "reason": str(e.get("reason") or "").strip() or "智能体改写",
            }
        )
    return out


def sanitize_chapter_edit_content(content: str, *, chapter_no: int | None = None) -> str:
    """清洗单章正文：去 JSON 包装、转义符、前言说明。"""
    text = unescape_llm_text((content or "").strip())
    if not text:
        return ""

    if looks_like_json_edit_payload(text):
        embedded = extract_edits_from_messy_text(text)
        if embedded:
            if chapter_no is not None:
                for e in embedded:
                    if int(e.get("chapter_no") or 0) == chapter_no:
                        return str(e.get("content") or "").strip()
                return ""
            if len(embedded) == 1:
                return str(embedded[0].get("content") or "").strip()
            return ""

    text = _strip_code_fences(text)
    text = _strip_edit_preamble(text)
    text = unescape_llm_text(text)

    if looks_like_json_edit_payload(text):
        return ""

    if is_meta_summary_content(text):
        return ""

    return text.strip()


def extract_title_from_message(message: str) -> str | None:
    m = TITLE_IN_MESSAGE_RE.search(message or "")
    return m.group(1).strip() if m else None


def parse_target_chapter_nos(message: str, fallback_chapter_no: int) -> list[int]:
    """从用户消息解析目标章节号；无法解析时回退为当前聚焦章。"""
    msg = (message or "").strip()
    nums: list[int] = []

    m = CHAPTER_RANGE_RE.search(msg)
    if m:
        start, end = int(m.group(1)), int(m.group(2))
        if start > end:
            start, end = end, start
        nums = list(range(start, end + 1))

    if not nums:
        found = [int(x) for x in CHAPTER_NO_RE.findall(msg)]
        if len(found) >= 2:
            nums = sorted(set(found))
        elif len(found) == 1 and any(k in msg for k in ("润色", "修改", "改写", "补全", "优化", "扩写")):
            nums = found

    if not nums and fallback_chapter_no > 0:
        if any(k in msg for k in ("本章", "这章", "当前章", "这一章")) or "【选段" in msg:
            nums = [fallback_chapter_no]
        elif is_edit_text_message(msg) and not re.search(r"第\s*\d+", msg):
            nums = [fallback_chapter_no]

    if not nums and fallback_chapter_no > 0:
        nums = [fallback_chapter_no]

    return nums[:15]



def diagnose_edit_failure(body: str, original_content: str, chapter_no: int = 0) -> str:
    """诊断章节改写失败原因，供逐章报告展示。"""
    text = (body or "").strip()
    if not text:
        return "模型返回空内容"
    if is_meta_summary_content(text):
        return "模型返回改动说明/分析，非完整正文"
    orig = (original_content or "").strip()
    if orig and not is_valid_chapter_edit_content(text, chapter_no=chapter_no, original_content=orig):
        need = max(200, int(len(orig) * 0.18)) if len(orig) >= 500 else max(80, int(len(orig) * 0.12))
        return f"正文过短（{len(text)} 字，需约 ≥{need} 字）"
    return "正文校验未通过"


def is_meta_summary_content(content: str) -> bool:
    """判断文本是否为改动说明/摘要，而非章节正文。"""
    t = (content or "").strip()
    if not t:
        return True
    chapter_headers = len(re.findall(r"第\s*\d+\s*章[：:]", t))
    chapter_mentions = len(re.findall(r"第\s*\d+\s*章", t))
    if chapter_headers >= 2:
        return True
    marker_hits = sum(1 for m in META_SUMMARY_MARKERS if m in t)
    if marker_hits >= 2:
        return True
    if chapter_headers >= 1 and marker_hits >= 1:
        return True
    if t.startswith(("好的，", "好的,", "OK，", "根据")) and re.search(r"第\s*\d+\s*章", t):
        if any(k in t for k in ("改动", "润色", "修改", "调整", "偏好")):
            return True
    # 列表式摘要：多行以 - **第 开头
    bullet_chapters = len(re.findall(r"^[\-*•]\s*\*?\*?第\s*\d+\s*章", t, re.MULTILINE))
    if bullet_chapters >= 2:
        return True
    # 操作型摘要：「已修正第2章…删除该句…通读全章…」
    if _META_ACTION_START_RE.match(t) and chapter_mentions >= 1:
        return True
    meta_op_hits = sum(1 for p in _META_OPERATION_PHRASES if p in t)
    if meta_op_hits >= 2:
        return True
    if meta_op_hits >= 1 and chapter_mentions >= 1 and len(t) < 900:
        return True
    if len(t) < 500 and chapter_mentions >= 1:
        desc_hits = sum(1 for w in _EDIT_DESC_WORDS if w in t)
        if desc_hits >= 2:
            return True
    # 极短且无叙事特征（无对话、几乎无换行）
    if len(t) < 350 and t.count("\n") <= 1 and "「" not in t and "《" not in t:
        if chapter_mentions >= 1 and any(w in t for w in ("已", "删除", "修正", "排查")):
            return True
        if meta_op_hits >= 1:
            return True
    return False


SELECTION_HEADER_RE = re.compile(r"【选段[^】]*第\s*(\d+)\s*章")


def parse_selection_from_message(message: str) -> tuple[int | None, str]:
    """从【选段·第N章】消息中解析章号与引用正文。"""
    msg = (message or "").strip()
    chapter_no: int | None = None
    m = SELECTION_HEADER_RE.search(msg)
    if m:
        chapter_no = int(m.group(1))

    quote_lines: list[str] = []
    in_block = False
    for line in msg.splitlines():
        if "【选段" in line:
            in_block = True
            continue
        if not in_block:
            continue
        stripped = line.strip()
        if stripped.startswith(">"):
            quote_lines.append(stripped.lstrip(">").strip())
        elif quote_lines and stripped and not stripped.startswith(">"):
            break
    quote = "\n".join(quote_lines).strip()
    return chapter_no, quote


def _flex_find_span(text: str, needle: str) -> tuple[int, int] | None:
    """在正文中定位选段（允许空白差异）。"""
    if not text or not needle:
        return None
    if needle in text:
        start = text.index(needle)
        return start, start + len(needle)

    needle_lines = [ln.strip() for ln in needle.splitlines() if ln.strip()]
    if not needle_lines:
        return None
    text_lines = text.splitlines(keepends=True)
    line_starts: list[int] = []
    pos = 0
    for ln in text_lines:
        line_starts.append(pos)
        pos += len(ln)

    for start_idx in range(len(text_lines)):
        ok = True
        for j, nl in enumerate(needle_lines):
            li = start_idx + j
            if li >= len(text_lines):
                ok = False
                break
            tl = text_lines[li].strip()
            if nl not in tl and tl != nl:
                ok = False
                break
        if not ok:
            continue
        start = line_starts[start_idx]
        end_line = start_idx + len(needle_lines) - 1
        end = line_starts[end_line] + len(text_lines[end_line])
        return start, end
    return None


def merge_selection_into_chapter(original: str, selection: str, candidate: str) -> str | None:
    """将模型返回的选段修正合并回整章；若已是整章则直接返回。"""
    orig = (original or "").strip()
    sel = (selection or "").strip()
    cand = (candidate or "").strip()
    if not orig or not cand or is_meta_summary_content(cand):
        return None

    if len(cand) >= max(int(len(orig) * 0.45), 120):
        return cand

    if not sel:
        return None

    span = _flex_find_span(orig, sel)
    if not span:
        return None
    start, end = span
    merged = orig[:start] + cand + orig[end:]
    if len(merged) < max(int(len(orig) * 0.35), 40):
        return None
    if is_meta_summary_content(merged):
        return None
    return merged


def finalize_chapter_edit_content(
    content: str,
    *,
    chapter_no: int | None = None,
    original_content: str = "",
    edit_scope: str = "chapter",
    selection_quote: str = "",
) -> str | None:
    """清洗并校验章节正文；选段模式支持将短回复合并回整章。"""
    text = sanitize_chapter_edit_content(content, chapter_no=chapter_no)
    if not text or is_meta_summary_content(text):
        return None

    orig = (original_content or "").strip()
    scope = (edit_scope or "chapter").strip()
    sel = (selection_quote or "").strip()

    if scope == "selection" and sel and orig:
        merged = merge_selection_into_chapter(orig, sel, text)
        if merged:
            text = merged
        elif not is_valid_chapter_edit_content(text, chapter_no=chapter_no, original_content=orig):
            return None
    elif not is_valid_chapter_edit_content(text, chapter_no=chapter_no, original_content=orig):
        return None

    if is_meta_summary_content(text):
        return None
    return text.strip()


def edit_failure_reply(
    *,
    edit_scope: str = "chapter",
    target_chapter_nos: list[int] | None = None,
) -> str:
    """按场景返回更准确的失败说明。"""
    nos = [n for n in (target_chapter_nos or []) if n > 0]
    if edit_scope == "selection":
        ch = f"第{nos[0]}章" if len(nos) == 1 else "目标章节"
        return (
            f"选段修改失败：未能生成可写入的{ch}完整正文（模型可能只返回了改动说明或仅返回选段）。"
            "正文未被修改，请重试或改为描述具体修改要求。"
        )
    if len(nos) > 3:
        return (
            f"多章润色（第 {', '.join(str(n) for n in nos)} 章）未能全部完成。"
            "建议逐章发送（如「先润色第2章」），或一次最多 3 章。正文未被修改。"
        )
    if len(nos) > 1:
        return (
            f"未能生成第 {', '.join(str(n) for n in nos)} 章的有效正文。"
            "可尝试逐章润色。正文未被修改。"
        )
    return "未能生成有效章节正文（模型可能只返回了改动说明）。正文未被修改，请重试。"


def is_valid_chapter_edit_content(
    content: str,
    *,
    chapter_no: int | None = None,
    original_content: str = "",
) -> bool:
    """校验是否为可写入编辑器的完整章节正文（非改动说明、非异常短替换）。"""
    text = sanitize_chapter_edit_content(content, chapter_no=chapter_no)
    if not text or is_meta_summary_content(text):
        return False

    orig = (original_content or "").strip()
    new_len = len(text)

    if orig:
        orig_len = len(orig)
        if orig_len >= 500:
            if new_len < max(200, int(orig_len * 0.18)):
                return False
        elif orig_len >= 120:
            if new_len < max(80, int(orig_len * 0.12)):
                return False
        elif orig_len >= 40:
            if new_len < max(35, int(orig_len * 0.45)):
                return False
    elif new_len < 30:
        return False

    return True


def reply_implies_edit_success(reply: str) -> bool:
    """reply 是否声称已完成正文写入（需与 applied 对照校验）。"""
    t = (reply or "").strip()
    if not t:
        return False
    phrases = (
        "已修改", "已写入", "已更新", "已修正", "已调整", "已润色", "已同步",
        "写入编辑器", "修改后完整正文", "修改后的完整正文", "以下是修改",
        "以下是第", "已按你的要求", "已完成修改", "完成全部修改", "并写入编辑器",
    )
    return any(p in t for p in phrases)


_CHAPTER_SECTION_HEAD_RE = re.compile(
    r"^(?:#+\s*)?(?:\*\*)?(?:第\s*0*(\d+)\s*章)[^\n]*(?:\*\*)?\s*$",
    re.MULTILINE,
)


def _strip_reply_wrapper(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:markdown|md|text|json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    lines = t.split("\n")
    while lines and any(lines[0].strip().startswith(p) for p in PREAMBLE_LINE_PREFIXES):
        lines.pop(0)
    return "\n".join(lines).strip()


def split_reply_by_chapter_sections(text: str) -> list[tuple[int, str]]:
    """从 reply 中按「第 N 章」标题拆分为多章正文块。"""
    raw = _strip_reply_wrapper(text or "")
    if not raw.strip():
        return []
    matches = list(_CHAPTER_SECTION_HEAD_RE.finditer(raw))
    if not matches:
        return []
    out: list[tuple[int, str]] = []
    for i, m in enumerate(matches):
        no = int(m.group(1))
        header = raw[m.start() : m.end()].strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        body = raw[body_start:body_end].strip()
        if header.startswith("#"):
            content = f"{header}\n\n{body}".strip() if body else header
        else:
            content = body
        if content:
            out.append((no, content))
    return out


def salvage_edits_from_chapter_sections(
    reply: str,
    target_chapter_nos: list[int],
    chapter_contents: dict[int, str] | None,
    edit_context: dict[str, Any] | None = None,
) -> list[dict]:
    """从 reply 的多章分节中回收 edits。"""
    allowed = set(n for n in (target_chapter_nos or []) if n > 0)
    ctx = edit_context or {}
    contents = chapter_contents or {}
    edits: list[dict] = []
    for no, section in split_reply_by_chapter_sections(reply):
        if allowed and no not in allowed:
            continue
        orig = (contents.get(no) or "").strip()
        finalized = finalize_chapter_edit_content(
            section,
            chapter_no=no,
            original_content=orig,
            edit_scope=str(ctx.get("edit_scope") or "chapter"),
            selection_quote=str(ctx.get("selection_quote") or "") if no in allowed else "",
        )
        if not finalized:
            continue
        if orig and finalized.strip() == orig:
            continue
        edits.append({"chapter_no": no, "content": finalized, "reason": "从 reply 分节回收正文"})
    return edits


def is_edit_text_message(message: str) -> bool:
    msg = (message or "").strip()
    if "【选段" in msg:
        return True
    # 多资源设定对照（大纲+角色卡等）不应走正文改写
    try:
        from app.services.task_planner import is_multi_resource_analysis_message

        if is_multi_resource_analysis_message(msg):
            return False
    except ImportError:
        pass
    if any(k in msg for k in CONSISTENCY_SETTING_KEYWORDS):
        if not any(k in msg for k in ("正文", "润色", "改写本章", "修改本章")):
            return False
    if any(k in msg for k in EDIT_TEXT_KEYWORDS):
        if "书名" in msg or is_apply_book_meta_message(msg):
            return False
        return True
    if any(k in msg for k in CHAPTER_SYNC_KEYWORDS) or (
        any(k in msg for k in SYNC_EXPAND_KEYWORDS) and any(k in msg for k in CHAPTER_EDIT_CONTEXT)
    ):
        if "书名" in msg:
            return False
        return True
    if any(k in msg for k in CHAPTER_EDIT_CONTEXT) and any(
        k in msg for k in ("改", "修", "润", "补", "写", "优化", "调整", "删")
    ):
        return True
    return False


def is_apply_book_meta_message(message: str) -> bool:
    msg = (message or "").strip()
    if any(k in msg for k in APPLY_BOOK_META_KEYWORDS):
        return True
    if "书名" in msg and any(k in msg for k in ("采纳", "确认", "就这样", "就用", "用这个", "确定", "可以", "帮忙", "帮我")):
        return True
    if extract_title_from_message(msg) and any(
        k in msg for k in ("就用", "用这个", "确定", "采纳", "确认", "更改", "改成", "改为", "帮忙", "帮我")
    ):
        return True
    return False


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def salvage_reply_from_raw(raw: str) -> str:
    """从损坏的 JSON 或纯文本中尽量提取 reply 正文。"""
    text = (raw or "").strip()
    if not text:
        return ""
    if not text.startswith("{"):
        return text[:8000]
    m = re.search(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
    if m:
        return m.group(1).replace("\\n", "\n").replace('\\"', '"').replace("\\t", "\t").strip()
    blob = _extract_json_object(text)
    if blob and blob.get("reply"):
        return str(blob["reply"]).strip()
    cleaned = re.sub(r"^\s*\{[\s\S]*", "", text).strip()
    return cleaned[:8000] if cleaned else ""


def _infer_history_context(history: list[dict]) -> dict[str, Any]:
    """从最近对话推断延续话题。"""
    topic = "other"
    was_brainstorm = False
    last_user = ""
    last_assistant = ""
    for h in reversed(history[-10:]):
        role = h.get("role")
        content = str(h.get("content") or "").strip()
        if not content:
            continue
        if role == "assistant" and not last_assistant:
            last_assistant = content
        if role == "user" and not last_user:
            last_user = content
        if role == "assistant":
            if "《" in content and re.search(r"^\s*\d+[\.、．]", content, re.MULTILINE):
                was_brainstorm = True
                topic = topic if topic != "other" else "book_title"
            if any(k in content for k in ("书名", "候选", "如下", "推荐")) and "《" in content:
                was_brainstorm = True
                topic = "book_title"
        if role == "user":
            for t, kws in BRAINSTORM_TOPIC_KEYWORDS.items():
                if any(k in content for k in kws):
                    was_brainstorm = True
                    topic = t
                    break
        if was_brainstorm and topic != "other":
            break
    return {
        "topic": topic,
        "was_brainstorm": was_brainstorm,
        "last_user": last_user,
        "last_assistant_preview": last_assistant[:400],
    }


def _extract_constraints(message: str) -> tuple[list[str], list[str]]:
    """从用户句中提取 must_do / must_not_do。"""
    msg = message.strip()
    must_not: list[str] = []
    must_do: list[str] = []
    if NEGATIVE_CONSTRAINT_RE.search(msg):
        must_not.append(f"遵守用户约束：{msg}")
    if "搞笑" in msg or "反差" in msg or "槽" in msg:
        must_do.append("突出搞笑感与反差感")
    if any(k in msg for k in ("能力等级", "D级", "S级", "等级")) and NEGATIVE_CONSTRAINT_RE.search(msg):
        must_not.append("不要在输出中强调 D级/S级/能力等级对比")
        must_do.append("在不强调等级的前提下重新给出候选")
    if "再" in msg or "继续" in msg or "还有" in msg:
        must_do.append("在 reply 正文中直接列出完整新候选（编号列表）")
    return must_do, must_not


def _rule_write_intent(message: str, history: list[dict] | None = None) -> dict[str, Any]:
    msg = message.strip()
    ctx = _infer_history_context(history or [])
    must_do, must_not = _extract_constraints(msg)

    # 确认采用书名/简介 — 优先于 brainstorm 延续
    if is_apply_book_meta_message(msg):
        title = extract_title_from_message(msg)
        intent = _write_intent(
            "apply_book_meta",
            "book_meta",
            allow_cards=True,
            summary=f"写入书名：{title}" if title else "更新作品信息",
            must_do=[
                "必须输出 premise 卡片并把 id 放入 apply_card_ids 写入数据库"
                if not title
                else "书名将由系统自动写入，reply 确认即可"
            ],
        )
        intent["extracted_title"] = title or ""
        intent["auto_apply"] = bool(title)
        return intent

    # 延续上一轮 brainstorm 的短句 refinement
    is_refine = any(k in msg for k in REFINE_KEYWORDS) or len(msg) <= 24
    if ctx["was_brainstorm"] and (is_refine or ctx["topic"] != "other"):
        summary = msg if len(msg) > 8 else f"延续{ctx['topic']}讨论：{msg}"
        return _write_intent(
            "brainstorm",
            ctx["topic"],
            is_follow_up=True,
            summary=summary,
            must_do=must_do or ["在 reply 正文中直接列出完整候选（编号列表）"],
            must_not_do=must_not or ["不要输出 actions 跳转按钮", "不要输出 cards"],
        )

    # 多资源一致性/对照（大纲+角色卡等）— 优先于正文改写
    try:
        from app.services.task_planner import is_multi_resource_analysis_message

        if is_multi_resource_analysis_message(msg):
            has_apply = any(k in msg for k in ("采纳", "确认", "应用", "写入设定", "保存设定", "就用"))
            has_sync = any(k in msg for k in ("统一", "同步", "对齐", "修正设定"))
            intent_name = "cross_sync" if has_apply or (has_sync and "正文" not in msg) else "consistency_check"
            resources_hint = "大纲与角色卡"
            return _write_intent(
                intent_name,
                "outline",
                allow_cards=True,
                summary=msg[:200] or f"对照{resources_hint}并{'统一' if has_sync else '分析冲突'}",
                must_do=[
                    "先加载大纲与角色卡全文并对照",
                    "在 reply 中列出冲突清单与建议修正",
                    "用 cards 输出修正草案（character/outline），禁止直接 edits 改正文",
                ],
                must_not_do=[
                    "禁止跳过分析直接改写第1章或任意章节正文",
                    "禁止在未分析时输出 edits",
                ],
            )
    except ImportError:
        pass

    if "【选段" in msg:
        sel_ch, sel_quote = parse_selection_from_message(msg)
        must_do_sel = [
            "只修改用户选中的段落，其余正文保持原样",
            "edits[].content 必须是整章完整正文（含未改部分），禁止只输出选段",
            "reply 仅 1～2 句说明",
        ]
        if sel_quote:
            must_do_sel.append(f"选段原文：{sel_quote[:280]}")
        if "违规" in msg or "写作规约" in msg or "不符合" in msg:
            must_do_sel.append("按本书写作规约修正选段表述，保持情节不变")
        intent = _write_intent(
            "edit_text",
            "chapter",
            allow_edits=True,
            summary="修改选段正文并符合写作规约",
            must_do=must_do_sel,
            must_not_do=[
                "禁止把改动说明/摘要当作正文",
                "禁止只返回选段而不返回整章",
                "禁止输出 cards 或 actions",
            ],
        )
        intent["edit_scope"] = "selection"
        intent["selection_quote"] = sel_quote
        intent["target_chapter_nos"] = [sel_ch] if sel_ch else []
        return intent
    if is_edit_text_message(msg):
        target_nos = parse_target_chapter_nos(msg, 0)
        summary = msg[:200]
        must_do = [
            "edits 中每条必须含正确 chapter_no 与完整修改后正文 content",
            "reply 仅简短说明，禁止把改动摘要或全文放入 reply",
        ]
        if len(target_nos) > 1:
            must_do.insert(0, f"分别修改第 {target_nos} 章，系统将逐章独立生成并写入")
            if len(target_nos) > 5:
                must_do.insert(
                    1,
                    f"共 {len(target_nos)} 章将分批：本次先处理第 {', '.join(str(n) for n in target_nos[:5])} 章",
                )
        elif target_nos:
            must_do.insert(0, f"修改第 {target_nos[0]} 章")
        intent = _write_intent(
            "edit_text",
            "chapter",
            allow_edits=True,
            summary=summary,
            must_do=must_do,
            must_not_do=[
                "禁止把改动说明/摘要当作正文写入",
                "禁止写入用户未指定的章节",
                "禁止编造前文未发生的情节或人物状态",
            ],
        )
        intent["target_chapter_nos"] = target_nos
        intent["edit_scope"] = "multi_chapter" if len(target_nos) > 1 else "chapter"
        return intent
    if any(k in msg for k in ("润色", "重写", "扩写", "改正文", "修改正文", "衔接")) and "书名" not in msg:
        return _write_intent("edit_text", "chapter", allow_edits=True)
    if any(k in msg for k in ("查看章节大纲", "看大纲", "调出大纲", "展示大纲")):
        return _write_intent("view_outline", "outline", allow_actions=True, action_types=["open_outline"])
    if any(k in msg for k in ("规划", "添加", "补充")) and any(k in msg for k in ("大纲", "章节")):
        return _write_intent("plan_outline", "outline", allow_cards=True)
    if any(k in msg for k in ("调出", "展示", "查看", "给我看", "显示", "列出")):
        if any(k in msg for k in ("角色", "人物", "男主", "女主")):
            return _write_intent("show_card", "character", allow_cards=True)
        if any(k in msg for k in ("世界观", "设定")) and "书名" not in msg:
            return _write_intent("show_card", "worldview", allow_cards=True)
        if any(k in msg for k in ("写作偏好", "写作规约", "本书偏好")):
            return _write_intent("show_card", "writing_prefs", allow_cards=True)
        if any(k in msg for k in ("大纲", "章节规划")):
            return _write_intent("view_outline", "outline", allow_actions=True, action_types=["open_outline"])
        if any(k in msg for k in ("书名", "简介", "作品", "定位")) and not any(k in msg for k in REFINE_KEYWORDS):
            return _write_intent("show_card", "premise", allow_cards=True)
    if any(k in msg for k in ("书名", "取名", "起名", "标题", "再取", "再来几个", "几个名", "搞笑", "反差")):
        return _write_intent(
            "brainstorm",
            "book_title",
            must_do=must_do or ["在 reply 正文中直接列出完整候选内容"],
            must_not_do=must_not or ["不要输出 actions 跳转按钮", "不要输出 cards 除非用户明确说采纳"],
        )
    # 延续一致性分析后的「开始执行 / 确认采纳」— 必须优先于通用「采纳/确认」draft_card 规则
    try:
        from app.services.write_task_executor import is_execute_plan_message, was_consistency_analysis_context

        if was_consistency_analysis_context(
            history or [],
            last_assistant_preview=ctx.get("last_assistant_preview") or "",
        ) and is_execute_plan_message(msg):
            intent = _write_intent(
                "cross_sync",
                "outline",
                allow_cards=True,
                allow_edits=True,
                is_follow_up=True,
                summary="执行上一轮一致性分析方案（写入设定并修正正文）",
                must_do=[
                    "必须应用上一轮草案 character/outline 卡片到数据库",
                    "必须对分析中涉及的章节正文执行实际修改并写入",
                ],
                must_not_do=["禁止只口头描述已完成而未写入数据库"],
            )
            intent["auto_apply"] = True
            intent["execute_prior_plan"] = True
            intent["allow_edits"] = True
            return intent
    except ImportError:
        pass

    if any(k in msg for k in ("采纳", "确认", "就这样", "保存设定", "应用")):
        return _write_intent("draft_card", "other", allow_cards=True)

    if any(k in msg for k in ("改书名", "改简介", "修改简介", "更新书名")):
        return _write_intent("draft_card", "book_meta", allow_cards=True)

    if ctx["was_brainstorm"]:
        return _write_intent(
            "brainstorm",
            ctx["topic"],
            is_follow_up=True,
            summary=msg,
            must_do=must_do or ["在 reply 正文中直接列出完整候选"],
            must_not_do=must_not,
        )
    return _write_intent("discuss", "other", summary=msg[:200])


def _write_intent(
    intent: str,
    topic: str,
    *,
    allow_cards: bool = False,
    allow_edits: bool = False,
    allow_actions: bool = False,
    action_types: list[str] | None = None,
    must_do: list[str] | None = None,
    must_not_do: list[str] | None = None,
    is_follow_up: bool = False,
    summary: str = "",
) -> dict[str, Any]:
    if intent == "brainstorm":
        allow_cards = False
        allow_actions = False
        allow_edits = False
    elif intent in ("consistency_check", "analyze_only"):
        allow_cards = True
        allow_actions = False
        allow_edits = False
    elif intent == "cross_sync":
        allow_cards = True
        allow_actions = False
        allow_edits = False
    elif intent in ("show_card", "draft_card", "apply_book_meta"):
        allow_cards = True
    elif intent == "edit_text":
        allow_edits = True
    elif intent == "view_outline":
        allow_actions = True
        action_types = action_types or ["open_outline"]
    elif intent == "plan_outline":
        allow_cards = True
    return {
        "intent": intent,
        "topic": topic,
        "is_follow_up": is_follow_up,
        "summary": summary or "",
        "must_do": must_do or [],
        "must_not_do": must_not_do or [],
        "allow_cards": allow_cards,
        "allow_edits": allow_edits,
        "allow_actions": allow_actions,
        "action_types": action_types or [],
    }


def _merge_write_understanding(llm: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any]:
    """LLM 与规则引擎合并：规则在 follow-up/refinement 场景优先。"""
    merged = dict(rule)
    if rule.get("execute_prior_plan"):
        merged["intent"] = "cross_sync"
        merged["execute_prior_plan"] = True
        merged["auto_apply"] = True
        merged["allow_edits"] = True
        merged["allow_cards"] = True
        merged["topic"] = rule.get("topic") or "outline"
        if llm.get("summary"):
            merged["summary"] = llm["summary"]
        merged["must_do"] = list(dict.fromkeys((merged.get("must_do") or []) + (rule.get("must_do") or [])))[:8]
        merged["must_not_do"] = list(dict.fromkeys((merged.get("must_not_do") or []) + (rule.get("must_not_do") or [])))[:8]
        return merged
    if llm.get("summary"):
        merged["summary"] = llm["summary"]
    if llm.get("must_do"):
        merged["must_do"] = list(dict.fromkeys((merged.get("must_do") or []) + llm["must_do"]))[:8]
    if llm.get("must_not_do"):
        merged["must_not_do"] = list(dict.fromkeys((merged.get("must_not_do") or []) + llm["must_not_do"]))[:8]

    if rule.get("intent") == "apply_book_meta":
        merged["intent"] = "apply_book_meta"
        merged["topic"] = "book_meta"
        merged["allow_cards"] = True
        merged["extracted_title"] = rule.get("extracted_title") or extract_title_from_message(str(rule.get("summary") or "")) or ""
        merged["auto_apply"] = bool(merged.get("extracted_title"))
        return merged

    if rule.get("intent") in ("consistency_check", "cross_sync", "analyze_only"):
        merged["intent"] = rule["intent"]
        merged["topic"] = rule.get("topic") or "outline"
        if rule.get("execute_prior_plan"):
            merged["execute_prior_plan"] = True
            merged["auto_apply"] = True
            merged["allow_edits"] = True
        else:
            merged["allow_edits"] = False
        merged["allow_cards"] = True
        merged["allow_actions"] = False
        merged["must_do"] = list(dict.fromkeys((merged.get("must_do") or []) + (rule.get("must_do") or [])))[:8]
        merged["must_not_do"] = list(dict.fromkeys((merged.get("must_not_do") or []) + (rule.get("must_not_do") or [])))[:8]
        return merged

    if rule.get("intent") == "edit_text":
        merged["intent"] = "edit_text"
        merged["topic"] = "chapter"
        merged["allow_edits"] = True
        merged["allow_cards"] = False
        merged["allow_actions"] = False
        merged["target_chapter_nos"] = rule.get("target_chapter_nos") or merged.get("target_chapter_nos") or []
        if rule.get("edit_scope"):
            merged["edit_scope"] = rule["edit_scope"]
        if rule.get("selection_quote"):
            merged["selection_quote"] = rule["selection_quote"]
        return merged

    # 规则判定为 brainstorm 延续时，不被 LLM 误判为 discuss/show_card 覆盖
    if rule.get("intent") == "brainstorm" and rule.get("is_follow_up"):
        merged["intent"] = "brainstorm"
        merged["topic"] = rule.get("topic") or llm.get("topic") or "other"
        merged["is_follow_up"] = True
        merged["allow_cards"] = False
        merged["allow_actions"] = False
        merged["allow_edits"] = False
        return merged

    intent = str(llm.get("intent") or rule["intent"])
    if intent in VALID_WRITE_INTENTS:
        merged["intent"] = intent
    if llm.get("topic"):
        merged["topic"] = llm["topic"]
    merged["is_follow_up"] = bool(llm.get("is_follow_up")) or bool(rule.get("is_follow_up"))
    if llm.get("intent") in ("show_card", "draft_card", "apply_book_meta", "plan_outline", "view_outline", "edit_text"):
        merged["allow_cards"] = bool(llm.get("allow_cards"))
        merged["allow_edits"] = bool(llm.get("allow_edits"))
        merged["allow_actions"] = bool(llm.get("allow_actions"))
    return merged


async def understand_write_message(
    user: User,
    message: str,
    history: list[dict],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """阶段一：理解写作智能体用户意图。"""
    rule = _rule_write_intent(message, history)
    ctx = _infer_history_context(history)

    system = """你是 NovFlow 写作智能体的「语义理解模块」。只输出 JSON，不执行任务。
必须结合**完整对话历史**理解用户最新消息——很多短句是对上一轮的修正/约束（如「不一定非要强调能力等级」= 延续书名讨论，要求去掉等级强调）。

{
  "intent": "edit_text|show_card|draft_card|apply_book_meta|view_outline|plan_outline|brainstorm|discuss|consistency_check|cross_sync|analyze_only|general",
  "topic": "chapter|book_title|book_meta|character|worldview|outline|writing_prefs|plot|other",
  "affected_resources": ["outline", "characters", "chapters", "writing_prefs", "worldview"],
  "is_follow_up": true/false,
  "summary": "用户真正要什么（含约束条件）",
  "edit_scope": "chapter|selection|multi_chapter|none",
  "target_chapter_nos": [2, 3],
  "must_do": [],
  "must_not_do": [],
  "allow_cards": false,
  "allow_edits": false,
  "allow_actions": false,
  "action_types": []
}

关键：
- 「检查/对比/冲突/统一 大纲与角色卡」且未明确要求改正文 → consistency_check 或 cross_sync（含「统一/应用/采纳」→ cross_sync）
- consistency_check / cross_sync：allow_edits=false，allow_cards=true；禁止误判为 edit_text
- 「【选段·第N章】」或带引用块 → edit_text + edit_scope=selection，target_chapter_nos=[N]
- 「润色第2-5章/2到5章」→ edit_text + edit_scope=multi_chapter，target_chapter_nos=[2,3,4,5]
- 「不符合写作规约/请修复选段」→ edit_text + selection，must_do 含遵守写作规约
- 「不一定/不用/别/不要/无需 + 某要求」→ 几乎总是 is_follow_up=true，延续上一轮 brainstorm
- 「《书名》就用这个/帮我更改书名」→ apply_book_meta，extracted_title 填书名
- 用户在 refine 书名/创意时 intent=brainstorm，allow_cards=false，allow_actions=false
- 「查看/调出」才是 show_card；讨论/修改/评价创意不是 show_card
- must_not_do 要写清用户否定项（如：不要强调能力等级）
- 结合 snapshot 中的 book_index_hint 推断章范围：用户未写「第N章」的短句改文请求 → edit_text + target_chapter_nos=[当前聚焦章]"""
    msgs: list[dict] = [{"role": "system", "content": system}]
    for h in history[-10:]:
        role = h.get("role")
        content = str(h.get("content") or "").strip()[:INTENT_HISTORY_MSG_CHARS]
        if role in ("user", "assistant") and content:
            msgs.append({"role": role, "content": content})
    ctx_line = (
        f"当前书名：{snapshot.get('title')}\n"
        f"当前聚焦：第 {snapshot.get('current_chapter_no')} 章\n"
        f"书籍索引：{snapshot.get('book_index_hint') or '（无）'}\n"
        f"历史推断：was_brainstorm={ctx['was_brainstorm']}, topic={ctx['topic']}\n"
        f"用户最新消息：{message.strip()}"
    )
    msgs.append({"role": "user", "content": ctx_line})

    try:
        raw = await _chat(user, msgs, temperature=0.1, max_tokens=1500, json_object=True)
        data = _extract_json_object(raw)
        if not data:
            return rule
        llm = {
            "intent": str(data.get("intent") or rule["intent"]),
            "topic": str(data.get("topic") or rule["topic"]),
            "is_follow_up": bool(data.get("is_follow_up")),
            "summary": str(data.get("summary") or rule.get("summary") or message.strip()[:200]),
            "edit_scope": str(data.get("edit_scope") or rule.get("edit_scope") or ""),
            "target_chapter_nos": [
                int(x) for x in (data.get("target_chapter_nos") or rule.get("target_chapter_nos") or []) if x
            ],
            "must_do": [str(x) for x in (data.get("must_do") or []) if x][:6],
            "must_not_do": [str(x) for x in (data.get("must_not_do") or []) if x][:6],
            "allow_cards": bool(data.get("allow_cards")),
            "allow_edits": bool(data.get("allow_edits")),
            "allow_actions": bool(data.get("allow_actions")),
            "action_types": [str(x) for x in (data.get("action_types") or []) if x],
        }
        if llm.get("edit_scope") == "selection" and not llm.get("target_chapter_nos"):
            ch, _ = parse_selection_from_message(message)
            if ch:
                llm["target_chapter_nos"] = [ch]
        return _merge_write_understanding(llm, rule)
    except Exception:
        return rule


def write_execution_hint(understanding: dict[str, Any], message: str) -> str:
    """阶段二：将语义理解结果注入执行提示。"""
    intent = understanding.get("intent", "general")
    lines = [
        "## 【语义理解 · 本轮必须先遵守】",
        f"- 用户意图：{intent}（主题：{understanding.get('topic', 'other')}）",
        f"- 需求摘要：{understanding.get('summary') or message.strip()[:300]}",
    ]
    if understanding.get("is_follow_up"):
        lines.append("- 这是对上一轮话题的**延续/修正**，必须承接上文约束，禁止另起炉灶或答非所问。")
    for item in understanding.get("must_do") or []:
        lines.append(f"- 必须：{item}")
    for item in understanding.get("must_not_do") or []:
        lines.append(f"- 禁止：{item}")

    if intent == "brainstorm":
        lines += [
            "- 头脑风暴：把所有候选**完整写进 reply 正文**（编号列表，每条一行）。",
            "- 禁止空口说「如下」却不列出；禁止 JSON 外泄露；cards=[]，actions=[]。",
            "- 若用户否定某元素（如等级对比），新候选必须避开该元素。",
        ]
    elif intent == "edit_text":
        target_nos = understanding.get("target_chapter_nos") or []
        edit_scope = understanding.get("edit_scope") or "chapter"
        if target_nos:
            lines.append(f"- 目标章节：第 {', '.join(str(n) for n in target_nos)} 章（必须逐章输出 edits，chapter_no 不得错）。")
        if edit_scope == "selection":
            sel = str(understanding.get("selection_quote") or "").strip()
            lines += [
                "- **选段修改**：用户只要求改选中段落，但必须输出**整章完整正文**（未改部分原样保留）。",
                f"- 选段原文：{sel[:400]}" if sel else "- 选段原文见用户消息中的引用块。",
                "- 若用户提到「写作规约/不符合规约」，按本书写作偏好修正选段表述。",
            ]
        elif edit_scope == "multi_chapter":
            lines += [
                "- **多章修改**：系统将逐章独立处理（每章一次完整生成并写入），单次最多 5 章。",
                "- 你无需在一条 reply 里塞多章正文；本轮若有多章，后端会自动逐章执行。",
            ]
        lines += [
            "- 正文修改：**必须**在 edits 数组写入完整修改后正文（edits[].content 为各章全文）。",
            "- reply 仅 1～3 句说明改了什么；**禁止**把改动摘要、分章说明或全文放在 reply。",
            "- **情节连续**：修改必须与前文、本章已有正文一致；不得添加前文未发生的动作/后果。",
            "- 用户纠正「前文没有X」时，删除或改写所有依赖 X 的句子，并检查全章类似问题。",
            "- cards、actions、apply_card_ids 必须为空数组。",
        ]
    elif intent == "show_card":
        lines += ["- 查看设定：输出 cards（status=applied）；actions 为空。"]
    elif intent == "draft_card":
        lines += ["- 设定草案：输出 cards（status=draft）。"]
    elif intent == "apply_book_meta":
        lines += [
            "- 用户确认采用书名/简介：必须输出 premise 卡片（data.title 等），并把 card id 放入 apply_card_ids。",
            "- 禁止只口头说「已更新」却不输出 cards + apply_card_ids。",
        ]
    elif intent == "view_outline":
        lines += ["- 查看大纲：actions 仅 open_outline；禁止 outline 卡片。"]
    elif intent == "plan_outline":
        lines += ["- 规划大纲：输出 outline 卡片（每批最多 15 章）。"]
    elif intent in ("consistency_check", "analyze_only"):
        lines += [
            "- **设定一致性分析**：对照大纲、角色卡、世界观等，输出冲突清单与建议。",
            "- 使用 analysis 结构（或在 reply 中用 Markdown 表格/列表呈现冲突）。",
            "- 修正方案用 cards（character/outline）草案；edits 必须为空。",
            "- 禁止跳过分析直接改写章节正文。",
        ]
    elif intent == "cross_sync":
        if understanding.get("execute_prior_plan"):
            lines += [
                "- **执行上一轮方案**：必须写入数据库（设定卡片 + 涉及章节正文），禁止只口头声称已完成。",
                "- 设定：应用上一轮草案 character/outline 卡片；正文：按分析方案修改涉及章节并写入。",
            ]
        else:
            lines += [
                "- **跨资源同步**：先分析冲突，再输出统一后的 character/outline 卡片草案。",
                "- 用户明确「采纳/应用/开始执行」时方可 apply_card_ids；否则仅 draft。",
                "- edits 必须为空；不要改正文（执行阶段由后端逐章写入）。",
            ]
    elif intent == "discuss":
        lines += ["- 讨论/答疑：以 reply 为主；cards 与 actions 默认为空。"]

    if not understanding.get("allow_actions"):
        lines.append("- actions 必须为空数组 []。")
    if not understanding.get("allow_cards"):
        lines.append("- cards 必须为空数组 []（除非用户明确说「采纳」）。")
    if not understanding.get("allow_edits") and not understanding.get("execute_prior_plan"):
        lines.append("- edits 必须为空数组 []。")

    return "\n".join(lines)


async def execute_chapter_edit_plain(
    user: User,
    messages: list[dict],
    target_chapter_nos: list[int],
    understanding: dict[str, Any],
    user_message: str,
    chapter_contents: dict[int, str] | None = None,
) -> dict[str, Any]:
    """章节改写：按目标章逐章生成正文 edits（纯文本模式，避免 JSON 损坏）。"""
    all_targets = [n for n in (target_chapter_nos or []) if n > 0]
    targets = all_targets[:3]
    edit_scope = str(understanding.get("edit_scope") or "chapter")
    selection_quote = str(understanding.get("selection_quote") or "").strip()
    if not targets:
        return {
            "reply": "未能识别要修改的章节，请说明章号（如：润色第2-5章）。",
            "edits": [],
            "cards": [],
            "apply_card_ids": [],
            "actions": [],
        }

    hint = write_execution_hint(understanding, user_message)
    edits: list[dict] = []
    contents = chapter_contents or {}

    for no in targets:
        orig = (contents.get(no) or "").strip()
        plain_msgs = list(messages)
        mode_hint = f"\n\n【输出模式 · 第 {no} 章】只输出该章修改后的**完整小说正文**。"
        mode_hint += "不要 JSON，不要 markdown 代码块，不要改动说明/摘要/分章点评。"
        mode_hint += "不要写「第{n}章：」标题行，直接从正文第一句开始。".replace("{n}", str(no))
        if edit_scope == "selection" and selection_quote:
            mode_hint += (
                f"\n\n【选段修改】用户选中段落：\n{selection_quote}\n\n"
                "只修改该选段以符合用户指令与写作规约，但必须输出**整章完整正文**（未改部分保持原样）。"
                "禁止只输出选段或改动说明。"
            )
        plain_msgs.append({"role": "system", "content": hint + mode_hint})
        if orig:
            plain_msgs.append(
                {
                    "role": "user",
                    "content": f"【第 {no} 章原文供参考】\n{orig[:INTENT_CHAPTER_REF_CHARS]}",
                }
            )
        text = await _chat(user, plain_msgs, temperature=0.5, max_tokens=16384, json_object=False)
        body = (text or "").strip()

        # 模型可能仍返回 JSON / 说明+edits 混合体
        embedded = extract_edits_from_messy_text(body)
        if embedded:
            for e in embedded:
                c_no = int(e.get("chapter_no") or 0)
                if c_no not in targets:
                    continue
                if any(x.get("chapter_no") == c_no for x in edits):
                    continue
                content = str(e.get("content") or "").strip()
                orig = (contents.get(c_no) or "").strip()
                finalized = finalize_chapter_edit_content(
                    content,
                    chapter_no=c_no,
                    original_content=orig,
                    edit_scope=edit_scope,
                    selection_quote=selection_quote if c_no in targets else "",
                )
                if finalized:
                    edits.append(
                        {
                            "chapter_no": c_no,
                            "content": finalized,
                            "reason": str(understanding.get("summary") or user_message).strip()[:200] or "智能体改写",
                        }
                    )
            continue

        finalized = finalize_chapter_edit_content(
            body,
            chapter_no=no,
            original_content=orig,
            edit_scope=edit_scope,
            selection_quote=selection_quote,
        )
        if not finalized:
            continue
        edits.append(
            {
                "chapter_no": no,
                "content": finalized,
                "reason": str(understanding.get("summary") or user_message).strip()[:200] or "智能体改写",
            }
        )

    if not edits:
        return {
            "reply": edit_failure_reply(edit_scope=edit_scope, target_chapter_nos=all_targets),
            "edits": [],
            "cards": [],
            "apply_card_ids": [],
            "actions": [],
        }

    nos = [e["chapter_no"] for e in edits]
    if edit_scope == "selection" and len(nos) == 1:
        reply = f"已按你的要求修改第 {nos[0]} 章选段并写入编辑器。"
    else:
        reply = f"已修改第 {', '.join(str(n) for n in nos)} 章并写入编辑器。"
    if len(all_targets) > len(edits):
        remaining = [n for n in all_targets if n not in nos]
        reply += f" 其余第 {', '.join(str(n) for n in remaining[:5])} 章请再发一次继续处理。"
    return {
        "reply": reply,
        "edits": edits,
        "cards": [],
        "apply_card_ids": [],
        "actions": [],
    }


async def execute_brainstorm_plain(
    user: User,
    messages: list[dict],
    understanding: dict[str, Any],
    user_message: str,
) -> dict[str, Any]:
    """brainstorm 专用：纯文本输出，避免 JSON 解析失败。"""
    hint = write_execution_hint(understanding, user_message)
    plain_msgs = list(messages)
    plain_msgs.append(
        {
            "role": "system",
            "content": hint
            + "\n\n【输出模式】直接输出给用户看的 Markdown 正文，不要 JSON，不要代码块。"
            "必须列出完整编号列表。",
        }
    )
    text = await _chat(user, plain_msgs, temperature=0.72, max_tokens=8192, json_object=False)
    reply = (text or "").strip()
    if reply.startswith("{"):
        salvaged = salvage_reply_from_raw(reply)
        if salvaged:
            reply = salvaged
    return {
        "reply": reply or "请再说明一下你的具体需求，我会重新列出候选。",
        "edits": [],
        "cards": [],
        "apply_card_ids": [],
        "actions": [],
    }


def _rule_setup_intent(message: str, history: list[dict] | None = None) -> dict[str, Any]:
    msg = message.strip()
    ctx = _infer_history_context(history or [])
    must_do, must_not = _extract_constraints(msg)
    is_refine = any(k in msg for k in REFINE_KEYWORDS)

    if ctx["was_brainstorm"] and is_refine:
        return {
            "intent": "brainstorm",
            "topic": ctx["topic"],
            "is_follow_up": True,
            "summary": msg,
            "must_do": must_do or ["在 reply 中直接列出完整候选"],
            "must_not_do": must_not or ["不要无关跳转"],
            "allow_cards": False,
            "allow_actions": False,
        }

    if any(k in msg for k in ("下一步", "接下来", "做什么", "怎么办", "进度")):
        return {"intent": "guidance", "summary": "询问进度或下一步", "allow_cards": False}
    if any(k in msg for k in ("开始写", "试笔", "进入写作", "写第")):
        return {"intent": "writing", "summary": "进入写作", "allow_cards": False, "allow_actions": True}
    if any(k in msg for k in ("大纲", "章节规划", "规划章")):
        return {"intent": "outline", "summary": "规划章节大纲", "allow_cards": True}
    if any(k in msg for k in ("角色", "人物", "男主", "女主", "反派")):
        return {"intent": "character", "summary": "设计角色", "allow_cards": True}
    if any(k in msg for k in ("书名", "取名", "起名", "再取", "再来几个", "搞笑", "反差")):
        return {
            "intent": "brainstorm",
            "summary": "头脑风暴书名或卖点",
            "allow_cards": False,
            "must_do": must_do or ["在 reply 中直接列出完整候选"],
            "must_not_do": must_not or ["不要只写引言不列出内容"],
        }
    if ctx["was_brainstorm"]:
        return {
            "intent": "brainstorm",
            "topic": ctx["topic"],
            "is_follow_up": True,
            "summary": msg,
            "allow_cards": False,
            "must_do": must_do,
            "must_not_do": must_not,
        }
    return {"intent": "general", "summary": msg[:200], "allow_cards": True}


async def understand_setup_message(
    user: User,
    message: str,
    history: list[dict],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """阶段一：理解创书助手用户意图。"""
    rule = _rule_setup_intent(message, history)
    ctx = _infer_history_context(history)

    system = """你是 NovFlow 创书助手的语义理解模块。只输出 JSON。
短句修正（如「不一定非要强调能力等级」）必须结合历史判为 brainstorm + is_follow_up=true。

{
  "intent": "guidance|outline|writing|character|brainstorm|draft_card|show_card|general",
  "topic": "book_title|book_meta|character|worldview|outline|plot|other",
  "is_follow_up": false,
  "summary": "",
  "must_do": [],
  "must_not_do": [],
  "allow_cards": false,
  "allow_actions": false
}"""
    msgs: list[dict] = [{"role": "system", "content": system}]
    for h in history[-10:]:
        if h.get("role") in ("user", "assistant"):
            content = str(h.get("content") or "").strip()[:INTENT_HISTORY_MSG_CHARS]
            if content:
                msgs.append({"role": h["role"], "content": content})
    msgs.append(
        {
            "role": "user",
            "content": (
                f"书名：{snapshot.get('title')}\n阶段：{snapshot.get('phase')}\n"
                f"was_brainstorm={ctx['was_brainstorm']}\n用户消息：{message.strip()}"
            ),
        }
    )
    try:
        raw = await _chat(user, msgs, temperature=0.1, max_tokens=1500, json_object=True)
        data = _extract_json_object(raw)
        if not data:
            return rule
        intent = str(data.get("intent") or rule["intent"])
        if intent not in VALID_SETUP_INTENTS:
            intent = rule["intent"]
        merged = {
            "intent": intent,
            "topic": str(data.get("topic") or rule.get("topic", "other")),
            "is_follow_up": bool(data.get("is_follow_up")) or bool(rule.get("is_follow_up")),
            "summary": str(data.get("summary") or rule.get("summary") or message[:200]),
            "must_do": list(dict.fromkeys((rule.get("must_do") or []) + [str(x) for x in (data.get("must_do") or []) if x]))[:8],
            "must_not_do": list(dict.fromkeys((rule.get("must_not_do") or []) + [str(x) for x in (data.get("must_not_do") or []) if x]))[:8],
            "allow_cards": bool(data.get("allow_cards", rule.get("allow_cards", True))),
            "allow_actions": bool(data.get("allow_actions")),
        }
        if rule.get("intent") == "brainstorm" and rule.get("is_follow_up"):
            merged["intent"] = "brainstorm"
            merged["allow_cards"] = False
        return merged
    except Exception:
        return rule


def setup_execution_hint(understanding: dict[str, Any], message: str) -> str:
    lines = [
        "## 【语义理解 · 本轮必须先遵守】",
        f"- 意图：{understanding.get('intent')} · {understanding.get('summary') or message[:200]}",
    ]
    if understanding.get("is_follow_up"):
        lines.append("- 延续上一轮，承接约束，禁止答非所问。")
    for item in understanding.get("must_do") or []:
        lines.append(f"- 必须：{item}")
    for item in understanding.get("must_not_do") or []:
        lines.append(f"- 禁止：{item}")
    if understanding.get("intent") == "brainstorm":
        lines += ["- 完整内容写进 reply，cards/actions 为空。"]
    if not understanding.get("allow_cards"):
        lines.append("- cards 应为空数组。")
    return "\n".join(lines)
