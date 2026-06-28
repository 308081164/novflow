import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, Sparkles, Globe, Users, ListTree, PenLine } from "lucide-react";
import { api, Book, Character, Worldview } from "../api";
import { PageHeader } from "../components/Layout";

const STEPS = [
  { n: 1, title: "作品定位", icon: Sparkles },
  { n: 2, title: "世界观", icon: Globe },
  { n: 3, title: "角色卡", icon: Users },
  { n: 4, title: "章节大纲", icon: ListTree },
  { n: 5, title: "开始写作", icon: PenLine },
];

export default function SetupWizardPage() {
  const { bookId } = useParams();
  const id = Number(bookId);
  const nav = useNavigate();
  const [book, setBook] = useState<Book | null>(null);
  const [step, setStep] = useState(1);
  const [genre, setGenre] = useState("");
  const [premise, setPremise] = useState("");
  const [targetChapters, setTargetChapters] = useState(100);
  const [wv, setWv] = useState<Worldview | null>(null);
  const [chars, setChars] = useState<Character[]>([]);
  const [charHint, setCharHint] = useState("主角，第一人称叙述者");
  const [outlineStart, setOutlineStart] = useState(1);
  const [outlineCount, setOutlineCount] = useState(10);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    api.book(id).then((b) => {
      setBook(b);
      setStep(b.setup_step < 5 ? b.setup_step : 1);
      setGenre(b.genre);
      setPremise(b.premise || b.blurb);
      setTargetChapters(b.target_chapters);
    });
    api.worldview(id).then(setWv).catch(() => {});
    api.characters(id).then(setChars).catch(() => {});
  }, [id]);

  const saveStep = async (next: number) => {
    await api.updateSetup(id, { setup_step: next, genre, premise, target_chapters: targetChapters });
    setStep(next);
  };

  const step1Next = async () => {
    setErr("");
    if (!premise.trim()) {
      setErr("请填写一句话梗概");
      return;
    }
    await api.updateSetup(id, { genre, premise, target_chapters: targetChapters, setup_step: 2 });
    setStep(2);
  };

  const aiWorldview = async () => {
    setBusy(true);
    setErr("");
    try {
      const w = await api.aiWorldview(id);
      setWv(w);
      setMsg("世界观已生成，可继续编辑");
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const saveWorldview = async () => {
    if (!wv) return;
    await api.saveWorldview(id, wv);
    await saveStep(3);
  };

  const aiCharacter = async () => {
    setBusy(true);
    setErr("");
    try {
      const c = await api.aiCharacter(id, charHint);
      setChars((prev) => [...prev, c]);
      setMsg(`已生成角色：${c.name}`);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const aiOutline = async () => {
    setBusy(true);
    setErr("");
    try {
      const r = await api.aiOutline(id, outlineStart, outlineCount);
      setMsg(`已生成 ${r.count} 章规划`);
      await saveStep(4);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const finish = async () => {
    try {
      await api.aiRules(id);
    } catch {
      /* optional */
    }
    await api.updateSetup(id, { setup_step: 5 });
    nav(`/books/${id}`);
  };

  if (!book) return <p className="text-slate-500">加载中…</p>;

  return (
    <div className="max-w-3xl">
      <Link to={`/books/${id}`} className="mb-4 inline-flex items-center gap-1 text-sm text-brand-600 hover:underline">
        <ArrowLeft className="h-4 w-4" /> 返回书籍
      </Link>
      <PageHeader title={`创建向导 · ${book.title}`} desc="按步骤完成设定，即可开始 AI 辅助写作" />

      <div className="mb-8 flex gap-2 overflow-x-auto pb-2">
        {STEPS.map((s) => (
          <button
            key={s.n}
            type="button"
            onClick={() => setStep(s.n)}
            className={`flex shrink-0 items-center gap-2 rounded-full px-4 py-2 text-sm ${
              step === s.n ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-600"
            }`}
          >
            <s.icon className="h-4 w-4" /> {s.n}. {s.title}
          </button>
        ))}
      </div>

      {msg && <div className="mb-4 rounded-lg bg-emerald-50 px-4 py-2 text-sm">{msg}</div>}
      {err && <div className="mb-4 rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700">{err}</div>}

      {step === 1 && (
        <div className="card space-y-4 p-6">
          <h3 className="font-semibold">Step 1 · 作品定位</h3>
          <div>
            <label className="label">类型</label>
            <input className="input" placeholder="如：现实悬疑 · 轻喜剧" value={genre} onChange={(e) => setGenre(e.target.value)} />
          </div>
          <div>
            <label className="label">一句话梗概（必填）</label>
            <textarea className="input min-h-[100px]" value={premise} onChange={(e) => setPremise(e.target.value)} placeholder="用 1–3 句话说明故事核心冲突与卖点…" />
          </div>
          <div>
            <label className="label">计划总章数</label>
            <input className="input" type="number" min={10} max={500} value={targetChapters} onChange={(e) => setTargetChapters(Number(e.target.value))} />
          </div>
          <button className="btn-primary" onClick={step1Next}>
            下一步：世界观 <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      )}

      {step === 2 && (
        <div className="card space-y-4 p-6">
          {!wv && <p className="text-slate-500">加载世界观…</p>}
          {wv && (
          <>
          <h3 className="font-semibold">Step 2 · 世界观</h3>
          <p className="text-sm text-slate-500">可手动填写，或让 AI 根据梗概生成初稿后再改。</p>
          <button className="btn-secondary" onClick={aiWorldview} disabled={busy}>
            <Sparkles className="h-4 w-4" /> AI 生成世界观
          </button>
          <div className="grid gap-3 sm:grid-cols-2">
            <div><label className="label">时代</label><input className="input" value={wv.era} onChange={(e) => setWv({ ...wv, era: e.target.value })} /></div>
            <div><label className="label">主舞台</label><input className="input" value={wv.setting} onChange={(e) => setWv({ ...wv, setting: e.target.value })} /></div>
          </div>
          <div><label className="label">基调</label><input className="input" value={wv.tone} onChange={(e) => setWv({ ...wv, tone: e.target.value })} /></div>
          <div><label className="label">时间线</label><textarea className="input min-h-[80px]" value={wv.timeline_text} onChange={(e) => setWv({ ...wv, timeline_text: e.target.value })} /></div>
          <div><label className="label">写作禁忌</label><textarea className="input min-h-[60px]" value={wv.taboos} onChange={(e) => setWv({ ...wv, taboos: e.target.value })} /></div>
          <div><label className="label">完整世界观（Markdown）</label><textarea className="input min-h-[200px] font-mono text-xs" value={wv.content} onChange={(e) => setWv({ ...wv, content: e.target.value })} /></div>
          <button className="btn-primary" onClick={saveWorldview}>下一步：角色卡</button>
          </>
          )}
        </div>
      )}

      {step === 3 && (
        <div className="card space-y-4 p-6">
          <h3 className="font-semibold">Step 3 · 角色卡</h3>
          <p className="text-sm text-slate-500">至少创建 2 个核心角色（建议：主角 + 重要配角/反派）。</p>
          <div className="flex gap-2">
            <input className="input flex-1" value={charHint} onChange={(e) => setCharHint(e.target.value)} placeholder="描述要生成的角色…" />
            <button className="btn-primary shrink-0" onClick={aiCharacter} disabled={busy}>AI 生成</button>
          </div>
          <ul className="space-y-2">
            {chars.map((c) => (
              <li key={c.id} className="rounded-lg border border-slate-200 p-3 text-sm">
                <strong>{c.name}</strong> · {c.role}
                <p className="mt-1 text-slate-600">{c.summary}</p>
              </li>
            ))}
          </ul>
          <Link to={`/books/${id}/characters`} className="text-sm text-brand-600 hover:underline">打开完整角色编辑器 →</Link>
          <button className="btn-primary" onClick={() => saveStep(4)} disabled={chars.length < 1}>
            下一步：章节大纲
          </button>
        </div>
      )}

      {step === 4 && (
        <div className="card space-y-4 p-6">
          <h3 className="font-semibold">Step 4 · 章节大纲</h3>
          <p className="text-sm text-slate-500">AI 将根据梗概、世界观、角色生成前若干章规划，之后可在「章节规划」里细改。</p>
          <div className="flex gap-4">
            <div><label className="label">起始章</label><input className="input w-24" type="number" value={outlineStart} onChange={(e) => setOutlineStart(Number(e.target.value))} /></div>
            <div><label className="label">生成章数</label><input className="input w-24" type="number" value={outlineCount} onChange={(e) => setOutlineCount(Number(e.target.value))} /></div>
          </div>
          <button className="btn-primary" onClick={aiOutline} disabled={busy}>
            <Sparkles className="h-4 w-4" /> AI 生成章节规划
          </button>
          <Link to={`/books/${id}/outline`} className="block text-sm text-brand-600 hover:underline">手动编辑大纲 →</Link>
          <button className="btn-primary" onClick={() => setStep(5)}>下一步：开始写作</button>
        </div>
      )}

      {step === 5 && (
        <div className="card space-y-4 p-6 text-center">
          <h3 className="text-xl font-semibold">设定完成</h3>
          <p className="text-slate-600">本书写作偏好将自动生成；平台合规规范由系统内置。现在可以进入第 1 章编辑器，使用 AI 生成本章正文。</p>
          <div className="flex justify-center gap-3 pt-4">
            <button className="btn-secondary" onClick={finish}>完成向导</button>
            <Link to={`/books/${id}/write/1`} className="btn-primary">写第 1 章</Link>
          </div>
        </div>
      )}
    </div>
  );
}
