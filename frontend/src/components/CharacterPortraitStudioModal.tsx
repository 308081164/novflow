import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Check,
  Loader2,
  MessageCircle,
  Send,
  Sparkles,
  Star,
  X,
  ZoomIn,
} from "lucide-react";
import type { GeneratedImage } from "../api";
import { withMediaAuth } from "../api";
import ImageLightbox from "./ImageLightbox";
import ImageUploadButton from "./ImageUploadButton";

type StudioMessage =
  | { id: string; role: "user"; content: string }
  | { id: string; role: "assistant"; content: string; image?: GeneratedImage };

type Props = {
  characterName: string;
  images: GeneratedImage[];
  onClose: () => void;
  onGenerate: () => Promise<GeneratedImage>;
  onUpload?: (file: File) => Promise<GeneratedImage>;
  onRefine: (image: GeneratedImage, prompt: string) => Promise<GeneratedImage>;
  onSetActive: (objectKey: string) => Promise<GeneratedImage[]>;
};

function pickInitialIndex(images: GeneratedImage[]) {
  const activeIdx = images.findIndex((img) => img.is_active);
  if (activeIdx >= 0) return activeIdx;
  return images.length > 0 ? images.length - 1 : -1;
}

function formatVersionLabel(index: number, total: number) {
  return `v${index + 1}/${total}`;
}

/** 9:16 立绘缩略图：顶部对齐，避免裁切头部 */
export const PORTRAIT_THUMB_IMG_CLASS = "h-full w-full object-cover object-top";

/** 从用户输入解析版本号（1-based），如 v2、版本2、第2版 */
function parseVersionIndexFromText(text: string, total: number): number | null {
  if (total <= 0) return null;
  const patterns = [
    /(?:基于|从|参照|参考|按)\s*v(\d+)/i,
    /(?:基于|从|参照|参考|按)\s*版本\s*(\d+)/,
    /第\s*(\d+)\s*(?:版|个版本)/,
    /\bv(\d+)\b/i,
  ];
  for (const pattern of patterns) {
    const m = text.match(pattern);
    if (m) {
      const n = parseInt(m[1], 10);
      if (n >= 1 && n <= total) return n - 1;
    }
  }
  return null;
}

/** 去掉消息中的版本指向前缀，避免干扰即梦提示词 */
function stripVersionHint(text: string): string {
  const stripped = text
    .replace(
      /^(?:基于|从|参照|参考|按)\s*(?:v\d+|版本\s*\d+|第\s*\d+\s*(?:版|个版本))\s*(?:版本)?\s*(?:进一步|继续)?(?:优化|调整|修改|改)?[:：,，]?\s*/i,
      "",
    )
    .trim();
  return stripped || text.trim();
}

export default function CharacterPortraitStudioModal({
  characterName,
  images: initialImages,
  onClose,
  onGenerate,
  onUpload,
  onRefine,
  onSetActive,
}: Props) {
  const [images, setImages] = useState(initialImages);
  const [previewIndex, setPreviewIndex] = useState(() => pickInitialIndex(initialImages));
  const [refineBaseIndex, setRefineBaseIndex] = useState(() => pickInitialIndex(initialImages));

  useEffect(() => {
    setImages(initialImages);
  }, [initialImages]);
  const [messages, setMessages] = useState<StudioMessage[]>(() => {
    if (!initialImages.length) {
      return [
        {
          id: "welcome",
          role: "assistant",
          content: "还没有立绘。你可以上传本地图片、先「生成立绘」，或在下方输入调整描述开始对话式修改。",
        },
      ];
    }
    const active = initialImages.find((img) => img.is_active) || initialImages[initialImages.length - 1];
    return [
      {
        id: "welcome",
        role: "assistant",
        content: `已加载 ${initialImages.length} 个历史版本。右侧点击选择「调整基准」；或在描述中写「基于 v2 调整…」。满意后点击「采用此版本」。`,
        image: active,
      },
    ];
  });
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [adopting, setAdopting] = useState(false);
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const preview = previewIndex >= 0 ? images[previewIndex] : null;
  const refineBase = refineBaseIndex >= 0 ? images[refineBaseIndex] : null;
  const activeImage = useMemo(
    () => images.find((img) => img.is_active) || null,
    [images],
  );
  const previewIsActive = preview?.object_key && preview.object_key === activeImage?.object_key;

  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !lightboxSrc) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose, lightboxSrc]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  const appendAssistant = (content: string, image?: GeneratedImage) => {
    setMessages((prev) => [
      ...prev,
      { id: `a_${Date.now()}`, role: "assistant", content, image },
    ]);
  };

  const handleUpload = async (file: File) => {
    if (!onUpload) return;
    setBusy(true);
    try {
      const img = await onUpload(file);
      setImages((prev) => {
        const next = [...prev, { ...img, is_active: img.is_active ?? !prev.some((x) => x.is_active) }];
        setPreviewIndex(next.length - 1);
        setRefineBaseIndex(next.length - 1);
        return next;
      });
      appendAssistant("已上传立绘，可作为调整基准继续对话式修改，满意后采用为正式立绘。", img);
    } catch (e) {
      appendAssistant(e instanceof Error ? e.message : "上传失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  };

  const handleGenerate = async () => {
    setBusy(true);
    try {
      const img = await onGenerate();
      setImages((prev) => {
        const next = [...prev, { ...img, is_active: img.is_active ?? !prev.some((x) => x.is_active) }];
        setPreviewIndex(next.length - 1);
        setRefineBaseIndex(next.length - 1);
        return next;
      });
      appendAssistant("已生成新的立绘版本，请在右侧历史中选择预览，满意后采用为正式立绘。", img);
    } catch (e) {
      appendAssistant(e instanceof Error ? e.message : "生成失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  };

  const selectVersion = (idx: number) => {
    setPreviewIndex(idx);
    setRefineBaseIndex(idx);
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setMessages((prev) => [...prev, { id: `u_${Date.now()}`, role: "user", content: text }]);
    setBusy(true);
    try {
      const parsedIdx = parseVersionIndexFromText(text, images.length);
      let baseIdx = refineBaseIndex;
      if (parsedIdx !== null) {
        baseIdx = parsedIdx;
        setPreviewIndex(parsedIdx);
        setRefineBaseIndex(parsedIdx);
      }
      let parent = baseIdx >= 0 ? images[baseIdx] : null;
      if (!parent && images.length > 0) {
        parent = images[images.length - 1];
        baseIdx = images.length - 1;
        setRefineBaseIndex(baseIdx);
      }
      if (!parent) {
        const img = await onGenerate();
        setImages([img]);
        setPreviewIndex(0);
        setRefineBaseIndex(0);
        appendAssistant("已根据描述生成首版立绘。", img);
        return;
      }
      const refinePrompt = stripVersionHint(text);
      const img = await onRefine(parent, refinePrompt);
      setImages((prev) => {
        const next = [...prev, img];
        setPreviewIndex(next.length - 1);
        setRefineBaseIndex(next.length - 1);
        return next;
      });
      appendAssistant(
        `已基于 ${formatVersionLabel(baseIdx, images.length)} 生成新版本（${formatVersionLabel(images.length, images.length + 1)}），可在右侧历史切换对比。`,
        img,
      );
    } catch (e) {
      appendAssistant(e instanceof Error ? e.message : "调整失败，请稍后重试。");
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  };

  const handleAdopt = async () => {
    if (!preview?.object_key || adopting) return;
    setAdopting(true);
    try {
      const updated = await onSetActive(preview.object_key);
      setImages(updated);
      const idx = updated.findIndex((img) => img.object_key === preview.object_key);
      if (idx >= 0) setPreviewIndex(idx);
      appendAssistant(`已将 ${formatVersionLabel(idx >= 0 ? idx : previewIndex, updated.length)} 设为正式立绘，角色卡将展示此版本。`);
    } catch (e) {
      appendAssistant(e instanceof Error ? e.message : "设置正式立绘失败。");
    } finally {
      setAdopting(false);
    }
  };

  return createPortal(
    <div className="fixed inset-0 z-[9998] flex items-center justify-center bg-black/50 p-3 sm:p-6">
      <div
        className="flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-slate-200"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-slate-200 bg-gradient-to-r from-emerald-600 to-emerald-500 px-4 py-3 text-white">
          <div className="min-w-0">
            <h2 className="truncate text-base font-bold">{characterName} · 立绘工坊</h2>
            <p className="text-[11px] text-emerald-100/90">上传或 AI 生成 · 对话式调整 · 选定正式立绘</p>
          </div>
          <button
            type="button"
            className="shrink-0 rounded-lg bg-white/15 p-2 hover:bg-white/25"
            onClick={onClose}
            aria-label="关闭"
          >
            <X className="h-5 w-5" />
          </button>
        </header>

        <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)_140px]">
          {/* 对话区 */}
          <section className="flex min-h-[220px] flex-col border-b border-slate-200 lg:min-h-0 lg:border-b-0 lg:border-r">
            <div className="shrink-0 border-b border-slate-100 px-3 py-2 text-xs font-medium text-slate-600">
              <MessageCircle className="mr-1 inline h-3.5 w-3.5" />
              调整对话
            </div>
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
              {messages.map((m) => (
                <div key={m.id} className={`flex flex-col ${m.role === "user" ? "items-end" : "items-start"}`}>
                  {m.role === "assistant" && (
                    <span className="mb-1 text-[10px] text-emerald-600">立绘助手</span>
                  )}
                  <div
                    className={`max-w-[95%] rounded-2xl px-3 py-2 text-xs leading-relaxed ${
                      m.role === "user"
                        ? "bg-brand-600 text-white"
                        : "border border-slate-200 bg-slate-50 text-slate-700"
                    }`}
                  >
                    <p className="whitespace-pre-wrap">{m.content}</p>
                    {m.role === "assistant" && m.image && (
                      <button
                        type="button"
                        className="mt-2 block overflow-hidden rounded-lg ring-1 ring-slate-200"
                        onClick={() => {
                          const idx = images.findIndex((img) => img.object_key === m.image?.object_key);
                          if (idx >= 0) selectVersion(idx);
                        }}
                      >
                        <img
                          src={withMediaAuth(m.image.url)}
                          alt=""
                          className="h-24 w-auto object-cover object-top"
                        />
                      </button>
                    )}
                  </div>
                </div>
              ))}
              {busy && (
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  正在生成…
                </div>
              )}
              <div ref={chatEndRef} />
            </div>
            <div className="shrink-0 border-t border-slate-100 p-3">
              {refineBase && images.length > 0 && (
                <div className="mb-2 flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50/80 px-2 py-1.5">
                  <img
                    src={withMediaAuth(refineBase.url)}
                    alt=""
                    className="h-10 w-7 shrink-0 rounded object-cover object-top ring-1 ring-emerald-200"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-[10px] font-semibold text-emerald-800">
                      调整基准：{formatVersionLabel(refineBaseIndex, images.length)}
                    </p>
                    <p className="text-[9px] text-emerald-700/80">右侧点击切换；或输入「基于 v2 …」</p>
                  </div>
                </div>
              )}
              <div className="flex gap-2">
                <textarea
                  ref={inputRef}
                  className="input min-h-[2.5rem] flex-1 resize-none text-xs"
                  rows={2}
                  placeholder="基于 v2 调整：换成制式短裙、加强光影…"
                  value={input}
                  disabled={busy}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      handleSend();
                    }
                  }}
                />
                <button
                  type="button"
                  className="btn-primary shrink-0 self-end px-3 py-2 text-xs"
                  disabled={busy || !input.trim()}
                  onClick={handleSend}
                >
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                </button>
              </div>
              {!images.length && (
                <div className="mt-2 flex gap-2">
                  {onUpload && (
                    <ImageUploadButton
                      label="上传立绘"
                      className="btn-secondary flex-1 py-1.5 text-xs"
                      disabled={busy}
                      onUpload={handleUpload}
                    />
                  )}
                  <button
                    type="button"
                    className="btn-secondary flex-1 py-1.5 text-xs"
                    disabled={busy}
                    onClick={handleGenerate}
                  >
                    <Sparkles className="h-3.5 w-3.5" />
                    生成立绘
                  </button>
                </div>
              )}
            </div>
          </section>

          {/* 预览区 */}
          <section className="flex min-h-[280px] flex-col border-b border-slate-200 lg:min-h-0 lg:border-b-0 lg:border-r">
            <div className="flex shrink-0 items-center justify-between border-b border-slate-100 px-3 py-2">
              <span className="text-xs font-medium text-slate-600">
                {preview ? formatVersionLabel(previewIndex, images.length) : "预览"}
                {previewIsActive && (
                  <span className="ml-2 inline-flex items-center gap-0.5 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-800">
                    <Star className="h-3 w-3 fill-current" />
                    正式采用
                  </span>
                )}
              </span>
              {preview && (
                <button
                  type="button"
                  className="inline-flex items-center gap-1 text-[10px] text-brand-600 hover:underline"
                  onClick={() => setLightboxSrc(withMediaAuth(preview.url))}
                >
                  <ZoomIn className="h-3 w-3" />
                  放大
                </button>
              )}
            </div>
            <div className="flex min-h-0 flex-1 items-center justify-center bg-slate-100 p-4">
              {preview ? (
                <img
                  src={withMediaAuth(preview.url)}
                  alt={preview.prompt || `${characterName} 立绘`}
                  className="max-h-full max-w-full rounded-xl object-contain shadow-md ring-1 ring-slate-200"
                  style={{ maxHeight: "min(52vh, 520px)", aspectRatio: "9/16" }}
                />
              ) : (
                <div className="text-center text-sm text-slate-500">
                  <Sparkles className="mx-auto mb-2 h-8 w-8 text-slate-300" />
                  暂无立绘，请在左侧生成或发送调整描述
                </div>
              )}
            </div>
            {preview?.prompt && (
              <p className="shrink-0 border-t border-slate-100 px-3 py-2 text-[10px] leading-relaxed text-slate-500 line-clamp-3">
                {preview.prompt}
              </p>
            )}
          </section>

          {/* 历史版本 */}
          <section className="flex min-h-[120px] flex-col lg:min-h-0">
            <div className="shrink-0 border-b border-slate-100 px-2 py-2 text-center text-[10px] font-medium text-slate-600">
              历史 {images.length} 版
              <span className="mt-0.5 block text-[9px] font-normal text-slate-400">点击设为调整基准</span>
            </div>
            <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-2">
              {images.map((img, idx) => {
                const selected = idx === previewIndex;
                const isBase = idx === refineBaseIndex;
                const isActive = !!img.is_active;
                return (
                  <button
                    key={img.object_key || img.url || idx}
                    type="button"
                    onClick={() => selectVersion(idx)}
                    className={`relative w-full overflow-hidden rounded-lg ring-2 transition ${
                      isBase ? "ring-brand-500" : selected ? "ring-emerald-400" : "ring-transparent hover:ring-slate-300"
                    }`}
                  >
                    <img
                      src={withMediaAuth(img.url)}
                      alt={`版本 ${idx + 1}`}
                      className="aspect-[9/16] w-full object-cover object-top"
                    />
                    <span className="absolute left-1 top-1 rounded bg-black/55 px-1 py-0.5 text-[9px] text-white">
                      v{idx + 1}
                    </span>
                    {isBase && (
                      <span className="absolute bottom-1 left-1 rounded bg-brand-600/90 px-1 py-0.5 text-[8px] text-white">
                        基准
                      </span>
                    )}
                    {isActive && (
                      <span className="absolute right-1 top-1 rounded-full bg-emerald-500 p-0.5 text-white">
                        <Check className="h-2.5 w-2.5" />
                      </span>
                    )}
                  </button>
                );
              })}
              {!images.length && (
                <p className="px-1 text-center text-[10px] text-slate-400">尚无历史</p>
              )}
            </div>
          </section>
        </div>

        <footer className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-slate-200 bg-slate-50 px-4 py-3">
          <p className="text-[11px] text-slate-500">
            {activeImage
              ? `当前正式立绘：${images.findIndex((i) => i.object_key === activeImage.object_key) + 1 || "?"} / ${images.length}`
              : "尚未选定正式立绘"}
          </p>
          <div className="flex gap-2">
            <button type="button" className="btn-secondary text-xs" onClick={onClose}>
              关闭
            </button>
            <button
              type="button"
              className="btn-primary text-xs"
              disabled={!preview?.object_key || previewIsActive || adopting}
              onClick={handleAdopt}
            >
              {adopting ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Check className="h-3.5 w-3.5" />
              )}
              采用此版本
            </button>
          </div>
        </footer>
      </div>

      {lightboxSrc && (
        <ImageLightbox
          src={lightboxSrc}
          title={`${characterName} · 立绘预览`}
          caption={preview?.prompt}
          onClose={() => setLightboxSrc(null)}
        />
      )}
    </div>,
    document.body,
  );
}
