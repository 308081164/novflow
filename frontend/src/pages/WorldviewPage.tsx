import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Sparkles } from "lucide-react";
import { api, Worldview } from "../api";
import { PageHeader } from "../components/Layout";

export default function WorldviewPage() {
  const { bookId } = useParams();
  const id = Number(bookId);
  const [wv, setWv] = useState<Worldview | null>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.worldview(id).then(setWv);
  }, [id]);

  const save = async () => {
    if (!wv) return;
    await api.saveWorldview(id, wv);
    setMsg("已保存");
  };

  const aiGen = async () => {
    setBusy(true);
    try {
      setWv(await api.aiWorldview(id));
      setMsg("AI 已重新生成世界观");
    } finally {
      setBusy(false);
    }
  };

  if (!wv) return <p>加载中…</p>;

  return (
    <div className="max-w-3xl">
      <Link to={`/books/${id}`} className="mb-4 inline-flex items-center gap-1 text-sm text-brand-600 hover:underline">
        <ArrowLeft className="h-4 w-4" /> 返回书籍
      </Link>
      <PageHeader
        title="世界观设定"
        desc="时代、舞台、时间线与禁忌——生成章节时会自动注入"
        action={
          <button className="btn-secondary" onClick={aiGen} disabled={busy}>
            <Sparkles className="h-4 w-4" /> AI 重新生成
          </button>
        }
      />
      {msg && <p className="mb-4 text-sm text-emerald-600">{msg}</p>}
      <div className="card space-y-4 p-6">
        <div className="grid gap-3 sm:grid-cols-2">
          <div><label className="label">时代</label><input className="input" value={wv.era} onChange={(e) => setWv({ ...wv, era: e.target.value })} /></div>
          <div><label className="label">主舞台</label><input className="input" value={wv.setting} onChange={(e) => setWv({ ...wv, setting: e.target.value })} /></div>
        </div>
        <div><label className="label">基调</label><input className="input" value={wv.tone} onChange={(e) => setWv({ ...wv, tone: e.target.value })} /></div>
        <div><label className="label">时间线</label><textarea className="input min-h-[100px]" value={wv.timeline_text} onChange={(e) => setWv({ ...wv, timeline_text: e.target.value })} /></div>
        <div><label className="label">禁忌</label><textarea className="input min-h-[80px]" value={wv.taboos} onChange={(e) => setWv({ ...wv, taboos: e.target.value })} /></div>
        <div><label className="label">完整文档</label><textarea className="input min-h-[280px] font-mono text-xs" value={wv.content} onChange={(e) => setWv({ ...wv, content: e.target.value })} /></div>
        <button className="btn-primary" onClick={save}>保存世界观</button>
      </div>
    </div>
  );
}
