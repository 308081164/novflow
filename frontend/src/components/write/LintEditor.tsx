import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { MessageSquarePlus } from "lucide-react";
import type { LintIssue } from "../api";
import {
  getCaretCharOffset,
  globalIssues,
  htmlToText,
  issuesForLine,
  lineDecorations,
  setCaretCharOffset,
  textToLintHtml,
} from "../../utils/lintHighlight";
import { countDiffChanges, diffTextLines, textToDiffHtml, type DiffHunk } from "../../utils/textDiff";

type Props = {
  value: string;
  onChange: (value: string) => void;
  issues: LintIssue[];
  disabled?: boolean;
  placeholder?: string;
  onIssueClick?: (issue: LintIssue) => void;
  onAddToChat?: (text: string, issues?: LintIssue[]) => void;
  /** 智能体修改前的正文；与 showDiff 配合展示 Cursor 式 diff */
  diffBase?: string | null;
  showDiff?: boolean;
  diffHunks?: DiffHunk[];
  onHunkDecision?: (blockId: string, accepted: boolean) => void;
};

const EDITOR_CLASS =
  "lint-editor-input h-full w-full overflow-auto border-0 bg-white px-6 py-5 font-serif text-[17px] leading-[1.85] tracking-normal text-slate-800 outline-none focus:ring-0";

type SelectionFab = { top: number; left: number; text: string; lineNo: number };

function estimateLineNo(root: HTMLElement, range: Range): number {
  const pre = range.cloneRange();
  pre.selectNodeContents(root);
  pre.setEnd(range.startContainer, range.startOffset);
  return pre.toString().split("\n").length;
}

const MAX_GLOBAL_CHIPS = 6;

export default function LintEditor({
  value,
  onChange,
  issues,
  disabled,
  placeholder,
  onIssueClick,
  onAddToChat,
  diffBase,
  showDiff = false,
  diffHunks,
  onHunkDecision,
}: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const composingRef = useRef(false);
  const lastHtmlRef = useRef("");
  const [fab, setFab] = useState<SelectionFab | null>(null);

  const inDiffView = showDiff && !!diffBase;
  const diffLines = inDiffView ? diffTextLines(diffBase!, value) : [];
  const diffStats = inDiffView ? countDiffChanges(diffLines) : null;

  const globals = inDiffView ? [] : globalIssues(issues, value);
  const visibleGlobals = globals.slice(0, MAX_GLOBAL_CHIPS);
  const hiddenGlobalCount = globals.length - visibleGlobals.length;
  const decoByLine = inDiffView ? new Map<number, "error" | "warn">() : lineDecorations(issues, value);

  useEffect(() => {
    lastHtmlRef.current = "";
  }, [issues, value, diffBase, showDiff, diffHunks]);

  const paint = useCallback(() => {
    const el = rootRef.current;
    if (!el || composingRef.current) return;
    const html = inDiffView
      ? textToDiffHtml(diffLines, diffHunks, { interactive: !!onHunkDecision })
      : textToLintHtml(value, decoByLine);
    if (html === lastHtmlRef.current) return;
    const caret = inDiffView ? 0 : getCaretCharOffset(el);
    el.innerHTML = html || `<div class="lint-line"><br></div>`;
    lastHtmlRef.current = html;
    if (!inDiffView) setCaretCharOffset(el, caret);
  }, [value, decoByLine, inDiffView, diffLines, diffHunks, onHunkDecision]);

  useLayoutEffect(() => {
    paint();
  }, [paint]);

  useEffect(() => {
    const el = rootRef.current;
    if (!el || !inDiffView || !onHunkDecision) return;
    const onClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      const btn = target.closest(".diff-hunk-btn") as HTMLElement | null;
      if (!btn) return;
      e.preventDefault();
      const blockId = btn.getAttribute("data-block-id");
      const action = btn.getAttribute("data-action");
      if (!blockId || !action) return;
      onHunkDecision(blockId, action === "accept");
    };
    el.addEventListener("click", onClick);
    return () => el.removeEventListener("click", onClick);
  }, [inDiffView, onHunkDecision]);

  const updateSelectionFab = useCallback(() => {
    if (disabled || !onAddToChat || inDiffView) {
      setFab(null);
      return;
    }
    const el = rootRef.current;
    const sel = window.getSelection();
    if (!el || !sel || sel.isCollapsed || sel.rangeCount === 0) {
      setFab(null);
      return;
    }
    const anchor = sel.anchorNode;
    const focus = sel.focusNode;
    if (!anchor || !focus || !el.contains(anchor) || !el.contains(focus)) {
      setFab(null);
      return;
    }
    const text = sel.toString().trim();
    if (text.length < 2) {
      setFab(null);
      return;
    }
    const range = sel.getRangeAt(0);
    const rect = range.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) {
      setFab(null);
      return;
    }
    setFab({
      top: rect.bottom + 6,
      left: Math.max(8, rect.left + rect.width / 2 - 56),
      text,
      lineNo: getCaretCharOffset(el) > 0 ? estimateLineNo(el, range) : 0,
    });
  }, [disabled, onAddToChat, inDiffView]);

  useEffect(() => {
    document.addEventListener("selectionchange", updateSelectionFab);
    const el = rootRef.current;
    el?.addEventListener("scroll", () => setFab(null));
    return () => {
      document.removeEventListener("selectionchange", updateSelectionFab);
    };
  }, [updateSelectionFab]);

  useEffect(() => {
    const onPointerDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (t instanceof Element && t.closest(".lint-add-to-chat-fab")) return;
      window.setTimeout(updateSelectionFab, 0);
    };
    document.addEventListener("mouseup", onPointerDown);
    return () => document.removeEventListener("mouseup", onPointerDown);
  }, [updateSelectionFab]);

  const handleInput = () => {
    if (inDiffView) return;
    const el = rootRef.current;
    if (!el || composingRef.current) return;
    const text = htmlToText(el);
    lastHtmlRef.current = textToLintHtml(text, decoByLine);
    onChange(text);
  };

  const handleAddToChat = () => {
    if (!fab || !onAddToChat) return;
    const related =
      fab.lineNo > 0
        ? issuesForLine(issues, fab.lineNo, value)
        : issues.filter((i) => fab.text.includes(i.excerpt?.trim() || i.snippet?.trim() || ""));
    onAddToChat(fab.text, related.length ? related : undefined);
    setFab(null);
    window.getSelection()?.removeAllRanges();
  };

  const showPlaceholder = !value.trim() && placeholder && !inDiffView;

  return (
    <div className="lint-editor relative h-full min-h-0 flex-1 overflow-hidden">
      {globals.length > 0 && (
        <div className="absolute left-6 right-6 top-2 z-20 flex flex-wrap gap-1.5">
          {visibleGlobals.map((issue, idx) => (
            <button
              key={`${issue.rule_id}-${idx}`}
              type="button"
              title={`${issue.message}${issue.auto_fixable ? " · 点击自动修复" : " · 点击加入智能体对话"}`}
              onClick={() => onIssueClick?.(issue)}
              className={`rounded-md px-2 py-0.5 text-xs ring-1 cursor-pointer hover:ring-2 ${
                issue.auto_fixable
                  ? "bg-sky-50 text-sky-800 ring-sky-200"
                  : issue.severity === "error"
                    ? "bg-red-50 text-red-700 ring-red-200"
                    : "bg-amber-50 text-amber-800 ring-amber-200"
              }`}
            >
              {issue.auto_fixable ? "⚡ " : ""}
              {issue.rule_id}: {issue.message}
            </button>
          ))}
          {hiddenGlobalCount > 0 && (
            <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-600 ring-1 ring-slate-200">
              +{hiddenGlobalCount} 项
            </span>
          )}
        </div>
      )}

      <div className="relative h-full overflow-hidden" style={{ paddingTop: globals.length ? 36 : 0 }}>
        {inDiffView && diffStats && (
          <div className="pointer-events-none absolute right-6 top-2 z-20 rounded-full bg-white/95 px-3 py-1 text-xs text-slate-600 shadow-sm ring-1 ring-slate-200">
            <span className="text-emerald-700">+{diffStats.added + diffStats.changed}</span>
            <span className="mx-1.5 text-slate-300">|</span>
            <span className="text-red-600">−{diffStats.removed + diffStats.changed}</span>
          </div>
        )}
        {showPlaceholder && (
          <div className="pointer-events-none absolute left-6 top-5 z-10 whitespace-pre-wrap font-serif text-[17px] leading-[1.85] text-slate-400">
            {placeholder}
          </div>
        )}

        <div
          ref={rootRef}
          role="textbox"
          aria-multiline
          contentEditable={!disabled && !inDiffView}
          suppressContentEditableWarning
          className={EDITOR_CLASS}
          onInput={handleInput}
          onKeyUp={updateSelectionFab}
          onCompositionStart={() => {
            composingRef.current = true;
            setFab(null);
          }}
          onCompositionEnd={() => {
            composingRef.current = false;
            handleInput();
          }}
        />
      </div>

      {fab && onAddToChat && (
        <button
          type="button"
          className="lint-add-to-chat-fab fixed z-50 flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white shadow-lg ring-1 ring-slate-700 transition hover:bg-slate-800"
          style={{ top: fab.top, left: fab.left }}
          onMouseDown={(e) => e.preventDefault()}
          onClick={handleAddToChat}
        >
          <MessageSquarePlus className="h-3.5 w-3.5" />
          加入对话
        </button>
      )}

      {issues.length > 0 && !inDiffView && (
        <div className="pointer-events-none absolute bottom-3 left-6 z-20 flex items-center gap-2 rounded-full bg-white/90 px-3 py-1 text-xs shadow-sm ring-1 ring-slate-200 backdrop-blur">
          <span className="text-red-600">
            {issues.filter((i) => i.severity === "error" && i.blocking !== false).length} 须修
          </span>
          <span className="text-slate-300">|</span>
          <span className="text-amber-600">
            {issues.filter((i) => i.severity === "warn" || i.blocking === false).length} 建议
          </span>
          {issues.some((i) => i.auto_fixable) && (
            <>
              <span className="text-slate-300">|</span>
              <span className="text-sky-600">{issues.filter((i) => i.auto_fixable).length} 可一键修</span>
            </>
          )}
        </div>
      )}
    </div>
  );
}
