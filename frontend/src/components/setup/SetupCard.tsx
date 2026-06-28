import { useEffect, useMemo, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Globe,
  GitBranch,
  Hash,
  ListTree,
  Pencil,
  Sparkles,
  User,
  BookOpen,
} from "lucide-react";
import type { SetupCard } from "../../api";
import OutlineTimeline, { cardDataToTimelineChapters, type TimelineChapter } from "./OutlineTimeline";
import PlotFrameworkBody from "./PlotFramework";

const TYPE_META: Record<
  string,
  {
    icon: typeof Sparkles;
    accent: string;
    header: string;
    badge: string;
    label: string;
  }
> = {
  premise: {
    icon: Sparkles,
    accent: "ring-violet-200 shadow-violet-100/50",
    header: "from-violet-600 to-violet-500",
    badge: "bg-violet-100 text-violet-800",
    label: "作品定位",
  },
  worldview: {
    icon: Globe,
    accent: "ring-sky-200 shadow-sky-100/50",
    header: "from-sky-600 to-sky-500",
    badge: "bg-sky-100 text-sky-800",
    label: "世界观",
  },
  character: {
    icon: User,
    accent: "ring-emerald-200 shadow-emerald-100/50",
    header: "from-emerald-600 to-emerald-500",
    badge: "bg-emerald-100 text-emerald-800",
    label: "角色卡",
  },
  outline: {
    icon: ListTree,
    accent: "ring-amber-200 shadow-amber-100/50",
    header: "from-amber-600 to-amber-500",
    badge: "bg-amber-100 text-amber-800",
    label: "章节大纲",
  },
  plot: {
    icon: GitBranch,
    accent: "ring-rose-200 shadow-rose-100/50",
    header: "from-rose-600 to-rose-500",
    badge: "bg-rose-100 text-rose-800",
    label: "剧情走向",
  },
  writing_prefs: {
    icon: BookOpen,
    accent: "ring-indigo-200 shadow-indigo-100/50",
    header: "from-indigo-600 to-indigo-500",
    badge: "bg-indigo-100 text-indigo-800",
    label: "写作偏好",
  },
};

type Props = {
  card: SetupCard;
  onApply?: (card: SetupCard) => void;
  onEdit?: (card: SetupCard, outlineChapter?: TimelineChapter) => void;
  applying?: boolean;
  compact?: boolean;
  outlineChapter?: TimelineChapter;
  scrollableBody?: boolean;
};

export default function SetupCardView({
  card,
  onApply,
  onEdit,
  applying,
  compact,
  outlineChapter,
  scrollableBody,
}: Props) {
  const meta = TYPE_META[card.type] || {
    icon: Sparkles,
    accent: "ring-slate-200",
    header: "from-slate-600 to-slate-500",
    badge: "bg-slate-100 text-slate-800",
    label: card.type,
  };
  const Icon = meta.icon;
  const d = card.data || {};
  const applied = card.status === "applied";

  return (
    <article
      className={`overflow-hidden rounded-2xl bg-white shadow-md ring-1 ${meta.accent} ${applied ? "opacity-90" : ""}`}
    >
      <header className={`bg-gradient-to-r ${meta.header} px-4 py-3 text-white`}>
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2 min-w-0">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/20">
              <Icon className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${meta.badge} !text-inherit bg-white/90`}>
                  {meta.label}
                </span>
                {applied && (
                  <span className="flex items-center gap-1 rounded-full bg-white/20 px-2 py-0.5 text-[10px]">
                    <Check className="h-3 w-3" /> 已采纳
                  </span>
                )}
              </div>
              <h4 className="mt-1 truncate text-sm font-bold leading-snug">
                {outlineChapter
                  ? `第 ${outlineChapter.chapter_no} 章 · ${outlineChapter.title || card.title || meta.label}`
                  : card.title || meta.label}
              </h4>
            </div>
          </div>
          {(onEdit || (!applied && onApply)) && (
            <div className="flex shrink-0 gap-1.5">
              {onEdit && (
                <button
                  type="button"
                  onClick={() => onEdit(card, outlineChapter)}
                  className="rounded-lg bg-white/15 px-2 py-1 text-xs font-medium hover:bg-white/25"
                >
                  <Pencil className="inline h-3 w-3" /> 编辑
                </button>
              )}
              {!applied && onApply && (
                <button
                  type="button"
                  onClick={() => onApply(card)}
                  disabled={applying}
                  className="rounded-lg bg-white px-2.5 py-1 text-xs font-semibold text-slate-800 hover:bg-white/90 disabled:opacity-60"
                >
                  {applying ? "…" : "采纳"}
                </button>
              )}
            </div>
          )}
        </div>
      </header>

      <div
        className={`px-4 py-3 ${compact ? "text-xs" : "text-sm"} ${scrollableBody ? "max-h-72 overflow-y-auto" : ""}`}
      >
        {card.type === "premise" && <PremiseBody data={d} />}
        {card.type === "worldview" && <WorldviewBody data={d} />}
        {card.type === "character" && <CharacterBody data={d} />}
        {card.type === "plot" && <PlotBody data={d} />}
        {card.type === "outline" && <OutlineBody data={d} singleChapter={outlineChapter} />}
        {card.type === "writing_prefs" && <WritingPrefsBody data={d} />}
      </div>
    </article>
  );
}

function PremiseBody({ data }: { data: Record<string, unknown> }) {
  const genres = String(data.genre || "")
    .split(/[/·、,，]/)
    .map((s) => s.trim())
    .filter(Boolean);
  return (
    <div className="space-y-3">
      {data.title && (
        <div className="text-base font-bold text-slate-900">{String(data.title)}</div>
      )}
      {genres.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {genres.map((g) => (
            <span key={g} className="rounded-md bg-violet-50 px-2 py-0.5 text-xs font-medium text-violet-700 ring-1 ring-violet-100">
              {g}
            </span>
          ))}
        </div>
      )}
      {data.premise && (
        <blockquote className="border-l-4 border-violet-300 pl-3 text-slate-700 leading-relaxed">
          {String(data.premise)}
        </blockquote>
      )}
      {!data.premise && data.blurb && (
        <blockquote className="border-l-4 border-violet-300 pl-3 text-slate-700 leading-relaxed">
          {String(data.blurb)}
        </blockquote>
      )}
      {data.target_chapters && (
        <div className="inline-flex items-center gap-1.5 rounded-lg bg-slate-50 px-3 py-1.5 text-xs text-slate-600">
          <Hash className="h-3.5 w-3.5" />
          计划 <strong className="text-slate-900">{String(data.target_chapters)}</strong> 章
        </div>
      )}
    </div>
  );
}

function WorldviewBody({ data }: { data: Record<string, unknown> }) {
  const chips = [
    data.era && { k: "时代", v: String(data.era) },
    data.setting && { k: "舞台", v: String(data.setting) },
    data.tone && { k: "基调", v: String(data.tone) },
  ].filter(Boolean) as { k: string; v: string }[];

  return (
    <div className="space-y-3">
      {chips.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-3">
          {chips.map((c) => (
            <div key={c.k} className="rounded-lg bg-sky-50/80 px-2.5 py-2 ring-1 ring-sky-100">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-sky-600">{c.k}</div>
              <div className="mt-0.5 text-xs font-medium text-slate-800 line-clamp-2">{c.v}</div>
            </div>
          ))}
        </div>
      )}
      {data.timeline_text && <ExpandBlock label="时间线" text={String(data.timeline_text)} />}
      {data.taboos && <ExpandBlock label="禁忌" text={String(data.taboos)} />}
      {data.content && <ExpandBlock label="世界观详述" text={String(data.content)} defaultOpen />}
    </div>
  );
}

export function CharacterBody({ data, compact }: { data: Record<string, unknown>; compact?: boolean }) {
  const name = String(data.name || "未命名");
  const initial = name.charAt(0);
  const roleLabels: Record<string, string> = {
    protagonist: "主角",
    antagonist: "反派",
    support: "配角",
  };
  const role = roleLabels[String(data.role)] || String(data.role || "");

  return (
    <div className={`space-y-2 ${compact ? "text-xs" : "space-y-3 text-sm"}`}>
      <div className="flex items-center gap-2">
        <div
          className={`flex shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-emerald-400 to-emerald-600 font-bold text-white ${
            compact ? "h-8 w-8 text-sm" : "h-12 w-12 text-lg"
          }`}
        >
          {initial}
        </div>
        <div className="min-w-0">
          {!compact && <div className="text-base font-bold text-slate-900">{name}</div>}
          {role && (
            <span className="inline-block rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-800">
              {role}
            </span>
          )}
        </div>
      </div>
      {data.summary && (
        <p className={`text-slate-600 leading-relaxed ${compact ? "line-clamp-4" : ""}`}>
          {String(data.summary)}
        </p>
      )}
      {data.voice_notes && (
        <div className="rounded-lg bg-emerald-50/60 px-2 py-1.5 text-[10px] text-emerald-900 ring-1 ring-emerald-100">
          <span className="font-semibold">说话风格 · </span>
          {String(data.voice_notes)}
        </div>
      )}
      {data.content && <ExpandBlock label="完整角色卡" text={String(data.content)} />}
    </div>
  );
}

function PlotBody({ data }: { data: Record<string, unknown> }) {
  return <PlotFrameworkBody data={data} />;
}

function OutlineBody({
  data,
  singleChapter,
}: {
  data: Record<string, unknown>;
  singleChapter?: TimelineChapter;
}) {
  const chapters = singleChapter ? [singleChapter] : cardDataToTimelineChapters(data);
  if (!chapters.length) return <p className="text-xs text-slate-500">暂无章节数据</p>;
  return <OutlineTimeline chapters={chapters} compact single={!!singleChapter} />;
}

function WritingPrefsBody({ data }: { data: Record<string, unknown> }) {
  const content = String(data.content || "").trim();
  if (!content || content === "（尚未配置）") {
    return (
      <p className="text-xs text-slate-500">
        尚未配置本书写作偏好。可在「写作偏好与语料库」页面编辑，或在此卡片点编辑后采纳。
      </p>
    );
  }
  return (
    <div className="space-y-2">
      <p className="text-[10px] text-slate-400">平台合规规约由系统自动注入，此处仅展示作者偏好。</p>
      <ExpandBlock label="本书写作偏好" text={content} defaultOpen />
    </div>
  );
}

function ExpandBlock({ label, text, defaultOpen = false }: { label: string; text: string; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen || text.length < 180);
  const long = text.length > 180;
  return (
    <div className="rounded-lg bg-slate-50 ring-1 ring-slate-100">
      <button
        type="button"
        className="flex w-full items-center justify-between px-3 py-2 text-left text-xs font-semibold text-slate-600"
        onClick={() => long && setOpen(!open)}
      >
        {label}
        {long && (open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />)}
      </button>
      {(open || !long) && <p className="whitespace-pre-wrap border-t border-slate-100 px-3 py-2 text-xs leading-relaxed text-slate-700">{text}</p>}
    </div>
  );
}

function timelineChapterToCardData(ch: TimelineChapter): Record<string, unknown> {
  return {
    chapter_no: ch.chapter_no,
    title: ch.title || "",
    plot_points: ch.plot_points || "",
    scene: ch.scene || "",
    comedy_core: ch.comedy_core || "",
    cast: ch.cast || [],
    events: ch.events || [],
    entrances: ch.entrances || [],
    exits: ch.exits || [],
  };
}

function parseListInput(text: string): string[] {
  return text
    .split(/[\n,，、]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function OutlineChapterEditor({
  chapter,
  onChange,
}: {
  chapter: TimelineChapter;
  onChange: (ch: TimelineChapter) => void;
}) {
  const set = (key: keyof TimelineChapter, val: string | string[]) => {
    onChange({ ...chapter, [key]: val });
  };

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="label">章号</label>
          <input className="input bg-slate-50" value={chapter.chapter_no} readOnly />
        </div>
        <div>
          <label className="label">场景</label>
          <input
            className="input"
            value={chapter.scene || ""}
            onChange={(e) => set("scene", e.target.value)}
          />
        </div>
      </div>
      <div>
        <label className="label">章节标题</label>
        <input
          className="input"
          value={chapter.title || ""}
          onChange={(e) => set("title", e.target.value)}
        />
      </div>
      <div>
        <label className="label">情节要点</label>
        <textarea
          className="input min-h-[120px]"
          value={chapter.plot_points || ""}
          onChange={(e) => set("plot_points", e.target.value)}
        />
      </div>
      <div>
        <label className="label">梗核 / 喜剧点</label>
        <input
          className="input"
          value={chapter.comedy_core || ""}
          onChange={(e) => set("comedy_core", e.target.value)}
        />
      </div>
      <div>
        <label className="label">出场角色（逗号或换行分隔）</label>
        <textarea
          className="input min-h-[60px]"
          value={(chapter.cast || []).join("、")}
          onChange={(e) => set("cast", parseListInput(e.target.value))}
        />
      </div>
      <div>
        <label className="label">关键事件（每行一条）</label>
        <textarea
          className="input min-h-[80px]"
          value={(chapter.events || []).join("\n")}
          onChange={(e) => set("events", e.target.value.split("\n").map((s) => s.trim()).filter(Boolean))}
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="label">新登场（逗号分隔）</label>
          <input
            className="input"
            value={(chapter.entrances || []).join("、")}
            onChange={(e) => set("entrances", parseListInput(e.target.value))}
          />
        </div>
        <div>
          <label className="label">退场（逗号分隔）</label>
          <input
            className="input"
            value={(chapter.exits || []).join("、")}
            onChange={(e) => set("exits", parseListInput(e.target.value))}
          />
        </div>
      </div>
    </div>
  );
}

export function SetupCardEditModal({
  card,
  outlineChapter,
  onSave,
  onClose,
}: {
  card: SetupCard;
  outlineChapter?: TimelineChapter;
  onSave: (card: SetupCard) => void;
  onClose: () => void;
}) {
  const [data, setData] = useState<Record<string, unknown>>(() => ({ ...(card.data || {}) }));
  const set = (key: string, val: string) => setData((prev) => ({ ...prev, [key]: val }));

  const outlineChapters = useMemo(() => cardDataToTimelineChapters(data), [data]);
  const [activeChapterNo, setActiveChapterNo] = useState<number>(
    () => outlineChapter?.chapter_no ?? outlineChapters[0]?.chapter_no ?? 1,
  );
  const [chapterDraft, setChapterDraft] = useState<TimelineChapter>(() => {
    const initial =
      outlineChapter ||
      outlineChapters.find((c) => c.chapter_no === activeChapterNo) ||
      outlineChapters[0] || {
        chapter_no: activeChapterNo,
        title: "",
        plot_points: "",
        scene: "",
        comedy_core: "",
        cast: [],
        events: [],
        entrances: [],
        exits: [],
      };
    return { ...initial };
  });

  useEffect(() => {
    const ch =
      outlineChapter ||
      outlineChapters.find((c) => c.chapter_no === activeChapterNo) ||
      outlineChapters[0];
    if (ch) setChapterDraft({ ...ch });
  }, [card.id, outlineChapter, activeChapterNo, outlineChapters]);

  const fields: { key: string; label: string; multiline?: boolean }[] =
    card.type === "premise"
      ? [
          { key: "title", label: "书名" },
          { key: "genre", label: "类型" },
          { key: "premise", label: "简介/梗概", multiline: true },
          { key: "target_chapters", label: "计划章数" },
        ]
      : card.type === "worldview"
        ? [
            { key: "era", label: "时代" },
            { key: "setting", label: "舞台" },
            { key: "tone", label: "基调" },
            { key: "timeline_text", label: "时间线", multiline: true },
            { key: "taboos", label: "禁忌", multiline: true },
            { key: "content", label: "详述", multiline: true },
          ]
        : card.type === "character"
          ? [
              { key: "name", label: "姓名" },
              { key: "role", label: "角色类型（protagonist/antagonist/support）" },
              { key: "summary", label: "定位", multiline: true },
              { key: "voice_notes", label: "说话风格" },
              { key: "content", label: "角色卡", multiline: true },
            ]
          : card.type === "plot"
            ? [
                { key: "summary", label: "框架摘要", multiline: true },
                { key: "total_chapters", label: "目标章数" },
                { key: "style", label: "风格/类型说明" },
              ]
            : card.type === "writing_prefs"
              ? [{ key: "content", label: "本书写作偏好（Markdown）", multiline: true }]
              : [];

  const modalTitle =
    card.type === "outline" && (outlineChapter || chapterDraft.chapter_no)
      ? `编辑 · 第 ${chapterDraft.chapter_no} 章大纲`
      : `编辑 · ${card.title || card.type}`;

  const handleSave = () => {
    if (card.type === "outline") {
      const chapters = cardDataToTimelineChapters(data);
      const merged = chapters.some((c) => c.chapter_no === chapterDraft.chapter_no)
        ? chapters.map((c) => (c.chapter_no === chapterDraft.chapter_no ? chapterDraft : c))
        : [...chapters, chapterDraft].sort((a, b) => a.chapter_no - b.chapter_no);
      onSave({
        ...card,
        data: { ...data, chapters: merged.map(timelineChapterToCardData) },
      });
      return;
    }
    if (card.type === "plot") {
      onSave({ ...card, data });
      return;
    }
    onSave({ ...card, data });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="card max-h-[85vh] w-full max-w-lg overflow-y-auto p-5">
        <h3 className="text-lg font-semibold">{modalTitle}</h3>
        <div className="mt-4 space-y-3">
          {card.type === "outline" ? (
            <>
              {!outlineChapter && outlineChapters.length > 1 && (
                <div>
                  <label className="label">选择章节</label>
                  <select
                    className="input"
                    value={activeChapterNo}
                    onChange={(e) => setActiveChapterNo(Number(e.target.value))}
                  >
                    {outlineChapters.map((ch) => (
                      <option key={ch.chapter_no} value={ch.chapter_no}>
                        第 {ch.chapter_no} 章 · {ch.title || "未命名"}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              <OutlineChapterEditor chapter={chapterDraft} onChange={setChapterDraft} />
            </>
          ) : (
            fields.map((f) =>
              f.multiline ? (
                <div key={f.key}>
                  <label className="label">{f.label}</label>
                  <textarea
                    className="input min-h-[80px]"
                    value={String(data[f.key] ?? "")}
                    onChange={(e) => set(f.key, e.target.value)}
                  />
                </div>
              ) : (
                <div key={f.key}>
                  <label className="label">{f.label}</label>
                  <input
                    className="input"
                    value={String(data[f.key] ?? "")}
                    onChange={(e) => set(f.key, e.target.value)}
                  />
                </div>
              ),
            )
          )}
          {card.type === "plot" && Array.isArray(data.phases) && (data.phases as unknown[]).length > 0 && (
            <p className="text-xs text-slate-500">
              主线阶段与单元结构请在对话中请助手调整，或采纳后于书籍概览修改；此处可编辑摘要、章数与风格。
            </p>
          )}
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" className="btn-secondary" onClick={onClose}>
            取消
          </button>
          <button type="button" className="btn-primary" onClick={handleSave}>
            保存并采纳
          </button>
        </div>
      </div>
    </div>
  );
}

export type CardSlide = {
  key: string;
  card: SetupCard;
  outlineChapter?: TimelineChapter;
};

export function expandCardsToSlides(cards: SetupCard[]): CardSlide[] {
  const slides: CardSlide[] = [];
  for (const card of cards) {
    if (card.type === "outline") {
      const chapters = cardDataToTimelineChapters(card.data || {});
      if (chapters.length > 0) {
        for (const ch of chapters) {
          slides.push({
            key: `${card.id}-ch-${ch.chapter_no}`,
            card,
            outlineChapter: ch,
          });
        }
      } else {
        slides.push({ key: card.id, card });
      }
    } else {
      slides.push({ key: card.id, card });
    }
  }
  return slides;
}

export function PaginatedCardGroup({
  cards,
  title = "设定卡片",
  onApply,
  onEdit,
  applyingId,
  className,
  compact = true,
}: {
  cards: SetupCard[];
  title?: string;
  onApply?: (c: SetupCard) => void;
  onEdit?: (c: SetupCard, outlineChapter?: TimelineChapter) => void;
  applyingId?: string | null;
  className?: string;
  compact?: boolean;
}) {
  const slides = useMemo(() => expandCardsToSlides(cards), [cards]);
  const [currentIndex, setCurrentIndex] = useState(0);

  useEffect(() => {
    setCurrentIndex(0);
  }, [slides.length, slides.map((s) => s.key).join("|")]);

  if (!slides.length) return null;

  const total = slides.length;
  const idx = Math.min(currentIndex, total - 1);
  const slide = slides[idx];
  const atStart = idx === 0;
  const atEnd = idx === total - 1;
  const showDots = total <= 7;

  return (
    <div className={className ?? "mt-3 w-full"}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-400">
          <Sparkles className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">
            {title} · {total}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            aria-label="上一张"
            disabled={atStart}
            onClick={() => setCurrentIndex((i) => Math.max(0, i - 1))}
            className="rounded-md p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-30"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="min-w-[2.5rem] text-center text-[11px] tabular-nums text-slate-500">
            {idx + 1}/{total}
          </span>
          <button
            type="button"
            aria-label="下一张"
            disabled={atEnd}
            onClick={() => setCurrentIndex((i) => Math.min(total - 1, i + 1))}
            className="rounded-md p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-30"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>

      {showDots && total > 1 && (
        <div className="mb-2 flex justify-center gap-1.5">
          {slides.map((s, i) => (
            <button
              key={s.key}
              type="button"
              aria-label={`第 ${i + 1} 张`}
              aria-current={i === idx ? "true" : undefined}
              onClick={() => setCurrentIndex(i)}
              className={`h-1.5 rounded-full transition-all ${
                i === idx ? "w-4 bg-brand-500" : "w-1.5 bg-slate-300 hover:bg-slate-400"
              }`}
            />
          ))}
        </div>
      )}

      <div className="w-full">
        <SetupCardView
          key={slide.key}
          card={slide.card}
          outlineChapter={slide.outlineChapter}
          onApply={slide.card.status !== "applied" ? onApply : undefined}
          onEdit={onEdit}
          applying={applyingId === slide.card.id}
          compact={compact}
          scrollableBody
        />
      </div>
    </div>
  );
}

export function SetupCardGrid({
  cards,
  onApply,
  onEdit,
  applyingId,
  className,
  compact,
}: {
  cards: SetupCard[];
  onApply?: (c: SetupCard) => void;
  onEdit?: (c: SetupCard, outlineChapter?: TimelineChapter) => void;
  applyingId?: string | null;
  className?: string;
  compact?: boolean;
}) {
  if (!cards.length) return null;
  return (
    <PaginatedCardGroup
      cards={cards}
      onApply={onApply}
      onEdit={onEdit}
      applyingId={applyingId}
      className={className ?? "mt-3 w-full max-w-3xl"}
      compact={compact ?? true}
    />
  );
}
