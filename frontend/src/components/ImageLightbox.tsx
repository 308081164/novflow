import { useEffect } from "react";
import { createPortal } from "react-dom";
import { X, ZoomIn } from "lucide-react";

export type ImageLightboxProps = {
  src: string;
  alt?: string;
  title?: string;
  caption?: string;
  onClose: () => void;
};

export default function ImageLightbox({ src, alt, title, caption, onClose }: ImageLightboxProps) {
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex flex-col bg-black/90"
      role="dialog"
      aria-modal="true"
      aria-label={title || "放大查看"}
    >
      <div
        className="flex shrink-0 items-center justify-between gap-3 border-b border-white/10 px-4 py-3 text-white"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex min-w-0 items-center gap-2">
          <ZoomIn className="h-4 w-4 shrink-0 text-white/80" />
          <span className="truncate text-sm font-medium">{title || alt || "放大查看"}</span>
        </div>
        <button
          type="button"
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-white/10 px-3 py-1.5 text-xs font-medium hover:bg-white/20"
          onClick={onClose}
        >
          <X className="h-4 w-4" />
          关闭
        </button>
      </div>

      <div
        className="flex min-h-0 flex-1 items-center justify-center p-4"
        onClick={onClose}
      >
        <img
          src={src}
          alt={alt || title || "放大查看"}
          className="max-h-[calc(100vh-8rem)] max-w-[min(96vw,32rem)] rounded-lg object-contain shadow-2xl ring-1 ring-white/10"
          onClick={(e) => e.stopPropagation()}
        />
      </div>

      <div
        className="shrink-0 border-t border-white/10 px-4 py-3 text-center"
        onClick={(e) => e.stopPropagation()}
      >
        {caption && (
          <p className="mx-auto mb-2 max-w-2xl line-clamp-3 text-xs leading-relaxed text-white/70">
            {caption}
          </p>
        )}
        <p className="text-[10px] text-white/40">点击空白处或按 Esc 关闭</p>
      </div>
    </div>,
    document.body,
  );
}
