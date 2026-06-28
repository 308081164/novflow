import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Loader2, MessageCircle, PenLine, Send } from "lucide-react";
import { api, Book, GeneratedImage, SetupCard, SetupMessage, SetupSnapshot } from "../api";
import { PageHeader } from "../components/Layout";
import ContextPanel from "../components/setup/ContextPanel";
import SetupActionBar from "../components/setup/SetupActionBar";
import { SetupCardEditModal, SetupCardGrid } from "../components/setup/SetupCard";
import GeneratedImageGallery from "../components/GeneratedImageGallery";
import { normalizeSetupMessage } from "../utils/setupMessage";
import type { TimelineChapter } from "../components/setup/OutlineTimeline";

const SUGGESTIONS = [
  "下一步我们应该做什么？",
  "我想写一部都市悬疑，主角是私家侦探",
  "根据已有设定，规划第 1～10 章大纲",
  "帮我想几个反转点",
  "设计一个有趣的女主角",
  "帮我生成一张小说封面",
];

const PROGRESS_STEP_LABELS: Record<string, string> = {
  understand: "理解您的指令",
  context: "加载作品设定与已有大纲",
  delete_outline: "删除指定章节大纲",
  generate: "AI 生成中",
  generate_fallback: "专用通道生成大纲",
  review_rules: "规则一致性校验",
  review_llm: "AI 深度审阅",
  auto_fix: "自动修订问题",
  review_done: "质检完成",
  finalize: "整理回复",
};

export default function SetupChatPage() {
  const { bookId } = useParams();
  const id = Number(bookId);
  const nav = useNavigate();
  const bottomRef = useRef<HTMLDivElement>(null);

  const [book, setBook] = useState<Book | null>(null);
  const [snapshot, setSnapshot] = useState<SetupSnapshot | null>(null);
  const [messages, setMessages] = useState<SetupMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [progressSteps, setProgressSteps] = useState<string[]>([]);
  const [currentProgress, setCurrentProgress] = useState("");
  const [applyingId, setApplyingId] = useState<string | null>(null);
  const [editCard, setEditCard] = useState<SetupCard | null>(null);
  const [editOutlineChapter, setEditOutlineChapter] = useState<TimelineChapter | undefined>();
  const [err, setErr] = useState("");
  const [finishing, setFinishing] = useState(false);

  const load = async () => {
    const ctx = await api.setupChatContext(id);
    setBook(ctx.book);
    setSnapshot(ctx.snapshot);
    setMessages(ctx.messages);
  };

  useEffect(() => {
    load()
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  const send = async (text?: string) => {
    const msg = (text ?? input).trim();
    if (!msg || sending) return;
    setInput("");
    setSending(true);
    setErr("");
    setProgressSteps([]);
    setCurrentProgress("正在连接…");
    try {
      const res = await api.setupChatStream(id, msg, {
        onProgress: (data) => {
          const label =
            (data.detail as string) ||
            PROGRESS_STEP_LABELS[String(data.step || "")] ||
            String(data.step || "");
          if (!label) return;
          setCurrentProgress(label);
          setProgressSteps((prev) => (prev.includes(label) ? prev : [...prev, label]));
        },
      });
      setMessages((prev) => [...prev, res.user_message, res.assistant_message]);
      setBook(res.book);
      setSnapshot(res.snapshot);
    } catch (e) {
      setErr(String(e));
      setInput(msg);
      // 流式 done 失败时，服务端可能已保存消息，尝试从服务器恢复
      try {
        await load();
      } catch {
        /* ignore recovery failure */
      }
    } finally {
      setSending(false);
      setCurrentProgress("");
      setProgressSteps([]);
    }
  };

  const applyCard = async (card: SetupCard) => {
    setApplyingId(card.id);
    setErr("");
    try {
      const res = await api.setupChatApply(id, card);
      setBook(res.book);
      setSnapshot(res.snapshot);
      if (res.messages) setMessages(res.messages);
      else {
        setMessages((prev) =>
          prev.map((m) => ({
            ...m,
            cards: m.cards.map((c) => (c.id === card.id ? { ...c, status: "applied" as const } : c)),
          })),
        );
      }
    } catch (e) {
      setErr(String(e));
    } finally {
      setApplyingId(null);
      setEditCard(null);
      setEditOutlineChapter(undefined);
    }
  };

  const finish = async () => {
    setFinishing(true);
    setErr("");
    try {
      await api.setupChatFinish(id);
      nav(`/books/${id}`);
    } catch (e) {
      setErr(String(e));
    } finally {
      setFinishing(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24 text-slate-500">
        <Loader2 className="h-6 w-6 animate-spin" /> 加载创作助手…
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="AI 创作助手"
        desc={book ? `《${book.title}》· 对话式头脑风暴，卡片一键写入设定` : undefined}
        action={
          <div className="flex flex-wrap gap-2">
            <Link to={`/books/${id}/setup/classic`} className="btn-secondary text-xs">
              经典向导
            </Link>
            {book && book.setup_step >= 4 && (
              <button type="button" className="btn-primary" onClick={finish} disabled={finishing}>
                <PenLine className="h-4 w-4" />
                {finishing ? "准备中…" : "完成设定，开始写作"}
              </button>
            )}
          </div>
        }
      />

      {err && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {err.includes("API Key") ? (
            <>
              {err}{" "}
              <Link to="/settings" className="font-medium underline">
                去设置
              </Link>
            </>
          ) : (
            err
          )}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="card flex min-h-[70vh] flex-col">
          <div className="flex-1 space-y-6 overflow-y-auto p-4">
            {messages.map((m) => {
              const msg = normalizeSetupMessage(m);
              return (
                <div key={m.id} className={`flex flex-col ${m.role === "user" ? "items-end" : "items-start"}`}>
                  {m.role === "assistant" && (
                    <div className="mb-1 flex items-center gap-1 text-xs font-medium text-brand-600">
                      <MessageCircle className="h-3.5 w-3.5" /> 创作助手
                    </div>
                  )}
                  {(msg.content.trim() || m.role === "user") && (
                  <div
                    className={`max-w-[85%] rounded-2xl px-4 py-3 ${
                      m.role === "user"
                        ? "bg-brand-600 text-white"
                        : m.role === "system"
                          ? "bg-slate-100 text-slate-600 text-sm"
                          : "bg-white text-slate-800 border border-slate-200 shadow-sm"
                    }`}
                  >
                  {m.role !== "user" ? (
                    <div
                      className="whitespace-pre-wrap text-sm leading-relaxed"
                      dangerouslySetInnerHTML={{
                        __html: msg.content
                          .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
                          .replace(/\n/g, "<br />"),
                      }}
                    />
                  ) : (
                    <p className="whitespace-pre-wrap text-sm leading-relaxed">{msg.content}</p>
                  )}
                  </div>
                  )}
                  {m.role === "assistant" && !msg.content.trim() && !msg.cards?.length && !(m.meta?.images as GeneratedImage[] | undefined)?.length && (
                    <div className="max-w-[85%] rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                      本次回复为空，请重试；若一次要很多角色，建议分 2～3 个一批发送。
                    </div>
                  )}
                  {m.role === "assistant" && (m.meta?.images as GeneratedImage[] | undefined)?.length > 0 && (
                    <div className="mt-2 w-full max-w-md">
                      <GeneratedImageGallery
                        images={m.meta!.images as GeneratedImage[]}
                        compact
                        onRefine={async (img, prompt) => {
                          const refined = await api.refineImage(id, {
                            kind: img.kind || "cover",
                            prompt,
                            parent_object_key: img.object_key,
                            parent_id: img.id,
                            character_id: img.character_id,
                          });
                          setMessages((prev) =>
                            prev.map((x) =>
                              x.id === m.id
                                ? {
                                    ...x,
                                    meta: {
                                      ...x.meta,
                                      images: [...((x.meta?.images as GeneratedImage[]) || []), refined],
                                    },
                                  }
                                : x,
                            ),
                          );
                        }}
                      />
                    </div>
                  )}
                  {msg.role === "assistant" && msg.cards?.length > 0 && (
                    <SetupCardGrid
                      cards={msg.cards}
                      onApply={applyCard}
                      onEdit={(c, ch) => {
                        setEditCard(c);
                        setEditOutlineChapter(ch);
                      }}
                      applyingId={applyingId}
                    />
                  )}
                  {msg.role === "assistant" && (msg.actions?.length ?? 0) > 0 && (
                    <SetupActionBar bookId={id} actions={msg.actions!} />
                  )}
                </div>
              );
            })}
            {sending && (
              <div className="flex justify-start">
                <div className="max-w-[85%] rounded-2xl border border-brand-100 bg-brand-50/60 px-4 py-3 text-sm text-slate-600">
                  <div className="flex items-center gap-2">
                    <Loader2 className="h-4 w-4 shrink-0 animate-spin text-brand-600" />
                    <span className="font-medium text-brand-800">{currentProgress || "思考中…"}</span>
                  </div>
                  {progressSteps.length > 1 && (
                    <ul className="mt-2 space-y-1 border-t border-brand-100 pt-2 text-xs text-slate-500">
                      {progressSteps.map((step, i) => (
                        <li key={step} className="flex items-center gap-1.5">
                          {i < progressSteps.length - 1 ? (
                            <span className="text-emerald-500">✓</span>
                          ) : (
                            <Loader2 className="h-3 w-3 animate-spin text-brand-500" />
                          )}
                          {step}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {messages.length <= 1 && (
            <div className="border-t border-slate-100 px-4 py-3">
              <p className="mb-2 text-xs text-slate-500">快速开始：</p>
              <div className="flex flex-wrap gap-2">
                {SUGGESTIONS.map((s) => (
                  <button key={s} type="button" onClick={() => send(s)} className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs text-slate-600 hover:border-brand-300 hover:text-brand-700">
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="border-t border-slate-100 p-4">
            {snapshot?.progress && snapshot.progress.outline_written >= 1 && (
              <div className="mb-3 flex items-center justify-between gap-2 rounded-lg border border-brand-100 bg-brand-50 px-3 py-2">
                <span className="text-xs text-brand-800">大纲已就绪，可以开始写作</span>
                <Link to={`/books/${id}/write/1`} className="btn-primary shrink-0 text-xs">
                  <PenLine className="h-3.5 w-3.5" />
                  去写作
                </Link>
              </div>
            )}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                send();
              }}
              className="flex gap-2"
            >
              <textarea
                className="input min-h-[44px] max-h-32 flex-1 resize-none"
                placeholder="聊聊你的灵感、人物、情节…（Enter 发送，Shift+Enter 换行）"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send();
                  }
                }}
                rows={1}
                disabled={sending}
              />
              <button type="submit" className="btn-primary self-end" disabled={sending || !input.trim()}>
                <Send className="h-4 w-4" />
              </button>
            </form>
          </div>
        </div>

        <aside className="hidden lg:block">
          {book && snapshot && <ContextPanel book={book} snapshot={snapshot} />}
          <Link to={`/books/${id}`} className="btn-secondary mt-4 w-full text-xs">
            <ArrowLeft className="h-3.5 w-3.5" /> 返回书籍概览
          </Link>
        </aside>
      </div>

      {editCard && (
        <SetupCardEditModal
          card={editCard}
          outlineChapter={editOutlineChapter}
          onClose={() => {
            setEditCard(null);
            setEditOutlineChapter(undefined);
          }}
          onSave={(c) => applyCard(c)}
        />
      )}
    </div>
  );
}
