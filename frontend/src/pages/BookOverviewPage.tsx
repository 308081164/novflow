import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  Download,
  Globe,
  ImageIcon,
  ListTree,
  Loader2,
  PenLine,
  Sparkles,
  Users,
  Wand2,
  ZoomIn,
} from "lucide-react";
import { api, Book, Chapter, GeneratedImage, getToken, withMediaAuth } from "../api";
import { Badge } from "../components/Layout";
import GeneratedImageGallery from "../components/GeneratedImageGallery";
import ImageLightbox from "../components/ImageLightbox";
import ImageUploadButton from "../components/ImageUploadButton";

type ChapterFilter = "all" | "draft" | "approved" | "empty";

const WORKSPACE_GROUPS = [
  {
    title: "设定与资料",
    items: [
      { to: "worldview", icon: Globe, label: "世界观", desc: "时代 · 舞台 · 禁忌", color: "text-sky-600 bg-sky-50" },
      { to: "characters", icon: Users, label: "角色卡", desc: "立绘 · 人设 · AI", color: "text-violet-600 bg-violet-50" },
      { to: "outline", icon: ListTree, label: "章节规划", desc: "大纲与梗核", color: "text-emerald-600 bg-emerald-50" },
      { to: "resources", icon: BookOpen, label: "写作偏好", desc: "文风 · 语料库", color: "text-amber-600 bg-amber-50" },
    ],
  },
  {
    title: "工具",
    items: [
      { to: "setup", icon: Wand2, label: "创作向导", desc: "AI 助手完善设定", color: "text-brand-600 bg-brand-50" },
    ],
  },
] as const;

function chapterStatus(ch: Chapter) {
  if (ch.approved) return "approved" as const;
  if (ch.content?.trim()) return "draft" as const;
  return "empty" as const;
}

export default function BookOverviewPage() {
  const { bookId } = useParams();
  const id = Number(bookId);
  const [book, setBook] = useState<Book | null>(null);
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [coverImage, setCoverImage] = useState<GeneratedImage | null>(null);
  const [generatingCover, setGeneratingCover] = useState(false);
  const [coverErr, setCoverErr] = useState("");
  const [coverLightbox, setCoverLightbox] = useState(false);
  const [showCoverRefine, setShowCoverRefine] = useState(false);
  const [chapterFilter, setChapterFilter] = useState<ChapterFilter>("all");

  useEffect(() => {
    if (!id) return;
    Promise.all([api.book(id), api.chapters(id), api.getCover(id)]).then(([b, c, cover]) => {
      setBook(b);
      setChapters(c);
      if (cover.url) {
        setCoverImage({ url: cover.url, object_key: cover.object_key, kind: "cover" });
      } else if (b.cover_image_url) {
        setCoverImage({ url: b.cover_image_url, kind: "cover" });
      } else {
        setCoverImage(null);
      }
    });
  }, [id]);

  const plannedTotal = book?.planned_chapters || book?.target_chapters || book?.chapter_count || 0;
  const progress = book && plannedTotal ? Math.round((book.written_count / plannedTotal) * 100) : 0;
  const needsSetup = book ? book.setup_step < 5 && book.template_id === "blank" : false;

  const continueChapter = useMemo(() => {
    if (!chapters.length) return 1;
    const draft = chapters.find((ch) => !ch.approved && ch.content?.trim());
    if (draft) return draft.chapter_no;
    const empty = chapters.find((ch) => !ch.content?.trim());
    if (empty) return empty.chapter_no;
    return chapters[chapters.length - 1]?.chapter_no ?? 1;
  }, [chapters]);

  const filteredChapters = useMemo(() => {
    if (chapterFilter === "all") return chapters;
    return chapters.filter((ch) => chapterStatus(ch) === chapterFilter);
  }, [chapters, chapterFilter]);

  const generateCover = async () => {
    setGeneratingCover(true);
    setCoverErr("");
    try {
      const img = await api.generateCover(id);
      setCoverImage(img);
      setBook(await api.book(id));
    } catch (e) {
      setCoverErr(String(e));
    } finally {
      setGeneratingCover(false);
    }
  };

  const uploadCover = async (file: File) => {
    setCoverErr("");
    const img = await api.uploadCover(id, file);
    setCoverImage(img);
    setBook(await api.book(id));
  };

  const refineCover = async (img: GeneratedImage, prompt: string) => {
    const refined = await api.refineImage(id, {
      kind: "cover",
      prompt,
      parent_object_key: img.object_key,
    });
    setCoverImage(refined);
    setShowCoverRefine(false);
  };

  const exportTxt = (e: React.MouseEvent) => {
    e.preventDefault();
    fetch(api.exportUrl(id), { headers: { Authorization: `Bearer ${getToken()}` } })
      .then((r) => r.blob())
      .then((blob) => {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `${book?.title ?? "book"}.txt`;
        a.click();
      });
  };

  if (!book) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
      </div>
    );
  }

  const genreLabel = book.genre?.split(/[/·]/)[0]?.trim() || "网文";

  return (
    <div className="space-y-8 pb-10">
      {/* 面包屑 */}
      <Link
        to="/dashboard"
        className="inline-flex items-center gap-1.5 text-sm text-slate-500 transition hover:text-brand-700"
      >
        <ArrowLeft className="h-4 w-4" />
        返回书库
      </Link>

      {/* Hero：封面 + 书籍信息 */}
      <section className="overflow-hidden rounded-2xl border border-slate-200/70 bg-white shadow-sm">
        <div className="bg-gradient-to-br from-slate-50/80 via-white to-brand-50/40 px-6 py-8 lg:px-10 lg:py-10">
          <div className="flex flex-col gap-8 lg:flex-row lg:items-start lg:gap-10">
            {/* 封面区 */}
            <div className="mx-auto shrink-0 lg:mx-0">
              <div className="group relative w-[168px]">
                {coverImage ? (
                  <button
                    type="button"
                    className="relative block w-full overflow-hidden rounded-xl shadow-lg ring-1 ring-black/5 transition hover:shadow-xl"
                    onClick={() => setCoverLightbox(true)}
                  >
                    <img
                      src={withMediaAuth(coverImage.url)}
                      alt={`${book.title} 封面`}
                      className="aspect-[2/3] w-full object-cover object-top"
                    />
                    <span className="absolute inset-0 flex items-center justify-center bg-black/0 opacity-0 transition group-hover:bg-black/20 group-hover:opacity-100">
                      <ZoomIn className="h-8 w-8 text-white drop-shadow" />
                    </span>
                  </button>
                ) : (
                  <div className="flex aspect-[2/3] w-full flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-200 bg-slate-50/80 text-slate-400">
                    <ImageIcon className="mb-2 h-10 w-10 opacity-40" />
                    <span className="text-xs">暂无封面</span>
                  </div>
                )}
              </div>
              <div className="mt-3 flex flex-col gap-1.5">
                <ImageUploadButton
                  label="上传封面"
                  className="btn-secondary w-full justify-center py-1.5 text-xs"
                  disabled={generatingCover}
                  onUpload={uploadCover}
                  onError={setCoverErr}
                />
                <button
                  type="button"
                  className="btn-primary w-full justify-center py-1.5 text-xs"
                  onClick={generateCover}
                  disabled={generatingCover}
                >
                  {generatingCover ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Sparkles className="h-3.5 w-3.5" />
                  )}
                  AI 生成
                </button>
                {coverImage && (
                  <button
                    type="button"
                    className="text-xs text-brand-600 hover:underline"
                    onClick={() => setShowCoverRefine((v) => !v)}
                  >
                    {showCoverRefine ? "收起调整" : "微调封面"}
                  </button>
                )}
              </div>
              {coverErr && <p className="mt-2 text-xs text-red-600">{coverErr}</p>}
              {showCoverRefine && coverImage && (
                <div className="mt-3">
                  <GeneratedImageGallery images={[coverImage]} onRefine={refineCover} aspectRatio="9/16" />
                </div>
              )}
            </div>

            {/* 信息区 */}
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-brand-100 px-2.5 py-0.5 text-xs font-medium text-brand-800">
                  {genreLabel}
                </span>
                {needsSetup && (
                  <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-800">
                    设定 {book.setup_step}/5
                  </span>
                )}
              </div>

              <h1 className="mt-3 text-2xl font-bold leading-snug text-slate-900 lg:text-3xl">{book.title}</h1>

              {(book.premise || book.blurb) && (
                <p className="mt-3 max-w-2xl text-sm leading-relaxed text-slate-600">
                  {book.premise || book.blurb}
                </p>
              )}

              {/* 进度条 */}
              <div className="mt-6 max-w-md">
                <div className="mb-1.5 flex items-end justify-between text-xs">
                  <span className="font-medium text-slate-700">写作进度</span>
                  <span className="text-slate-500">
                    {book.written_count}/{plannedTotal} 章 · {progress}%
                  </span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-brand-500 to-brand-600 transition-all"
                    style={{ width: `${Math.max(progress, book.written_count > 0 ? 4 : 0)}%` }}
                  />
                </div>
              </div>

              {/* 统计 */}
              <div className="mt-5 flex flex-wrap gap-6">
                <div>
                  <div className="text-2xl font-bold tabular-nums text-slate-900">{plannedTotal}</div>
                  <div className="text-xs text-slate-500">规划章节</div>
                </div>
                <div>
                  <div className="text-2xl font-bold tabular-nums text-brand-700">{book.written_count}</div>
                  <div className="text-xs text-slate-500">已写</div>
                </div>
                <div>
                  <div className="text-2xl font-bold tabular-nums text-emerald-700">{book.approved_count}</div>
                  <div className="text-xs text-slate-500">已定稿</div>
                </div>
                {book.genre && (
                  <div className="hidden min-w-0 sm:block">
                    <div className="truncate text-sm font-medium text-slate-800">{book.genre}</div>
                    <div className="text-xs text-slate-500">类型定位</div>
                  </div>
                )}
              </div>

              {/* 主操作 */}
              <div className="mt-6 flex flex-wrap gap-3">
                <Link to={`/books/${id}/write/${continueChapter}`} className="btn-primary inline-flex px-5">
                  <PenLine className="h-4 w-4" />
                  继续写作
                  <span className="ml-1 text-xs opacity-80">第{String(continueChapter).padStart(3, "0")}章</span>
                </Link>
                {needsSetup && (
                  <Link to={`/books/${id}/setup`} className="btn-secondary inline-flex">
                    <Wand2 className="h-4 w-4" />
                    完善设定
                  </Link>
                )}
                <button type="button" className="btn-secondary inline-flex" onClick={exportTxt}>
                  <Download className="h-4 w-4" />
                  导出 TXT
                </button>
              </div>
            </div>
          </div>
        </div>

        {needsSetup && (
          <div className="border-t border-amber-100 bg-amber-50/80 px-6 py-3 lg:px-10">
            <p className="text-sm text-amber-900">
              本书尚未完成创建设定，建议先与 AI 助手完善世界观、角色与大纲，再进入正文写作。
            </p>
          </div>
        )}
      </section>

      {/* 工作台快捷入口 */}
      <section>
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-400">创作工作台</h2>
        <div className="grid gap-4 lg:grid-cols-3">
          {/* 写作主入口 — 突出展示 */}
          <Link
            to={`/books/${id}/write/${continueChapter}`}
            className="group relative overflow-hidden rounded-2xl border border-brand-200 bg-gradient-to-br from-brand-600 to-brand-700 p-5 text-white shadow-md transition hover:shadow-lg lg:col-span-1"
          >
            <div className="relative z-10">
              <PenLine className="h-8 w-8 opacity-90" />
              <h3 className="mt-3 text-lg font-semibold">章节编辑器</h3>
              <p className="mt-1 text-sm text-brand-100">AI 辅助写作 · 合规检查 · 插图生成</p>
              <span className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-white/90 group-hover:gap-2 transition-all">
                进入编辑
                <ChevronRight className="h-4 w-4" />
              </span>
            </div>
            <div className="pointer-events-none absolute -right-6 -top-6 h-32 w-32 rounded-full bg-white/10" />
          </Link>

          {/* 设定与工具 */}
          <div className="space-y-4 lg:col-span-2">
            {WORKSPACE_GROUPS.map((group) => (
              <div key={group.title}>
                <p className="mb-2 text-xs font-medium text-slate-500">{group.title}</p>
                <div className="grid gap-2 sm:grid-cols-2">
                  {group.items.map((item) => {
                    const Icon = item.icon;
                    return (
                      <Link
                        key={item.to}
                        to={`/books/${id}/${item.to}`}
                        className="group flex items-center gap-3 rounded-xl border border-slate-200/80 bg-white p-3.5 transition hover:border-brand-200 hover:shadow-sm"
                      >
                        <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${item.color}`}>
                          <Icon className="h-5 w-5" />
                        </div>
                        <div className="min-w-0">
                          <div className="font-medium text-slate-900 group-hover:text-brand-800">{item.label}</div>
                          <div className="truncate text-xs text-slate-500">{item.desc}</div>
                        </div>
                        <ChevronRight className="ml-auto h-4 w-4 shrink-0 text-slate-300 group-hover:text-brand-400" />
                      </Link>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* 章节列表 */}
      <section className="overflow-hidden rounded-2xl border border-slate-200/70 bg-white shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
          <div>
            <h2 className="font-semibold text-slate-900">章节列表</h2>
            <p className="text-xs text-slate-500">
              共 {plannedTotal} 章规划
              {book.outline_planned_count > 0 && (
                <span className="text-slate-400"> · 已规划大纲 {book.outline_planned_count} 章</span>
              )}
            </p>
          </div>
          <div className="flex flex-wrap gap-1 rounded-lg bg-slate-100 p-1">
            {(
              [
                ["all", "全部"],
                ["draft", "草稿"],
                ["approved", "定稿"],
                ["empty", "未写"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setChapterFilter(key)}
                className={`rounded-md px-3 py-1 text-xs font-medium transition ${
                  chapterFilter === key
                    ? "bg-white text-brand-700 shadow-sm"
                    : "text-slate-600 hover:text-slate-900"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="divide-y divide-slate-50">
          {filteredChapters.length === 0 ? (
            <p className="px-5 py-8 text-center text-sm text-slate-500">没有符合筛选条件的章节</p>
          ) : (
            filteredChapters.map((ch) => {
              const status = chapterStatus(ch);
              return (
                <Link
                  key={ch.chapter_no}
                  to={`/books/${id}/write/${ch.chapter_no}`}
                  className="group flex items-center gap-4 px-5 py-3.5 transition hover:bg-slate-50/80"
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-xs font-bold tabular-nums text-slate-600 group-hover:bg-brand-50 group-hover:text-brand-700">
                    {String(ch.chapter_no).padStart(2, "0")}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium text-slate-800 group-hover:text-brand-800">
                      {ch.title || `第 ${ch.chapter_no} 章`}
                    </div>
                    {ch.word_count > 0 && (
                      <div className="text-xs text-slate-400">{ch.word_count.toLocaleString()} 字</div>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {status === "approved" && (
                      <Badge color="green">
                        <CheckCircle2 className="mr-0.5 inline h-3 w-3" />
                        定稿
                      </Badge>
                    )}
                    {status === "draft" && <Badge color="blue">草稿</Badge>}
                    {status === "empty" && <Badge color="slate">未写</Badge>}
                    <ChevronRight className="h-4 w-4 text-slate-300 group-hover:text-brand-400" />
                  </div>
                </Link>
              );
            })
          )}
        </div>
      </section>

      {coverLightbox && coverImage && (
        <ImageLightbox
          src={withMediaAuth(coverImage.url)}
          alt={`${book.title} 封面`}
          title="封面预览"
          onClose={() => setCoverLightbox(false)}
        />
      )}
    </div>
  );
}
