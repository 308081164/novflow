import { GitBranch, Layers, Target } from "lucide-react";

type Phase = { name?: string; chapter_range?: string; description?: string };
type Unit = { name?: string; episodes_per_arc?: number | string; description?: string };

export default function PlotFrameworkBody({ data }: { data: Record<string, unknown> }) {
  const summary = String(data.summary || data.title || "");
  const total = data.total_chapters ? Number(data.total_chapters) : null;
  const style = String(data.style || "");
  const phases = (Array.isArray(data.phases) ? data.phases : []) as Phase[];
  const units = (Array.isArray(data.units) ? data.units : []) as Unit[];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {total && (
          <span className="inline-flex items-center gap-1 rounded-lg bg-rose-100 px-2.5 py-1 text-xs font-semibold text-rose-800">
            <Target className="h-3.5 w-3.5" /> 目标 {total} 章
          </span>
        )}
        {style && (
          <span className="rounded-lg bg-white px-2.5 py-1 text-xs text-rose-900 ring-1 ring-rose-100">{style}</span>
        )}
      </div>
      {summary && (
        <p className="rounded-xl bg-rose-50/60 p-3 text-sm leading-relaxed text-slate-700 ring-1 ring-rose-100">{summary}</p>
      )}
      {phases.length > 0 && (
        <div>
          <div className="mb-2 flex items-center gap-1 text-xs font-semibold text-rose-800">
            <GitBranch className="h-3.5 w-3.5" /> 主线阶段
          </div>
          <div className="relative space-y-0 pl-4">
            <div className="absolute left-1.5 top-1 bottom-1 w-0.5 bg-rose-200" />
            {phases.map((p, i) => (
              <div key={i} className="relative pb-3 pl-4">
                <div className="absolute left-0 top-1.5 h-3 w-3 rounded-full bg-rose-500 ring-2 ring-rose-100" />
                <div className="text-sm font-semibold text-slate-900">{p.name}</div>
                {p.chapter_range && <div className="text-[10px] text-rose-600">第 {p.chapter_range} 章</div>}
                {p.description && <p className="mt-1 text-xs text-slate-600">{p.description}</p>}
              </div>
            ))}
          </div>
        </div>
      )}
      {units.length > 0 && (
        <div>
          <div className="mb-2 flex items-center gap-1 text-xs font-semibold text-rose-800">
            <Layers className="h-3.5 w-3.5" /> 单元剧结构
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {units.map((u, i) => (
              <div key={i} className="rounded-lg border border-rose-100 bg-white p-2.5">
                <div className="text-sm font-medium text-slate-900">{u.name}</div>
                {u.episodes_per_arc && (
                  <div className="text-[10px] text-slate-500">每单元约 {u.episodes_per_arc} 章</div>
                )}
                {u.description && <p className="mt-1 text-xs text-slate-600">{u.description}</p>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
