import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { BookOpen, MapPin, Sparkles, Users } from "lucide-react";
import type { ChapterPlan } from "../../api";
import { planHasOutlineContent } from "../../utils/planOutline";
import { Badge } from "../Layout";

type Props = {
  bookId: number;
  chapterNo: number;
  plan: ChapterPlan | null;
  chapterList: ChapterPlan[];
};

type ChapterVisualStatus = "empty" | "draft" | "approved";

const STATUS_META: Record<
  ChapterVisualStatus,
  { dot: string; text: string; hover: string; active: string; label: string }
> = {
  empty: {
    dot: "bg-slate-300",
    text: "text-slate-500",
    hover: "hover:bg-slate-100 hover:text-slate-700",
    active: "bg-slate-100 font-medium text-slate-800 ring-1 ring-slate-300",
    label: "未写",
  },
  draft: {
    dot: "bg-blue-500",
    text: "text-blue-700",
    hover: "hover:bg-blue-50 hover:text-blue-800",
    active: "bg-blue-100 font-medium text-blue-900 ring-1 ring-blue-300",
    label: "草稿",
  },
  approved: {
    dot: "bg-emerald-500",
    text: "text-emerald-700",
    hover: "hover:bg-emerald-50 hover:text-emerald-800",
    active: "bg-emerald-100 font-medium text-emerald-900 ring-1 ring-emerald-300",
    label: "定稿",
  },
};

function chapterVisualStatus(status: string): ChapterVisualStatus {
  if (status === "approved") return "approved";
  if (status === "draft" || status === "written") return "draft";
  return "empty";
}

function metaList(meta: Record<string, unknown> | undefined, key: string): string[] {
  const v = meta?.[key];
  if (!v) return [];
  if (Array.isArray(v)) return v.map(String);
  return [String(v)];
}

export default function ChapterOutlinePanel({ bookId, chapterNo, plan, chapterList }: Props) {
  const activeItemRef = useRef<HTMLLIElement>(null);

  const cast = metaList(plan?.meta_json, "cast");
  const events = metaList(plan?.meta_json, "events");
  const entrances = metaList(plan?.meta_json, "entrances");
  const characters =
    cast.length > 0
      ? cast
      : plan?.character_names
        ? plan.character_names.split(/[、,，]/).map((s) => s.trim()).filter(Boolean)
        : [];

  useEffect(() => {
    activeItemRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [chapterNo, chapterList.length]);

  return (
    <aside className="flex h-full min-h-0 w-72 shrink-0 flex-col border-r border-slate-200 bg-slate-50/80">
      <div className="shrink-0 border-b border-slate-200 px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-slate-800">本章大纲</h2>
          <Link to={`/books/${bookId}/outline`} className="text-xs text-brand-600 hover:underline">
            全部
          </Link>
        </div>
        <p className="mt-0.5 text-xs text-slate-500">第 {chapterNo} 章规划参考</p>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain px-4 py-4">
        {!plan || !planHasOutlineContent(plan) ? (
          <div className="rounded-xl border border-dashed border-slate-200 bg-white p-4 text-center">
            <BookOpen className="mx-auto h-8 w-8 text-slate-300" />
            <p className="mt-2 text-sm text-slate-600">暂无本章大纲</p>
            <Link to={`/books/${bookId}/outline`} className="mt-2 inline-block text-xs text-brand-600 hover:underline">
              去大纲页补充
            </Link>
          </div>
        ) : (
          <>
            <section>
              <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">标题</h3>
              <p className="text-sm font-medium leading-snug text-slate-900">{plan.title || `第${chapterNo}章`}</p>
              {plan.status && plan.status !== "planned" && <Badge color="blue">{plan.status}</Badge>}
            </section>

            {plan.scene?.trim() && (
              <section>
                <h3 className="mb-1.5 flex items-center gap-1 text-xs font-medium uppercase tracking-wide text-slate-400">
                  <MapPin className="h-3 w-3" /> 场景
                </h3>
                <p className="text-sm leading-relaxed text-slate-700">{plan.scene}</p>
              </section>
            )}

            {plan.plot_points?.trim() && (
              <section>
                <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">情节骨架</h3>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">{plan.plot_points}</p>
              </section>
            )}

            {(plan.comedy_core?.trim() || plan.comedy_hook?.trim()) && (
              <section>
                <h3 className="mb-1.5 flex items-center gap-1 text-xs font-medium uppercase tracking-wide text-slate-400">
                  <Sparkles className="h-3 w-3" /> 喜剧核
                </h3>
                <p className="text-sm leading-relaxed text-slate-700">{plan.comedy_core || plan.comedy_hook}</p>
              </section>
            )}

            {characters.length > 0 && (
              <section>
                <h3 className="mb-1.5 flex items-center gap-1 text-xs font-medium uppercase tracking-wide text-slate-400">
                  <Users className="h-3 w-3" /> 出场角色
                </h3>
                <div className="flex flex-wrap gap-1.5">
                  {characters.map((name) => (
                    <span key={name} className="rounded-full bg-white px-2 py-0.5 text-xs text-slate-700 ring-1 ring-slate-200">
                      {name}
                    </span>
                  ))}
                </div>
              </section>
            )}

            {events.length > 0 && (
              <section>
                <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">关键事件</h3>
                <ul className="space-y-1.5">
                  {events.map((ev, i) => (
                    <li key={i} className="flex gap-2 text-sm text-slate-700">
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-400" />
                      {ev}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {entrances.length > 0 && (
              <section>
                <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">新登场</h3>
                <p className="text-sm text-slate-700">{entrances.join("、")}</p>
              </section>
            )}
          </>
        )}
      </div>

      {chapterList.length > 0 && (
        <section className="flex min-h-[140px] max-h-[min(45vh,320px)] shrink-0 flex-col border-t border-slate-200 bg-slate-50/80">
          <div className="shrink-0 px-4 pb-2 pt-3">
            <h3 className="text-xs font-medium uppercase tracking-wide text-slate-400">章节列表</h3>
            <p className="mt-0.5 text-[10px] text-slate-400">共 {chapterList.length} 章 · 可滚动浏览</p>
            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-slate-500">
              {(Object.keys(STATUS_META) as ChapterVisualStatus[]).map((key) => (
                <span key={key} className="inline-flex items-center gap-1">
                  <span className={`h-2 w-2 rounded-full ${STATUS_META[key].dot}`} />
                  {STATUS_META[key].label}
                </span>
              ))}
            </div>
          </div>
          <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto overscroll-contain px-3 pb-3">
            {chapterList.map((p) => {
              const visual = chapterVisualStatus(p.status);
              const meta = STATUS_META[visual];
              const isCurrent = p.chapter_no === chapterNo;
              return (
                <li key={p.chapter_no} ref={isCurrent ? activeItemRef : undefined}>
                  <Link
                    to={`/books/${bookId}/write/${p.chapter_no}`}
                    className={`flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs transition-colors ${
                      isCurrent ? meta.active : `${meta.text} ${meta.hover}`
                    }`}
                  >
                    <span className={`h-2 w-2 shrink-0 rounded-full ${meta.dot}`} aria-hidden />
                    <span className="truncate">
                      第{p.chapter_no}章 {p.title}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </aside>
  );
}
