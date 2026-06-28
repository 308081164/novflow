import { CheckCircle2, Circle, Globe, ListTree, Sparkles, User, GitBranch, ArrowRight } from "lucide-react";
import type { Book, SetupSnapshot } from "../../api";
import { Badge } from "../Layout";

const STEPS = ["定位", "世界观", "角色", "大纲", "写作"];

type Props = {
  book: Book;
  snapshot: SetupSnapshot;
};

export default function ContextPanel({ book, snapshot }: Props) {
  return (
    <div className="space-y-4">
      <div className="card p-4">
        <h3 className="font-semibold text-slate-900">{book.title}</h3>
        <p className="mt-1 text-xs text-slate-500">创建进度</p>
        <div className="mt-3 flex gap-1">
          {STEPS.map((s, i) => (
            <div
              key={s}
              className={`flex-1 rounded py-1 text-center text-[10px] font-medium ${
                book.setup_step > i ? "bg-brand-600 text-white" : book.setup_step === i + 1 ? "bg-brand-100 text-brand-800" : "bg-slate-100 text-slate-400"
              }`}
              title={s}
            >
              {s}
            </div>
          ))}
        </div>
        {snapshot.progress && (
          <div className="mt-4 space-y-2 border-t border-slate-100 pt-3">
            {snapshot.progress.checklist.map((item) => (
              <div key={item.id} className="flex items-center gap-2 text-xs text-slate-600">
                {item.done ? (
                  <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-600" />
                ) : (
                  <Circle className="h-3.5 w-3.5 shrink-0 text-slate-300" />
                )}
                <span className={item.done ? "text-slate-500 line-through" : "font-medium text-slate-700"}>{item.label}</span>
              </div>
            ))}
            <div className="mt-2 flex items-start gap-2 rounded-lg bg-brand-50 px-2.5 py-2 text-xs text-brand-900">
              <ArrowRight className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{snapshot.progress.next_action}</span>
            </div>
          </div>
        )}
      </div>

      {snapshot.premise && (
        <SnapshotCard icon={Sparkles} title="梗概" color="violet">
          {snapshot.genre && <Badge color="blue">{snapshot.genre}</Badge>}
          <p className="mt-2 text-sm text-slate-600">{snapshot.premise}</p>
        </SnapshotCard>
      )}

      {snapshot.worldview?.content && (
        <SnapshotCard icon={Globe} title="世界观" color="sky">
          {snapshot.worldview.era && <p className="text-xs text-slate-500">{snapshot.worldview.era} · {snapshot.worldview.setting}</p>}
          <p className="mt-1 text-sm text-slate-600 line-clamp-4">{snapshot.worldview.content}</p>
        </SnapshotCard>
      )}

      {snapshot.characters?.length > 0 && (
        <SnapshotCard icon={User} title={`角色 (${snapshot.characters.length})`} color="emerald">
          <ul className="mt-1 space-y-1">
            {snapshot.characters.map((c) => (
              <li key={c.id} className="text-sm">
                <span className="font-medium">{c.name}</span>
                <span className="text-slate-400"> · {c.role}</span>
                {c.summary && <p className="text-xs text-slate-500">{c.summary}</p>}
              </li>
            ))}
          </ul>
        </SnapshotCard>
      )}

      {snapshot.plot_summary && (
        <SnapshotCard icon={GitBranch} title="剧情走向" color="rose">
          <p className="text-sm text-slate-600 line-clamp-5">{snapshot.plot_summary}</p>
        </SnapshotCard>
      )}

      {snapshot.outline_preview?.length > 0 && (
        <SnapshotCard icon={ListTree} title="大纲预览" color="amber">
          <ul className="mt-1 space-y-1">
            {snapshot.outline_preview.map((p) => (
              <li key={p.chapter_no} className="text-xs text-slate-600">
                <span className="font-medium text-slate-800">第{p.chapter_no}章</span> {p.title}
              </li>
            ))}
          </ul>
        </SnapshotCard>
      )}
    </div>
  );
}

function SnapshotCard({
  icon: Icon,
  title,
  color,
  children,
}: {
  icon: typeof Sparkles;
  title: string;
  color: string;
  children: React.ReactNode;
}) {
  const borders: Record<string, string> = {
    violet: "border-violet-100",
    sky: "border-sky-100",
    emerald: "border-emerald-100",
    rose: "border-rose-100",
    amber: "border-amber-100",
  };
  return (
    <div className={`card border-l-4 p-3 ${borders[color] || ""}`}>
      <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
        <Icon className="h-4 w-4 text-slate-500" />
        {title}
      </div>
      <div className="mt-2">{children}</div>
    </div>
  );
}
