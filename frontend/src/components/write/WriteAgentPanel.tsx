import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { Loader2, MessageCircle, MessageSquarePlus, Minimize2, Pencil, Quote, Send, Sparkles, Undo2, X } from "lucide-react";
import { api, GeneratedImage, SetupCard, WriteAgentApplied, WriteAgentContextStatus, WriteAgentRevertSnapshot, type LintIssue } from "../../api";
import { SetupCardEditModal, SetupCardGrid } from "../setup/SetupCard";
import type { TimelineChapter } from "../setup/OutlineTimeline";
import SetupActionBar from "../setup/SetupActionBar";
import GeneratedImageGallery from "../GeneratedImageGallery";
import {
  type WriteAgentAssistantMsg,
  type WriteAgentChatMsg,
  type WriteAgentUserMsg,
  writeAgentMessageToChat,
  writeAgentMessagesToChat,
} from "../../utils/writeAgentMessage";

export type WriteAgentPanelHandle = {
  appendQuote: (text: string, chapterNo?: number, lintIssues?: LintIssue[], instruction?: string) => void;
};

type Props = {
  bookId: number;
  chapterNo: number;
  draftContent: string;
  onApplied: (
    applied: WriteAgentApplied[],
    snapshots?: WriteAgentRevertSnapshot[],
    draftBefore?: string,
  ) => void;
  onBookUpdated?: () => void;
  configured: boolean;
};

const SUGGESTIONS = [
  "润色本章，让开头更抓人",
  "帮我调出男主的角色卡片",
  "调出本书写作偏好",
  "查看章节大纲",
  "按大纲补全本章缺失的情节点",
  "为本章生成一张场景插图",
];

function buildPayload(chapterNo: number, inputText: string, quote: string | null): string {
  let msg = inputText.trim();
  if (quote) {
    const quoted = quote.split("\n").map((line) => `> ${line}`).join("\n");
    msg = `【选段 · 第${chapterNo}章】\n${quoted}\n\n${msg || "请润色或修改以上选段。"}`;
  }
  return msg;
}

function assistantFromResponse(
  res: Awaited<ReturnType<typeof api.writeAgentChat>>,
): WriteAgentAssistantMsg | null {
  if (res.assistant_message) return writeAgentMessageToChat(res.assistant_message) as WriteAgentAssistantMsg;
  if (!res.reply) return null;
  const appliedCardIds = new Set((res.card_applied || []).map((x) => String(x.card_id ?? "")));
  const cards = (res.cards || []).map((c) =>
    appliedCardIds.has(c.id) || c.status === "applied" ? { ...c, status: "applied" as const } : c,
  );
  let content = res.reply;
  if (res.applied.length > 0) {
    content += `\n\n✅ 已写入：${res.applied.map((a) => `第${a.chapter_no}章`).join("、")}`;
  }
  return {
    id: `tmp_${Date.now()}`,
    role: "assistant",
    content,
    applied: res.applied.length ? res.applied : undefined,
    revertSnapshots: res.revert_snapshots?.length ? res.revert_snapshots : undefined,
    cards: cards.length ? cards : undefined,
    actions: res.actions?.length ? res.actions : undefined,
    images: res.images?.length ? res.images : (res.assistant_message?.meta?.images as GeneratedImage[] | undefined),
  };
}

export default forwardRef<WriteAgentPanelHandle, Props>(function WriteAgentPanel(
  { bookId, chapterNo, draftContent, onApplied, onBookUpdated, configured },
  ref,
) {
  const [messages, setMessages] = useState<WriteAgentChatMsg[]>([]);
  const [contextStatus, setContextStatus] = useState<WriteAgentContextStatus | null>(null);
  const [compressing, setCompressing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [input, setInput] = useState("");
  const [attachedQuote, setAttachedQuote] = useState<string | null>(null);
  const [attachedLintIssues, setAttachedLintIssues] = useState<LintIssue[]>([]);
  const [sending, setSending] = useState(false);
  const [applyingId, setApplyingId] = useState<string | null>(null);
  const [revertingId, setRevertingId] = useState<string | null>(null);
  const [editCard, setEditCard] = useState<SetupCard | null>(null);
  const [editOutlineChapter, setEditOutlineChapter] = useState<TimelineChapter | undefined>();
  const [editMsgId, setEditMsgId] = useState<string | null>(null);
  const [resendMode, setResendMode] = useState<{
    resendFromMessageId?: number;
    undoSnapshots: WriteAgentRevertSnapshot[] | null;
    undoOnSend: boolean;
  } | null>(null);
  const [messagesBackup, setMessagesBackup] = useState<WriteAgentChatMsg[] | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const loadMessages = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.writeAgentMessages(bookId, chapterNo);
      setMessages(writeAgentMessagesToChat(data.messages));
      setContextStatus(data.context_status ?? null);
    } catch {
      setMessages([]);
      setContextStatus(null);
    } finally {
      setLoading(false);
    }
  }, [bookId, chapterNo]);

  useEffect(() => {
    loadMessages();
  }, [loadMessages]);

  useImperativeHandle(
    ref,
    () => ({
      appendQuote(text: string, _chNo?: number, lintIssues?: LintIssue[], instruction?: string) {
        const trimmed = text.trim();
        if (!trimmed) return;
        setAttachedQuote(trimmed);
        setAttachedLintIssues(lintIssues ?? []);
        const hint =
          instruction?.trim() ||
          (lintIssues?.length
            ? `请修复以下违规（${lintIssues[0].rule_id}）：${lintIssues[0].message}`
            : "请针对以上选段：");
        setInput((prev) => (prev.trim() ? prev : hint));
        setTimeout(() => inputRef.current?.focus(), 0);
      },
    }),
    [],
  );

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending, resendMode, loading]);

  const markCardApplied = (msgId: string, cardId: string) => {
    setMessages((prev) =>
      prev.map((m) => {
        if (m.role !== "assistant" || m.id !== msgId || !m.cards) return m;
        return {
          ...m,
          cards: m.cards.map((c) => (c.id === cardId ? { ...c, status: "applied" as const } : c)),
        };
      }),
    );
  };

  const revertAssistantEdit = async (msg: WriteAgentAssistantMsg) => {
    if (!msg.revertSnapshots?.length || msg.reverted || revertingId) return;
    if (!window.confirm(`确定撤回此次修改？将恢复 ${msg.revertSnapshots.map((s) => `第${s.chapter_no}章`).join("、")} 的内容。`)) {
      return;
    }
    setRevertingId(msg.id);
    try {
      const rev = await api.writeAgentRevert(bookId, msg.revertSnapshots);
      if (rev.reverted.length) onApplied(rev.reverted);
      setMessages((prev) =>
        prev.map((m) =>
          m.role === "assistant" && m.id === msg.id ? { ...m, reverted: true } : m,
        ),
      );
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        {
          id: `err_${Date.now()}`,
          role: "assistant",
          content: e instanceof Error ? e.message : "撤回失败",
        },
      ]);
    } finally {
      setRevertingId(null);
    }
  };

  const applyCard = async (card: SetupCard, msgId?: string) => {
    setApplyingId(card.id);
    try {
      await api.writeAgentApply(bookId, { ...card, status: "applied" });
      if (msgId) markCardApplied(msgId, card.id);
      else {
        setMessages((prev) =>
          prev.map((m) => {
            if (m.role !== "assistant" || !m.cards?.some((c) => c.id === card.id)) return m;
            return {
              ...m,
              cards: m.cards.map((c) => (c.id === card.id ? { ...c, status: "applied" as const } : c)),
            };
          }),
        );
      }
      onBookUpdated?.();
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        {
          id: `err_${Date.now()}`,
          role: "assistant",
          content: e instanceof Error ? e.message : "卡片采纳失败",
        },
      ]);
    } finally {
      setApplyingId(null);
      setEditCard(null);
      setEditMsgId(null);
    }
  };

  const startEdit = (userMsg: WriteAgentUserMsg, userIndex: number) => {
    const next = messages[userIndex + 1];
    const undoSnapshots =
      next?.role === "assistant" && next.revertSnapshots?.length ? next.revertSnapshots : null;
    setMessagesBackup(messages);
    setMessages((prev) => prev.slice(0, userIndex));
    setInput(userMsg.inputText);
    setAttachedQuote(userMsg.quote);
    setResendMode({
      resendFromMessageId: userMsg.dbId,
      undoSnapshots,
      undoOnSend: !!undoSnapshots,
    });
    setTimeout(() => inputRef.current?.focus(), 0);
  };

  const cancelResend = () => {
    if (messagesBackup) setMessages(messagesBackup);
    setMessagesBackup(null);
    setResendMode(null);
    setInput("");
    setAttachedQuote(null);
  };

  const startNewSession = async () => {
    if (sending) return;
    if (!window.confirm("开启新对话后，当前对话记录仍保存在服务端，但将不再作为上下文。确定继续？")) return;
    setSending(true);
    try {
      const data = await api.writeAgentNewSession(bookId);
      setMessages(writeAgentMessagesToChat(data.messages));
      setContextStatus(data.context_status ?? null);
      setResendMode(null);
      setMessagesBackup(null);
      setInput("");
      setAttachedQuote(null);
    } finally {
      setSending(false);
    }
  };

  const compressContext = async () => {
    if (compressing || sending) return;
    if (
      !window.confirm(
        "将把较早的对话压缩为摘要并归档，保留最近若干轮完整对话。压缩后仍可继续协作，确定继续？",
      )
    ) {
      return;
    }
    setCompressing(true);
    try {
      const data = await api.writeAgentCompressContext(bookId);
      setMessages(writeAgentMessagesToChat(data.messages));
      setContextStatus(data.context_status);
      if (!data.ok) {
        setMessages((prev) => [
          ...prev,
          {
            id: `info_${Date.now()}`,
            role: "assistant",
            content: data.message,
          },
        ]);
      }
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        {
          id: `err_${Date.now()}`,
          role: "assistant",
          content: e instanceof Error ? e.message : "压缩失败",
        },
      ]);
    } finally {
      setCompressing(false);
    }
  };

  const send = async (text?: string) => {
    const inputText = (text ?? input).trim();
    if (!inputText && !attachedQuote) return;
    if (sending) return;

    const payload = buildPayload(chapterNo, inputText || "请润色或修改以上选段。", attachedQuote);
    const quoteSnapshot = attachedQuote;
    const lintSnapshot = attachedLintIssues;
    const draftSnapshot = draftContent;
    setInput("");
    setAttachedQuote(null);
    setAttachedLintIssues([]);
    setSending(true);

    try {
      if (resendMode?.undoOnSend && resendMode.undoSnapshots?.length) {
        const rev = await api.writeAgentRevert(bookId, resendMode.undoSnapshots);
        if (rev.reverted.length) onApplied(rev.reverted);
      }

      const streamAssistantId = `stream_${Date.now()}`;
      setMessages((prev) => [
        ...prev,
        {
          id: streamAssistantId,
          role: "assistant" as const,
          content: "",
          streaming: true,
        },
      ]);

      let streamText = "";
      const res = await api.writeAgentChatStream(
        bookId,
        {
          message: payload,
          chapter_no: chapterNo,
          draft_content: draftContent,
          input_text: inputText || "请润色或修改以上选段。",
          quote: quoteSnapshot,
          lint_issues: lintSnapshot.map((i) => ({
            rule_id: i.rule_id,
            line_no: i.line_no,
            message: i.message,
            excerpt: i.excerpt || i.snippet,
          })),
          resend_from_message_id: resendMode?.resendFromMessageId,
        },
        {
          onToken: (t) => {
            streamText += t;
            setMessages((prev) =>
              prev.map((m) =>
                m.id === streamAssistantId ? { ...m, content: streamText } : m,
              ),
            );
          },
          onReply: (t) => {
            streamText = t;
            setMessages((prev) =>
              prev.map((m) =>
                m.id === streamAssistantId ? { ...m, content: streamText } : m,
              ),
            );
          },
        },
      );

      if (res.user_message && res.assistant_message) {
        const pair = writeAgentMessagesToChat([res.user_message, res.assistant_message]);
        setMessages((prev) => [
          ...prev.filter((m) => m.id !== streamAssistantId),
          ...pair,
        ]);
      } else {
        setMessages((prev) => prev.filter((m) => m.id !== streamAssistantId));
        const assistant = assistantFromResponse(res);
        if (assistant) setMessages((prev) => [...prev, assistant]);
      }

      setResendMode(null);
      setMessagesBackup(null);

      if (res.applied.length > 0) {
        onApplied(res.applied, res.revert_snapshots, draftSnapshot);
      }
      if (
        res.cards?.some((c) => c.status === "applied") ||
        (res.card_applied?.length ?? 0) > 0
      ) {
        onBookUpdated?.();
      }
      if (res.context_status) {
        setContextStatus(res.context_status);
      }
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        {
          id: `err_${Date.now()}`,
          role: "assistant",
          content: e instanceof Error ? e.message : "请求失败，请重试",
        },
      ]);
    } finally {
      setSending(false);
    }
  };

  return (
    <aside className="flex h-full w-96 shrink-0 flex-col border-l border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-4 py-3">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Sparkles className="h-4 w-4 text-brand-600" />
              写作智能体
            </h2>
            <p className="mt-0.5 text-xs text-slate-500">
              对话已保存 · 当前聚焦第 {chapterNo} 章
            </p>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1">
            <button
              type="button"
              className="btn-secondary px-2 py-1 text-[10px]"
              onClick={startNewSession}
              disabled={sending || loading || compressing}
              title="开启新对话"
            >
              <MessageSquarePlus className="h-3.5 w-3.5" />
              新对话
            </button>
            {(contextStatus?.warn || contextStatus?.suggest_compress) && (
              <button
                type="button"
                className="btn-secondary px-2 py-1 text-[10px] text-amber-800"
                onClick={compressContext}
                disabled={sending || loading || compressing}
                title="压缩对话上下文"
              >
                {compressing ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Minimize2 className="h-3.5 w-3.5" />
                )}
                压缩对话
              </button>
            )}
          </div>
        </div>
      </div>

      {contextStatus && (contextStatus.warn || contextStatus.suggest_compress) && (
        <div
          className={`mx-3 mt-2 rounded-lg border px-3 py-2 text-xs ${
            contextStatus.suggest_compress
              ? "border-amber-300 bg-amber-50 text-amber-900"
              : "border-slate-200 bg-slate-50 text-slate-700"
          }`}
        >
          <p className="font-medium">
            {contextStatus.suggest_compress ? "对话上下文较大，建议压缩" : "对话上下文接近上限"}
          </p>
          <p className="mt-0.5 leading-relaxed">
            约 {Math.round(contextStatus.estimated_tokens / 1000)}k tokens（
            {contextStatus.active_message_count} 条活跃消息）。
            {contextStatus.suggest_compress
              ? " 可点击「压缩对话」将较早记录合并为摘要，保留最近对话。"
              : " 继续对话可能变慢，必要时可压缩上下文。"}
          </p>
        </div>
      )}

      <div className="flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {loading && (
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" /> 加载对话…
          </div>
        )}
        {!loading &&
          messages.map((m, i) => (
            <div key={m.id} className={`flex flex-col ${m.role === "user" ? "items-end" : "items-start"}`}>
              {m.role === "assistant" && (
                <span className="mb-1 flex items-center gap-1 text-xs text-brand-600">
                  <MessageCircle className="h-3 w-3" />
                  {m.isContextSummary ? "对话摘要" : "智能体"}
                  {m.isContextSummary && m.archivedCount != null && (
                    <span className="text-slate-400">· 已压缩 {m.archivedCount} 条</span>
                  )}
                </span>
              )}
              {m.role === "assistant" && m.taskPlan && m.taskPlan.steps && m.taskPlan.steps.length > 0 && (
                <div className="mb-2 w-full max-w-full rounded-xl border border-violet-100 bg-violet-50/80 px-3 py-2 text-xs text-violet-900">
                  <div className="mb-1 font-semibold text-violet-800">任务计划</div>
                  <ol className="list-decimal space-y-0.5 pl-4">
                    {m.taskPlan.steps.map((s, idx) => (
                      <li key={s.id || idx}>{s.description || s.action}</li>
                    ))}
                  </ol>
                  {m.taskPlan.execution_mode === "analyze_only" && (
                    <p className="mt-1 text-[10px] text-violet-700">分析模式：不会直接改写章节正文</p>
                  )}
                </div>
              )}
              <div className="group relative max-w-[95%]">
                <div
                  className={`whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm leading-relaxed ${
                    m.role === "user"
                      ? "bg-brand-600 text-white"
                      : m.isContextSummary
                        ? "border border-sky-200 bg-sky-50 text-slate-800"
                        : "bg-slate-100 text-slate-800"
                  }`}
                >
                  {m.role === "user" ? m.payload : m.content}
                </div>
                {m.role === "user" && !sending && (
                  <button
                    type="button"
                    title="重新编辑并发送"
                    onClick={() => startEdit(m, i)}
                    className="absolute -left-8 top-1/2 -translate-y-1/2 rounded p-1 text-slate-400 opacity-0 transition hover:bg-slate-100 hover:text-brand-600 group-hover:opacity-100"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
              {m.role === "assistant" && m.images && m.images.length > 0 && (
                <div className="mt-2 w-full max-w-full">
                  <GeneratedImageGallery
                    images={m.images}
                    compact
                    onRefine={async (img, prompt) => {
                      const refined = await api.refineImage(bookId, {
                        kind: img.kind || "illustration",
                        prompt,
                        parent_object_key: img.object_key,
                        parent_id: img.id,
                        chapter_no: img.kind === "illustration" ? chapterNo : undefined,
                      });
                      setMessages((prev) =>
                        prev.map((x) =>
                          x.id === m.id && x.role === "assistant"
                            ? { ...x, images: [...(x.images || []), refined] }
                            : x,
                        ),
                      );
                    }}
                  />
                </div>
              )}
              {m.role === "assistant" && m.cards && m.cards.length > 0 && (
                <div className="mt-2 w-full max-w-full">
                  <SetupCardGrid
                    cards={m.cards}
                    applyingId={applyingId}
                    onApply={(card) => applyCard(card, m.id)}
                    onEdit={(card, ch) => {
                      setEditCard(card);
                      setEditOutlineChapter(ch);
                      setEditMsgId(m.id);
                    }}
                  />
                </div>
              )}
              {m.role === "assistant" && m.actions && m.actions.length > 0 && (
                <SetupActionBar bookId={bookId} actions={m.actions} className="mt-2" />
              )}
              {m.role === "assistant" && m.applied && m.applied.length > 0 && (
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <span className="text-[10px] text-slate-400">
                    已修改 {m.applied.map((a) => `第${a.chapter_no}章`).join("、")}
                  </span>
                  {m.revertSnapshots && m.revertSnapshots.length > 0 && (
                    <button
                      type="button"
                      disabled={!!m.reverted || revertingId === m.id}
                      onClick={() => revertAssistantEdit(m)}
                      className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-0.5 text-[10px] text-slate-600 hover:border-amber-300 hover:bg-amber-50 hover:text-amber-800 disabled:opacity-50"
                    >
                      {revertingId === m.id ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Undo2 className="h-3 w-3" />
                      )}
                      {m.reverted ? "已撤回" : "撤回"}
                    </button>
                  )}
                </div>
              )}
            </div>
          ))}
        {sending && (
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" /> 思考中…
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {!configured && (
        <div className="mx-3 mb-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">
          请先在 <a href="/settings" className="underline">设置</a> 配置 API Key
        </div>
      )}

      <div className="border-t border-slate-100 px-3 py-2">
        {resendMode && (
          <div className="mb-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">正在重新编辑上一条消息</span>
              <button type="button" className="text-amber-700 hover:underline" onClick={cancelResend}>
                取消
              </button>
            </div>
            {resendMode.undoSnapshots && resendMode.undoSnapshots.length > 0 && (
              <label className="mt-2 flex cursor-pointer items-start gap-2">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={resendMode.undoOnSend}
                  onChange={(e) =>
                    setResendMode((prev) => (prev ? { ...prev, undoOnSend: e.target.checked } : prev))
                  }
                />
                <span>
                  发送前撤销上一轮修改（恢复{" "}
                  {resendMode.undoSnapshots.map((s) => `第${s.chapter_no}章`).join("、")}）
                </span>
              </label>
            )}
          </div>
        )}

        {attachedQuote && (
          <div className="mb-2 rounded-lg border border-brand-200 bg-brand-50/80 p-2">
            <div className="mb-1 flex items-center justify-between gap-2">
              <span className="flex items-center gap-1 text-[10px] font-medium text-brand-700">
                <Quote className="h-3 w-3" /> 已选段 · 第{chapterNo}章
              </span>
              <button
                type="button"
                className="text-slate-400 hover:text-slate-600"
                onClick={() => {
                  setAttachedQuote(null);
                  setAttachedLintIssues([]);
                }}
                aria-label="移除选段"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
            <p className="line-clamp-3 whitespace-pre-wrap text-xs leading-relaxed text-slate-700">{attachedQuote}</p>
          </div>
        )}

        <div className="mb-2 flex flex-wrap gap-1">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              disabled={sending || !configured || !!resendMode || loading}
              onClick={() => send(s)}
              className="rounded-full border border-slate-200 px-2 py-0.5 text-[10px] text-slate-600 hover:border-brand-300 hover:text-brand-700 disabled:opacity-50"
            >
              {s}
            </button>
          ))}
        </div>

        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
        >
          <textarea
            ref={inputRef}
            className="input min-h-[44px] max-h-24 flex-1 resize-none text-sm"
            placeholder={
              resendMode
                ? "编辑后重新发送…"
                : attachedQuote
                  ? "补充指令，如：润色语气 / 加强冲突…"
                  : "描述你想怎么改本章或全书…"
            }
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={sending || !configured || loading}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            rows={1}
          />
          <button
            type="submit"
            className="btn-primary self-end px-3"
            disabled={sending || (!input.trim() && !attachedQuote) || !configured || loading}
            title={resendMode ? "重新发送" : "发送"}
          >
            <Send className="h-4 w-4" />
          </button>
        </form>
      </div>

      {editCard && (
        <SetupCardEditModal
          card={editCard}
          outlineChapter={editOutlineChapter}
          onClose={() => {
            setEditCard(null);
            setEditOutlineChapter(undefined);
            setEditMsgId(null);
          }}
          onSave={(updated) => {
            if (editMsgId) {
              setMessages((prev) =>
                prev.map((m) => {
                  if (m.role !== "assistant" || m.id !== editMsgId || !m.cards) return m;
                  return {
                    ...m,
                    cards: m.cards.map((c) => (c.id === updated.id ? updated : c)),
                  };
                }),
              );
            }
            applyCard(updated, editMsgId ?? undefined);
          }}
        />
      )}
    </aside>
  );
});
