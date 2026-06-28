import { Flag, LogOut, UserPlus, Users } from "lucide-react";

export type TimelineChapter = {
  chapter_no: number;
  title?: string;
  plot_points?: string;
  scene?: string;
  comedy_core?: string;
  cast?: string[];
  events?: string[];
  entrances?: string[];
  exits?: string[];
};

type Props = {
  chapters: TimelineChapter[];
  compact?: boolean;
  single?: boolean;
};

export default function OutlineTimeline({ chapters, compact, single }: Props) {
  const sorted = [...chapters].sort((a, b) => Number(a.chapter_no) - Number(b.chapter_no));
  if (!sorted.length) return null;

  return (
    <div className="relative space-y-0">
      <div className="absolute left-[15px] top-2 bottom-2 w-0.5 bg-gradient-to-b from-amber-300 via-amber-200 to-amber-100" />
      {sorted.map((ch, idx) => (
        <div key={`${ch.chapter_no}-${idx}`} className={`relative pl-10 ${compact ? "pb-3" : "pb-5"}`}>
          <div className="absolute left-2 top-1.5 flex h-7 w-7 items-center justify-center rounded-full bg-amber-500 text-[10px] font-bold text-white shadow ring-4 ring-amber-100">
            {ch.chapter_no}
          </div>
          <div className="rounded-xl border border-amber-100 bg-white p-3 shadow-sm">
            <div className="flex flex-wrap items-center gap-2">
              <h5 className="text-sm font-bold text-slate-900">{ch.title || `第 ${ch.chapter_no} 章`}</h5>
              {ch.scene && (
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-600">{ch.scene}</span>
              )}
            </div>
            {ch.plot_points && (
              <p
                className={`mt-2 text-slate-600 leading-relaxed ${compact ? "text-xs" : "text-sm"} ${compact && !single ? "line-clamp-3" : ""}`}
              >
                {ch.plot_points}
              </p>
            )}
            <div className="mt-2 flex flex-wrap gap-1.5">
              {(ch.cast || []).map((name) => (
                <span key={name} className="inline-flex items-center gap-0.5 rounded-md bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-800 ring-1 ring-emerald-100">
                  <Users className="h-3 w-3" /> {name}
                </span>
              ))}
              {(ch.entrances || []).map((name) => (
                <span key={`in-${name}`} className="inline-flex items-center gap-0.5 rounded-md bg-sky-50 px-1.5 py-0.5 text-[10px] text-sky-800 ring-1 ring-sky-100">
                  <UserPlus className="h-3 w-3" /> 登场·{name}
                </span>
              ))}
              {(ch.exits || []).map((name) => (
                <span key={`out-${name}`} className="inline-flex items-center gap-0.5 rounded-md bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">
                  <LogOut className="h-3 w-3" /> 退场·{name}
                </span>
              ))}
            </div>
            {(ch.events || []).length > 0 && (
              <ul className="mt-2 space-y-1 border-t border-amber-50 pt-2">
                {ch.events!.map((ev, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-xs text-amber-900">
                    <Flag className="mt-0.5 h-3 w-3 shrink-0 text-amber-500" />
                    {ev}
                  </li>
                ))}
              </ul>
            )}
            {ch.comedy_core && (
              <p className="mt-2 text-[10px] italic text-amber-700/80">梗核：{ch.comedy_core}</p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

export function planToTimelineChapter(p: {
  chapter_no: number;
  title: string;
  plot_points: string;
  scene: string;
  comedy_core: string;
  character_names?: string;
  meta_json?: Record<string, unknown>;
}): TimelineChapter {
  const meta = p.meta_json || {};
  const castFromMeta = Array.isArray(meta.cast) ? (meta.cast as string[]) : [];
  const castFromNames = p.character_names
    ? p.character_names.split(/[、,，]/).map((s) => s.trim()).filter(Boolean)
    : [];
  return {
    chapter_no: p.chapter_no,
    title: p.title,
    plot_points: p.plot_points,
    scene: p.scene,
    comedy_core: p.comedy_core,
    cast: castFromMeta.length ? castFromMeta : castFromNames,
    events: Array.isArray(meta.events) ? (meta.events as string[]) : [],
    entrances: Array.isArray(meta.entrances) ? (meta.entrances as string[]) : [],
    exits: Array.isArray(meta.exits) ? (meta.exits as string[]) : [],
  };
}

export function cardDataToTimelineChapters(data: Record<string, unknown>): TimelineChapter[] {
  const raw = data.chapters;
  if (!Array.isArray(raw)) return [];
  return raw.map((ch) => {
    const c = ch as Record<string, unknown>;
    const cast = c.cast || c.characters;
    return {
      chapter_no: Number(c.chapter_no),
      title: String(c.title || ""),
      plot_points: String(c.plot_points || c.synopsis || ""),
      scene: String(c.scene || ""),
      comedy_core: String(c.comedy_core || c.comedy_hook || ""),
      cast: Array.isArray(cast) ? cast.map(String) : [],
      events: Array.isArray(c.events) ? c.events.map(String) : [],
      entrances: Array.isArray(c.entrances) ? c.entrances.map(String) : [],
      exits: Array.isArray(c.exits) ? c.exits.map(String) : [],
    };
  });
}
