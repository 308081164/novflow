import { useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Images, Loader2, Pencil, Sparkles, Star, Trash2, User, ZoomIn } from "lucide-react";
import type { GeneratedImage, SetupCard } from "../api";
import { withMediaAuth } from "../api";
import ImageLightbox from "./ImageLightbox";
import CharacterPortraitStudioModal from "./CharacterPortraitStudioModal";
import ImageUploadButton from "./ImageUploadButton";
import { CharacterBody } from "./setup/SetupCard";

type ViewMode = "settings" | "portrait";

type Props = {
  card: SetupCard;
  images: GeneratedImage[];
  generating?: boolean;
  onEdit: () => void;
  onDelete?: () => Promise<void>;
  onGenerate?: () => Promise<GeneratedImage>;
  onUpload?: (file: File) => Promise<GeneratedImage>;
  onRefine?: (image: GeneratedImage, prompt: string) => Promise<GeneratedImage>;
  onSetActive?: (objectKey: string) => Promise<GeneratedImage[]>;
  onImagesUpdated?: (images: GeneratedImage[]) => void;
};

function resolveDisplayImage(images: GeneratedImage[]) {
  if (!images.length) return null;
  return images.find((img) => img.is_active) || images[images.length - 1];
}

export default function CharacterPortraitCard({
  card,
  images,
  generating,
  onEdit,
  onDelete,
  onGenerate,
  onUpload,
  onRefine,
  onSetActive,
  onImagesUpdated,
}: Props) {
  const [view, setView] = useState<ViewMode>("settings");
  const [studioOpen, setStudioOpen] = useState(false);
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const d = card.data || {};
  const name = String(d.name || card.title || "未命名");
  const charId = d.character_id as number | undefined;

  const displayImg = useMemo(() => resolveDisplayImage(images), [images]);
  const versionCount = images.length;
  const activeIndex = displayImg
    ? images.findIndex((img) => img.object_key === displayImg.object_key)
    : -1;

  const openPreview = () => {
    if (!displayImg) return;
    setLightboxSrc(withMediaAuth(displayImg.url));
  };

  const syncImages = (next: GeneratedImage[]) => {
    onImagesUpdated?.(next);
  };

  const handleDelete = async () => {
    if (!onDelete || deleting) return;
    setDeleting(true);
    try {
      setStudioOpen(false);
      await onDelete();
      setConfirmDelete(false);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <>
      <article className="flex aspect-[9/16] flex-col overflow-hidden rounded-2xl bg-white shadow-md ring-1 ring-emerald-200 shadow-emerald-100/50">
        <header className="shrink-0 bg-gradient-to-r from-emerald-600 to-emerald-500 px-3 py-2 text-white">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <h3 className="truncate text-sm font-bold leading-snug">{name}</h3>
              <div className="mt-1.5 flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setView("settings")}
                  className={`rounded-md px-2 py-0.5 text-[10px] font-medium transition ${
                    view === "settings" ? "bg-white text-emerald-700" : "bg-white/15 hover:bg-white/25"
                  }`}
                >
                  设定
                </button>
                <button
                  type="button"
                  onClick={() => setView("portrait")}
                  className={`rounded-md px-2 py-0.5 text-[10px] font-medium transition ${
                    view === "portrait" ? "bg-white text-emerald-700" : "bg-white/15 hover:bg-white/25"
                  }`}
                >
                  查看形象
                </button>
              </div>
            </div>
            <div className="flex shrink-0 gap-1">
              <button
                type="button"
                onClick={onEdit}
                className="rounded-lg bg-white/15 px-2 py-1 text-[10px] font-medium hover:bg-white/25"
              >
                <Pencil className="inline h-3 w-3" /> 编辑
              </button>
              {charId && onDelete && (
                <button
                  type="button"
                  onClick={() => setConfirmDelete(true)}
                  className="rounded-lg bg-white/15 px-2 py-1 text-[10px] font-medium hover:bg-red-500/80"
                  aria-label="删除角色"
                >
                  <Trash2 className="inline h-3 w-3" />
                </button>
              )}
            </div>
          </div>
        </header>

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-3 py-2">
          {view === "settings" ? (
            <div className="min-h-0 flex-1 overflow-y-auto">
              <CharacterBody data={d} compact />
            </div>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col gap-2">
              <div className="relative min-h-0 flex-1 overflow-hidden rounded-lg bg-slate-100 ring-1 ring-slate-200">
                {displayImg ? (
                  <>
                    <img
                      src={withMediaAuth(displayImg.url)}
                      alt={displayImg.prompt || `${name} 立绘`}
                      className="h-full w-full object-cover object-top"
                    />
                    {displayImg.is_active && (
                      <span className="absolute left-2 top-2 inline-flex items-center gap-0.5 rounded-md bg-emerald-600/90 px-1.5 py-0.5 text-[9px] font-medium text-white">
                        <Star className="h-2.5 w-2.5 fill-current" />
                        正式
                      </span>
                    )}
                    <button
                      type="button"
                      className="absolute right-2 top-2 inline-flex items-center gap-1 rounded-lg bg-black/55 px-2 py-1 text-[10px] font-medium text-white shadow backdrop-blur-sm transition hover:bg-black/70"
                      onClick={openPreview}
                    >
                      <ZoomIn className="h-3.5 w-3.5" />
                      放大
                    </button>
                  </>
                ) : (
                  <div className="flex h-full flex-col items-center justify-center gap-2 px-4 text-center text-xs text-slate-500">
                    <User className="h-8 w-8 text-slate-300" />
                    <p>尚无立绘，可上传或打开立绘工坊生成</p>
                  </div>
                )}
              </div>

              <div className="shrink-0 space-y-1.5">
                {displayImg && (
                  <p className="text-center text-[10px] text-slate-400">
                    {versionCount > 1
                      ? `正式 v${activeIndex + 1} · 共 ${versionCount} 版`
                      : "共 1 版"}
                  </p>
                )}

                {charId && onGenerate && onRefine && onSetActive && (
                  <button
                    type="button"
                    className="btn-primary w-full py-1 text-xs"
                    onClick={() => setStudioOpen(true)}
                  >
                    <Images className="h-3.5 w-3.5" />
                    立绘工坊
                  </button>
                )}

                {!displayImg && onUpload && (
                  <ImageUploadButton
                    label="上传立绘"
                    className="btn-secondary w-full py-1 text-xs"
                    disabled={generating}
                    onUpload={async (file) => {
                      const img = await onUpload(file);
                      syncImages([...images, img]);
                    }}
                  />
                )}

                {!displayImg && onGenerate && (
                  <button
                    type="button"
                    className="btn-secondary w-full py-1 text-xs"
                    disabled={generating}
                    onClick={async () => {
                      const img = await onGenerate();
                      syncImages([...images, img]);
                    }}
                  >
                    {generating ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Sparkles className="h-3.5 w-3.5" />
                    )}
                    AI 生成立绘
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </article>

      {studioOpen && charId && onGenerate && onRefine && onSetActive && (
        <CharacterPortraitStudioModal
          characterName={name}
          images={images}
          onClose={() => setStudioOpen(false)}
          onGenerate={onGenerate}
          onUpload={onUpload}
          onRefine={onRefine}
          onSetActive={async (objectKey) => {
            const updated = await onSetActive(objectKey);
            syncImages(updated);
            return updated;
          }}
        />
      )}

      {lightboxSrc && (
        <ImageLightbox
          src={lightboxSrc}
          alt={`${name} 立绘`}
          title={`${name} · 角色立绘`}
          caption={displayImg?.prompt}
          onClose={() => setLightboxSrc(null)}
        />
      )}

      {confirmDelete &&
        onDelete &&
        createPortal(
          <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50 p-4">
            <div className="card w-full max-w-sm p-5 shadow-xl">
              <h3 className="text-base font-semibold text-slate-900">删除角色卡</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">
                确定删除「{name}」？此操作不可撤销，该角色的设定与全部立绘版本将被永久移除。
              </p>
              <div className="mt-4 flex justify-end gap-2">
                <button
                  type="button"
                  className="btn-secondary text-xs"
                  disabled={deleting}
                  onClick={() => setConfirmDelete(false)}
                >
                  取消
                </button>
                <button
                  type="button"
                  className="inline-flex items-center gap-1 rounded-lg bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-60"
                  disabled={deleting}
                  onClick={handleDelete}
                >
                  {deleting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                  确认删除
                </button>
              </div>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
