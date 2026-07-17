import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  CheckCircle,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Save,
  Wand2,
  Wrench,
} from "lucide-react";
import { api, Chapter, ChapterPlan, GeneratedImage, LintIssue, LintResult, WriteAgentApplied, streamJob } from "../api";
import AppAlertModal from "../components/AppAlertModal";
import ChapterOutlinePanel from "../components/write/ChapterOutlinePanel";
import LintEditor from "../components/write/LintEditor";
import WriteAgentPanel, { type WriteAgentPanelHandle } from "../components/write/WriteAgentPanel";
import GeneratedImageGallery from "../components/GeneratedImageGallery";
import ImageUploadButton from "../components/ImageUploadButton";
import { closedErrorModal, errorModalFromUnknown, type ErrorModalState } from "../utils/errorModal";
import {
  applyAllHunkDecision,
  applyHunkDecision,
  createChapterDiffState,
  refreshChapterDiffHunks,
  type ChapterDiffState,
} from "../utils/chapterDiff";
import { resolveIssueLine } from "../utils/lintHighlight";
import { useAuth } from "../auth";

export default function ChapterEditorPage() {
  const { user } = useAuth();
  const { bookId, chapterNo } = useParams();
  const id = Number(bookId);
  const no = Number(chapterNo);
  const nav = useNavigate();

  const [chapter, setChapter] = useState<Chapter | null>(null);
  const [plans, setPlans] = useState<ChapterPlan[]>([]);
  const [content, setContent] = useState("");
  const [lint, setLint] = useState<LintResult | null>(null);
  const [linting, setLinting] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [message, setMessage] = useState("");
  const [errorModal, setErrorModal] = useState<ErrorModalState>(closedErrorModal);
  const [saving, setSaving] = useState(false);
  const [chapterDiffs, setChapterDiffs] = useState<Map<number, ChapterDiffState>>(() => new Map());
  const [toolboxOpen, setToolboxOpen] = useState(false);
  const [illustrations, setIllustrations] = useState<GeneratedImage[]>([]);
  const [generatingIll, setGeneratingIll] = useState(false);
  const cancelStream = useRef<(() => void) | null>(null);
  const agentRef = useRef<WriteAgentPanelHandle>(null);
  const lintSeqRef = useRef(0);
  const toolboxRef = useRef<HTMLDivElement>(null);

  const currentDiff = chapterDiffs.get(no);
  const showDiff = currentDiff?.showDiff ?? false;
  const diffBase = currentDiff?.baseContent ?? null;

  const currentPlan = useMemo(() => plans.find((p) => p.chapter_no === no) ?? null, [plans, no]);
  const chapterList = useMemo(
    () => [...plans].sort((a, b) => a.chapter_no - b.chapter_no),
    [plans],
  );

  const hasCurrentDiff = !!currentDiff && currentDiff.baseContent.trim() !== currentDiff.currentContent.trim();

  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      if (!toolboxRef.current?.contains(e.target as Node)) {
        setToolboxOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  const updateChapterDiff = useCallback((chapterNum: number, updater: (prev: ChapterDiffState | undefined) => ChapterDiffState | undefined) => {
    setChapterDiffs((prev) => {
      const next = new Map(prev);
      const updated = updater(next.get(chapterNum));
      if (updated) next.set(chapterNum, updated);
      else next.delete(chapterNum);
      return next;
    });
  }, []);

  const runLint = useCallback(
    async (text: string, includeAi = false) => {
      if (!text.trim()) {
        setLint(null);
        return;
      }
      const seq = ++lintSeqRef.current;
      setLinting(true);
      try {
        const lr = await api.lintDraft(id, no, text, includeAi);
        if (seq !== lintSeqRef.current) return;
        setLint(lr);
      } catch {
        /* keep previous lint */
      } finally {
        if (seq === lintSeqRef.current) setLinting(false);
      }
    },
    [id, no],
  );

  const load = useCallback(async () => {
    const [ch, allPlans, ill] = await Promise.all([
      api.chapter(id, no),
      api.chapterPlans(id),
      api.chapterIllustrations(id, no).catch(() => [] as GeneratedImage[]),
    ]);
    setIllustrations(ill);
    setChapter(ch);
    setPlans(allPlans);
    setChapterDiffs((prev) => {
      const diff = prev.get(no);
      const text = diff?.currentContent ?? ch.content;
      setContent(text);
      void runLint(text, false);
      return prev;
    });
  }, [id, no, runLint]);

  useEffect(() => {
    void load();
    return () => cancelStream.current?.();
  }, [load]);

  useEffect(() => {
    if (!content.trim()) {
      setLint(null);
      return;
    }
    const timer = setTimeout(() => {
      runLint(content, false);
    }, 450);
    return () => clearTimeout(timer);
  }, [content, runLint]);

  const clearDiffForChapter = (chapterNum: number) => {
    setChapterDiffs((prev) => {
      const next = new Map(prev);
      next.delete(chapterNum);
      return next;
    });
  };

  const showErrorModal = (error: unknown, fallbackTitle = "操作失败") => {
    setErrorModal(errorModalFromUnknown(error, fallbackTitle));
  };

  const save = async () => {
    setSaving(true);
    try {
      const ch = await api.updateChapter(id, no, { content });
      setChapter(ch);
      await runLint(content, false);
      clearDiffForChapter(no);
      setMessage("已保存");
    } catch (e) {
      showErrorModal(e, "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const waitJob = (jobId: number) =>
    new Promise<void>((resolve, reject) => {
      setStreamText("");
      cancelStream.current = streamJob(
        id,
        jobId,
        (text) => setStreamText((prev) => prev + text),
        async (status, error) => {
          if (status === "completed") {
            await load();
            setStreamText("");
            resolve();
          } else {
            reject(error ?? new Error("生成失败"));
          }
        },
      );
    });

  const generate = async () => {
    setGenerating(true);
    setMessage("");
    cancelStream.current?.();
    try {
      const job = await api.generate(id, no, "");
      await waitJob(job.id);
      setMessage("章节生成完成");
    } catch (e) {
      showErrorModal(e, "生成失败");
    } finally {
      setGenerating(false);
      cancelStream.current = null;
    }
  };

  const expand = async () => {
    setToolboxOpen(false);
    setGenerating(true);
    setMessage("");
    cancelStream.current?.();
    try {
      const job = await api.expand(id, no, 500, "");
      await waitJob(job.id);
      setMessage("扩写完成");
    } catch (e) {
      showErrorModal(e, "扩写失败");
    } finally {
      setGenerating(false);
      cancelStream.current = null;
    }
  };

  const fixAll = async () => {
    setToolboxOpen(false);
    if (!content.trim()) {
      setMessage("无正文可修复");
      return;
    }
    const autoCount = lint?.issues.filter((i) => i.auto_fixable).length ?? 0;
    if (autoCount === 0) {
      setMessage("没有可自动修复的规则问题（章标题、逗号、破折号）；AI 规约项请用「AI 规约修复」或智能体");
      return;
    }
    setGenerating(true);
    setMessage("");
    try {
      const fixed = await api.fixDraft(id, no, content);
      setContent(fixed.content);
      setLint(fixed.lint);
      const remain = fixed.lint.issues.filter((i) => i.auto_fixable).length;
      if (fixed.fixed_count > 0) {
        setMessage(
          remain > 0
            ? `已自动修复 ${fixed.fixed_count} 项，仍有 ${remain} 项可一键修复`
            : `已自动修复 ${fixed.fixed_count} 项规则问题`,
        );
      } else {
        setMessage("未检测到可自动修复项");
      }
    } catch (e) {
      showErrorModal(e, "修复失败");
    } finally {
      setGenerating(false);
    }
  };

  const handleIssueClick = async (issue: LintIssue) => {
    if (issue.auto_fixable) {
      try {
        const res = await api.fixIssueDraft(id, no, content, issue);
        setContent(res.content);
        setLint(res.lint);
        setMessage(`已修复：${issue.rule_id}`);
      } catch (e) {
        showErrorModal(e, "修复失败");
      }
      return;
    }
    const lineNo = resolveIssueLine(content, issue);
    const lineIdx = lineNo > 0 ? lineNo - 1 : -1;
    const lines = content.split("\n");
    const lineText =
      issue.excerpt ||
      issue.snippet ||
      (lineIdx >= 0 && lines[lineIdx].trim() ? lines[lineIdx] : "") ||
      "";
    agentRef.current?.appendQuote(lineText, no, [issue], `请修复以下违规（${issue.rule_id}）：${issue.message}`);
  };

  const fixWithAi = async () => {
    setToolboxOpen(false);
    if (!content.trim()) return;
    setGenerating(true);
    setMessage("");
    cancelStream.current?.();
    try {
      await save();
      const job = await api.fixAi(id, no);
      await waitJob(job.id);
      await load();
      setMessage("AI 规约修复完成");
    } catch (e) {
      showErrorModal(e, "AI 修复失败");
    } finally {
      setGenerating(false);
      cancelStream.current = null;
    }
  };

  const approve = async () => {
    try {
      await save();
      await api.approve(id, no);
      await load();
      setMessage("章节已批准");
    } catch (e) {
      showErrorModal(e, "定稿失败");
    }
  };

  const handleContentChange = (text: string) => {
    setContent(text);
    if (currentDiff) {
      updateChapterDiff(no, (prev) =>
        prev ? refreshChapterDiffHunks({ ...prev, currentContent: text }) : prev,
      );
    }
  };

  const handleHunkDecision = (blockId: string, accepted: boolean) => {
    if (!currentDiff) return;
    const { state, content: nextContent } = applyHunkDecision(currentDiff, blockId, accepted);
    updateChapterDiff(no, () => state);
    setContent(nextContent);
  };

  const handleAcceptAllHunks = () => {
    if (!currentDiff) return;
    const { state, content: nextContent } = applyAllHunkDecision(currentDiff, true);
    updateChapterDiff(no, () => state);
    setContent(nextContent);
  };

  const handleRejectAllHunks = () => {
    if (!currentDiff) return;
    const { state, content: nextContent } = applyAllHunkDecision(currentDiff, false);
    updateChapterDiff(no, () => state);
    setContent(nextContent);
  };

  const closeDiffView = () => {
    updateChapterDiff(no, (prev) => (prev ? { ...prev, showDiff: false } : prev));
  };

  const openDiffView = () => {
    setToolboxOpen(false);
    updateChapterDiff(no, (prev) => (prev ? { ...prev, showDiff: true } : prev));
  };

  const handleAgentApplied = async (
    applied: WriteAgentApplied[],
    snapshots?: { chapter_no: number; title: string; content: string }[],
    draftBefore?: string,
  ) => {
    const chapterUpdates = await Promise.all(
      applied.map(async (a) => {
        const ch = await api.chapter(id, a.chapter_no);
        const prev =
          (a.previous_content && a.previous_content.trim()) ||
          snapshots?.find((s) => s.chapter_no === a.chapter_no)?.content?.trim() ||
          (a.chapter_no === no ? draftBefore?.trim() : "") ||
          "";
        return { chapterNo: a.chapter_no, prev, content: ch.content, ch };
      }),
    );

    setChapterDiffs((prev) => {
      const nextDiffs = new Map(prev);
      for (const { chapterNo, prev, content: newContent } of chapterUpdates) {
        if (prev && prev !== newContent.trim()) {
          nextDiffs.set(chapterNo, createChapterDiffState(prev, newContent));
        }
      }
      return nextDiffs;
    });

    const currentUpdate = chapterUpdates.find((u) => u.chapterNo === no);
    if (currentUpdate) {
      setChapter(currentUpdate.ch);
      const text =
        currentUpdate.prev && currentUpdate.prev !== currentUpdate.content.trim()
          ? currentUpdate.content
          : currentUpdate.ch.content;
      setContent(text);
      await runLint(text, false);
    } else {
      await load();
    }
    setMessage(`智能体已更新 ${applied.map((a) => `第${a.chapter_no}章`).join("、")}`);
  };

  const generateIllustration = async (passage?: string) => {
    setGeneratingIll(true);
    try {
      const img = await api.generateIllustration(id, no, { passage: passage || content });
      setIllustrations((prev) => [...prev, img]);
      setMessage("章节插图已生成");
    } catch (e) {
      showErrorModal(e, "插图生成失败");
    } finally {
      setGeneratingIll(false);
    }
  };

  const uploadIllustration = async (file: File) => {
    const img = await api.uploadIllustration(id, no, file);
    setIllustrations((prev) => [...prev, img]);
    setMessage("章节插图已上传");
  };

  const refineIllustration = async (img: GeneratedImage, prompt: string) => {
    const refined = await api.refineImage(id, {
      kind: "illustration",
      prompt,
      parent_object_key: img.object_key,
      parent_id: img.id,
      chapter_no: no,
    });
    setIllustrations((prev) => [...prev, refined]);
  };

  const blockingErrors = lint?.issues.filter((i) => i.severity === "error" && i.blocking !== false).length ?? 0;
  const lintWarnings = lint?.issues.filter((i) => i.severity === "warn" || i.blocking === false).length ?? 0;
  const autoFixableCount = lint?.issues.filter((i) => i.auto_fixable).length ?? 0;

  const displayContent = generating && streamText ? streamText : content;
  const wordCount = displayContent.replace(/^#.*$/m, "").replace(/\s/g, "").length;

  const pendingDiffChapters = [...chapterDiffs.entries()]
    .filter(([, d]) => d.baseContent.trim() !== d.currentContent.trim())
    .map(([n]) => n);

  return (
    <div className="flex h-full min-h-0">
      <ChapterOutlinePanel bookId={id} chapterNo={no} plan={currentPlan} chapterList={chapterList} />

      <div className="flex min-w-0 flex-1 flex-col bg-white">
        <div className="flex shrink-0 items-center justify-between gap-2 border-b border-slate-200 px-4 py-2.5">
          <div className="flex min-w-0 items-center gap-3">
            <Link to={`/books/${id}`} className="shrink-0 text-brand-600 hover:text-brand-800">
              <ArrowLeft className="h-5 w-5" />
            </Link>
            <div className="min-w-0">
              <h1 className="truncate text-base font-bold text-slate-900">
                第{String(no).padStart(3, "0")}章 {chapter?.title || ""}
              </h1>
              <p className="text-xs text-slate-500">
                {wordCount} 字 · {chapter?.status || "planned"}
                {lint && !lint.passed && (
                  <span className="ml-2 text-red-600">
                    {blockingErrors > 0 ? `${blockingErrors} 处须修` : `${lintWarnings} 处建议`}
                  </span>
                )}
                {autoFixableCount > 0 && (
                  <span className="ml-2 text-sky-600">{autoFixableCount} 可一键修</span>
                )}
                {linting && <span className="ml-2 text-slate-400">检查中…</span>}
                {showDiff && diffBase && (
                  <span className="ml-2 text-emerald-600">变更预览中</span>
                )}
                {!showDiff && pendingDiffChapters.length > 0 && (
                  <span className="ml-2 text-amber-600">
                    {pendingDiffChapters.length} 章有待查看变更
                  </span>
                )}
              </p>
            </div>
          </div>

          <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
            <button type="button" className="btn-primary py-1.5 text-sm" onClick={generate} disabled={generating || !user?.deepseek_configured}>
              {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
              生成章节
            </button>

            <div className="relative" ref={toolboxRef}>
              <button
                type="button"
                className="btn-secondary py-1.5 text-sm"
                onClick={() => setToolboxOpen((v) => !v)}
                aria-expanded={toolboxOpen}
              >
                <Wrench className="h-4 w-4" />
                工具箱
                <ChevronDown className={`h-3.5 w-3.5 transition ${toolboxOpen ? "rotate-180" : ""}`} />
              </button>
              {toolboxOpen && (
                <div className="absolute right-0 top-full z-30 mt-1 min-w-[11rem] rounded-lg border border-slate-200 bg-white py-1 shadow-lg">
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                    onClick={expand}
                    disabled={generating || !content.trim() || !user?.deepseek_configured}
                  >
                    扩写 500 字
                  </button>
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                    onClick={fixAll}
                    disabled={generating || !content.trim() || autoFixableCount === 0}
                  >
                    一键修复{autoFixableCount > 0 ? ` (${autoFixableCount})` : ""}
                  </button>
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                    onClick={() => {
                      setToolboxOpen(false);
                      runLint(content, true);
                    }}
                    disabled={linting || !content.trim() || !user?.deepseek_configured}
                  >
                    重新检查
                  </button>
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                    onClick={fixWithAi}
                    disabled={generating || !content.trim() || !user?.deepseek_configured}
                  >
                    AI 规约修复
                  </button>
                  {hasCurrentDiff && !showDiff && (
                    <button
                      type="button"
                      className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-emerald-700 hover:bg-emerald-50"
                      onClick={openDiffView}
                    >
                      查看变更
                    </button>
                  )}
                </div>
              )}
            </div>

            <button
              type="button"
              className="btn-secondary py-1.5 px-2.5"
              onClick={save}
              disabled={saving}
              title={saving ? "保存中" : "保存"}
              aria-label="保存"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            </button>

            <button type="button" className="btn-secondary py-1.5 text-sm" onClick={approve} disabled={!content.trim()}>
              <CheckCircle className="h-4 w-4" /> 定稿
            </button>

            <button type="button" className="btn-secondary py-1.5 px-2.5" disabled={no <= 1} onClick={() => nav(`/books/${id}/write/${no - 1}`)}>
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button type="button" className="btn-secondary py-1.5 px-2.5" onClick={() => nav(`/books/${id}/write/${no + 1}`)}>
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="relative flex min-h-0 flex-1 flex-col">
          {showDiff && diffBase && currentDiff && (
            <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-emerald-100 bg-emerald-50/80 px-4 py-2 text-sm text-emerald-900">
              <span>
                变更预览 · <span className="text-emerald-700">绿=新增</span> ·{" "}
                <span className="text-red-600">红=删除</span> · <span className="text-amber-700">黄=修改</span>
              </span>
              <div className="flex flex-wrap items-center gap-2">
                <button type="button" className="btn-secondary py-1 px-2.5 text-xs" onClick={handleAcceptAllHunks}>
                  全部采纳
                </button>
                <button type="button" className="btn-secondary py-1 px-2.5 text-xs" onClick={handleRejectAllHunks}>
                  全部拒绝
                </button>
                <button type="button" className="btn-secondary py-1 px-2.5 text-xs" onClick={closeDiffView}>
                  完成查看
                </button>
              </div>
            </div>
          )}
          <LintEditor
            value={displayContent}
            onChange={handleContentChange}
            issues={lint?.issues ?? []}
            disabled={generating}
            diffBase={diffBase}
            showDiff={showDiff}
            diffHunks={currentDiff?.hunks}
            onHunkDecision={showDiff && currentDiff ? handleHunkDecision : undefined}
            placeholder={"# 第001章 标题\n\n正文从这里开始…"}
            onIssueClick={handleIssueClick}
            onAddToChat={(text, related) =>
              agentRef.current?.appendQuote(
                text,
                no,
                related,
                related?.[0]
                  ? `请修复以下违规（${related[0].rule_id}）：${related[0].message}`
                  : undefined,
              )
            }
          />
          {generating && (
            <div className="pointer-events-none absolute bottom-12 right-6 flex items-center gap-2 rounded-full bg-brand-50 px-3 py-1.5 text-sm text-brand-700 shadow-sm ring-1 ring-brand-100">
              <Loader2 className="h-4 w-4 animate-spin" />
              AI 生成中…
            </div>
          )}
        </div>

        <div className="shrink-0 border-t border-slate-100 bg-slate-50/80 px-4 py-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-medium text-slate-800">章节插图</h3>
              <p className="text-xs text-slate-500">支持 AI 生成或本地上传，上传后同样可做多轮调整</p>
            </div>
            <div className="flex gap-2">
              <ImageUploadButton
                label="上传插图"
                disabled={generatingIll}
                onUpload={uploadIllustration}
                onError={setMessage}
              />
              <button
                type="button"
                className="btn-secondary text-xs"
                disabled={generatingIll || !content.trim()}
                onClick={() => generateIllustration()}
              >
                {generatingIll ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5" />}
                全文生成
              </button>
            </div>
          </div>
          {illustrations.length > 0 ? (
            <GeneratedImageGallery images={illustrations} onRefine={refineIllustration} compact />
          ) : (
            <p className="text-xs text-slate-500">本章尚无插图</p>
          )}
        </div>

        {message && (
          <div className="shrink-0 border-t border-slate-100 px-4 py-1.5 text-sm text-slate-600">{message}</div>
        )}
      </div>

      <WriteAgentPanel
        ref={agentRef}
        bookId={id}
        chapterNo={no}
        draftContent={content}
        onApplied={handleAgentApplied}
        onBookUpdated={load}
        onError={(error) => showErrorModal(error, "智能体请求失败")}
        configured={!!user?.deepseek_configured}
      />

      <AppAlertModal
        open={errorModal.open}
        title={errorModal.title}
        message={errorModal.message}
        settingsLink={errorModal.settingsLink}
        onClose={() => setErrorModal(closedErrorModal)}
      />
    </div>
  );
}
