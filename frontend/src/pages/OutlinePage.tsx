import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, PenLine, RefreshCw } from "lucide-react";
import { api, Book, ChapterPlan, SyncSettingsResult } from "../api";
import { PageHeader } from "../components/Layout";
import OutlineTimeline, { planToTimelineChapter } from "../components/setup/OutlineTimeline";

export default function OutlinePage() {
  const { bookId } = useParams();
  const id = Number(bookId);
  const [book, setBook] = useState<Book | null>(null);
  const [plans, setPlans] = useState<ChapterPlan[]>([]);
  const [view, setView] = useState<"timeline" | "table">("timeline");
  const [syncInfo, setSyncInfo] = useState<SyncSettingsResult | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [b, sync, planList] = await Promise.all([
        api.book(id),
        api.syncBookSettings(id),
        api.chapterPlans(id),
      ]);
      setBook(b);
      setSyncInfo(sync);
      setPlans(planList);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const withPlot = useMemo(() => plans.filter((p) => p.plot_points?.trim()), [plans]);
  const timelineChapters = withPlot.map(planToTimelineChapter);

  const plannedTotal = book?.planned_chapters || book?.target_chapters || plans.length || 0;
  const outlinePlanned = book?.outline_planned_count ?? withPlot.length;

  const syncBanner =
    syncInfo && syncInfo.cards_applied > 0
      ? `同步完成：${outlinePlanned} / ${plannedTotal} 章大纲已写入数据库${
          syncInfo.characters_synced > 0 ? `，${syncInfo.characters_synced} 张角色卡已更新` : ""
        }`
      : null;

  return (
    <div>
      <Link to={`/books/${id}`} className="mb-4 inline-flex items-center gap-1 text-sm text-brand-600 hover:underline">
        <ArrowLeft className="h-4 w-4" /> 返回书籍
      </Link>
      <PageHeader
        title="故事大纲时间线"
        desc="展示已采纳并写入数据库的章节规划；与 AI 创作助手同步"
        action={
          <div className="flex gap-2">
            <button type="button" className="btn-secondary text-xs" onClick={load} disabled={loading}>
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              同步
            </button>
            <button
              type="button"
              className={view === "timeline" ? "btn-primary text-xs" : "btn-secondary text-xs"}
              onClick={() => setView("timeline")}
            >
              时间线
            </button>
            <button
              type="button"
              className={view === "table" ? "btn-primary text-xs" : "btn-secondary text-xs"}
              onClick={() => setView("table")}
            >
              表格
            </button>
          </div>
        }
      />

      {syncBanner && (
        <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-800">
          {syncBanner}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">加载中…</p>
      ) : withPlot.length === 0 ? (
        <div className="card p-8 text-center text-sm text-slate-500">
          尚无章节大纲（全书规划 {plannedTotal} 章）。在{" "}
          <Link to={`/books/${id}/setup`} className="text-brand-600 underline">
            AI 创作助手
          </Link>{" "}
          中说「规划第 1～10 章大纲」并点「采纳」，然后返回此页点「同步」。
        </div>
      ) : view === "timeline" ? (
        <div className="card p-6">
          <p className="mb-4 text-xs text-slate-500">
            已规划大纲 <span className="font-medium text-slate-700">{outlinePlanned}</span> /{" "}
            <span className="font-medium text-slate-700">{plannedTotal}</span> 章
          </p>
          <OutlineTimeline chapters={timelineChapters} />
        </div>
      ) : (
        <div className="card overflow-x-auto">
          <div className="border-b border-slate-100 px-4 py-3 text-xs text-slate-500">
            已规划大纲 {outlinePlanned} / {plannedTotal} 章
          </div>
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-slate-500">
              <tr>
                <th className="w-16 px-4 py-3">章</th>
                <th className="w-40 px-4 py-3">标题</th>
                <th className="px-4 py-3">梗概</th>
                <th className="w-28 px-4 py-3">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {withPlot.map((p) => (
                <tr key={p.chapter_no} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-mono">{p.chapter_no}</td>
                  <td className="px-4 py-3">{p.title}</td>
                  <td className="px-4 py-3 text-slate-600">{p.plot_points}</td>
                  <td className="px-4 py-3">
                    <Link to={`/books/${id}/write/${p.chapter_no}`} className="btn-secondary px-2 py-1 text-xs">
                      <PenLine className="h-3 w-3" /> 写作
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
