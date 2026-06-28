import type { LintIssue } from "../api";

/** 在正文中按 excerpt 搜索行号（1-based），跳过标题/空行，找不到返回 0 */
export function findLineForExcerpt(content: string, excerpt: string): number {
  const ex = excerpt.trim();
  if (!ex) return 0;
  const lines = content.split("\n");

  const scan = (needle: string): number => {
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line.trim().startsWith("#") || !line.trim()) continue;
      if (line.includes(needle)) return i + 1;
    }
    return 0;
  };

  const hit = scan(ex);
  if (hit) return hit;
  if (ex.length >= 8) return scan(ex.slice(0, 24));
  return 0;
}

/** 校验 issue 在当前正文中的有效行号；excerpt 已删除则返回 0 */
export function resolveIssueLine(content: string, issue: LintIssue): number {
  const excerpt = (issue.excerpt || issue.snippet || "").trim();
  if (excerpt) {
    return findLineForExcerpt(content, excerpt);
  }
  const line = issue.line_no;
  if (line > 0) {
    const lines = content.split("\n");
    if (line <= lines.length) return line;
  }
  return 0;
}

export function lineDecorations(
  issues: LintIssue[],
  content: string,
): Map<number, "error" | "warn"> {
  const map = new Map<number, "error" | "warn">();
  for (const issue of issues) {
    const line = resolveIssueLine(content, issue);
    if (line <= 0) continue;
    const sev = issue.severity === "error" ? "error" : "warn";
    const prev = map.get(line);
    if (!prev || sev === "error") map.set(line, sev);
  }
  return map;
}

export function issuesForLine(issues: LintIssue[], lineNo: number, content: string): LintIssue[] {
  return issues.filter((i) => resolveIssueLine(content, i) === lineNo);
}

export function globalIssues(issues: LintIssue[], content?: string): LintIssue[] {
  return issues.filter((i) => {
    if (content !== undefined) return resolveIssueLine(content, i) <= 0;
    return !i.line_no || i.line_no <= 0;
  });
}

export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** 将纯文本转为带行级 lint 颜色的 HTML */
export function textToLintHtml(text: string, deco: Map<number, "error" | "warn">): string {
  const lines = text.split("\n");
  return lines
    .map((line, i) => {
      const ln = i + 1;
      const sev = deco.get(ln);
      const inner = escapeHtml(line) || "<br>";
      if (sev === "error") return `<div class="lint-line lint-line-error">${inner}</div>`;
      if (sev === "warn") return `<div class="lint-line lint-line-warn">${inner}</div>`;
      return `<div class="lint-line">${inner}</div>`;
    })
    .join("");
}

/** 从 contenteditable 提取纯文本 */
export function htmlToText(root: HTMLElement): string {
  const lineDivs = root.querySelectorAll(".lint-line");
  if (lineDivs.length > 0) {
    return Array.from(lineDivs)
      .map((node) => node.textContent ?? "")
      .join("\n");
  }
  return root.innerText.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

/** 保存/恢复光标（按字符偏移） */
export function getCaretCharOffset(root: HTMLElement): number {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return 0;
  const range = sel.getRangeAt(0);
  const pre = range.cloneRange();
  pre.selectNodeContents(root);
  pre.setEnd(range.endContainer, range.endOffset);
  return pre.toString().length;
}

export function setCaretCharOffset(root: HTMLElement, offset: number): void {
  const sel = window.getSelection();
  if (!sel) return;
  let remaining = Math.max(0, offset);
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node: Text | null = walker.nextNode() as Text | null;
  while (node) {
    const len = node.textContent?.length ?? 0;
    if (remaining <= len) {
      const range = document.createRange();
      range.setStart(node, remaining);
      range.collapse(true);
      sel.removeAllRanges();
      sel.addRange(range);
      return;
    }
    remaining -= len;
    node = walker.nextNode() as Text | null;
  }
  const range = document.createRange();
  range.selectNodeContents(root);
  range.collapse(false);
  sel.removeAllRanges();
  sel.addRange(range);
}
