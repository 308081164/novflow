import { useState } from "react";
import { Loader2, Sparkles, Wand2, ZoomIn } from "lucide-react";
import type { GeneratedImage } from "../api";
import { withMediaAuth } from "../api";
import ImageLightbox from "./ImageLightbox";

type Props = {
  images: GeneratedImage[];
  onRefine?: (image: GeneratedImage, prompt: string) => Promise<void>;
  compact?: boolean;
  aspectRatio?: "9/16" | "16/9" | "1/1";
};

const ASPECT_CLASS: Record<NonNullable<Props["aspectRatio"]>, string> = {
  "9/16": "aspect-[9/16]",
  "16/9": "aspect-video",
  "1/1": "aspect-square",
};

function sourceBadge(prompt?: string) {
  if (prompt?.includes("用户上传")) {
    return { label: "上传", className: "bg-slate-700/85" };
  }
  return { label: "AI", className: "bg-brand-600/85" };
}

export default function GeneratedImageGallery({ images, onRefine, compact, aspectRatio }: Props) {
  const [refinePrompt, setRefinePrompt] = useState("");
  const [refiningKey, setRefiningKey] = useState<string | null>(null);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [lightbox, setLightbox] = useState<{ src: string; alt?: string; caption?: string } | null>(null);

  if (!images.length) return null;

  const handleRefine = async (img: GeneratedImage) => {
    if (!onRefine || !refinePrompt.trim()) return;
    setRefiningKey(img.object_key || img.url);
    try {
      await onRefine(img, refinePrompt.trim());
      setRefinePrompt("");
      setActiveKey(null);
    } finally {
      setRefiningKey(null);
    }
  };

  return (
    <div className={`grid gap-3 ${compact ? "grid-cols-1" : "grid-cols-1 sm:grid-cols-2"}`}>
      {images.map((img) => {
        const badge = sourceBadge(img.prompt);
        return (
        <div key={img.object_key || img.url} className="rounded-xl border border-slate-200 bg-white p-2 shadow-sm">
          <div className={`relative overflow-hidden rounded-lg ${aspectRatio ? ASPECT_CLASS[aspectRatio] : ""}`}>
            <img
              src={withMediaAuth(img.url)}
              alt={img.prompt || "生成图片"}
              className={`w-full rounded-lg object-cover ${aspectRatio === "9/16" ? "object-top " : ""}${aspectRatio ? "h-full" : ""}`}
              style={aspectRatio ? undefined : { maxHeight: compact ? 200 : 320 }}
            />
            <span className={`absolute left-2 top-2 rounded-md px-1.5 py-0.5 text-[9px] font-medium text-white ${badge.className}`}>
              {badge.label}
            </span>
            <button
              type="button"
              className="absolute right-2 top-2 inline-flex items-center gap-1 rounded-lg bg-black/55 px-2 py-1 text-[10px] font-medium text-white shadow backdrop-blur-sm transition hover:bg-black/70"
              onClick={() =>
                setLightbox({
                  src: withMediaAuth(img.url),
                  alt: img.prompt || "生成图片",
                  caption: img.prompt,
                })
              }
            >
              <ZoomIn className="h-3.5 w-3.5" />
              放大
            </button>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="inline-flex items-center gap-1 text-xs text-brand-600 hover:underline"
              onClick={() =>
                setLightbox({
                  src: withMediaAuth(img.url),
                  alt: img.prompt || "生成图片",
                  caption: img.prompt,
                })
              }
            >
              <ZoomIn className="h-3 w-3" />
              放大查看
            </button>
          </div>
          {img.prompt && (
            <p className="mt-1 line-clamp-2 text-[10px] text-slate-500">{img.prompt}</p>
          )}
          {onRefine && (
            <div className="mt-2">
              {activeKey === (img.object_key || img.url) ? (
                <div className="space-y-2">
                  <input
                    className="input text-xs"
                    placeholder="描述要如何调整这张图…"
                    value={refinePrompt}
                    onChange={(e) => setRefinePrompt(e.target.value)}
                  />
                  <div className="flex gap-2">
                    <button
                      type="button"
                      className="btn-primary py-1 text-xs"
                      disabled={!refinePrompt.trim() || refiningKey === (img.object_key || img.url)}
                      onClick={() => handleRefine(img)}
                    >
                      {refiningKey === (img.object_key || img.url) ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Wand2 className="h-3 w-3" />
                      )}
                      调整
                    </button>
                    <button type="button" className="btn-secondary py-1 text-xs" onClick={() => setActiveKey(null)}>
                      取消
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  type="button"
                  className="text-xs text-brand-600 hover:underline"
                  onClick={() => setActiveKey(img.object_key || img.url)}
                >
                  <Sparkles className="inline h-3 w-3" /> 多轮调整
                </button>
              )}
            </div>
          )}
        </div>
        );
      })}
      {lightbox && (
        <ImageLightbox
          src={lightbox.src}
          alt={lightbox.alt}
          title="图片预览"
          caption={lightbox.caption}
          onClose={() => setLightbox(null)}
        />
      )}
    </div>
  );
}
