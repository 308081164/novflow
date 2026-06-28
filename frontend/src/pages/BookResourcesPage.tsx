import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, BookOpen, Sparkles } from "lucide-react";
import { api } from "../api";
import { PageHeader } from "../components/Layout";

export default function BookResourcesPage() {
  const { bookId } = useParams();
  const id = Number(bookId);
  const [authorPreferences, setAuthorPreferences] = useState("");
  const [corpus, setCorpus] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.bookResources(id).then((r) => {
      setAuthorPreferences(r.author_preferences || r.writing_rules);
      setCorpus(r.corpus);
    });
  }, [id]);

  const save = async () => {
    await api.saveBookResources(id, { author_preferences: authorPreferences, corpus });
    setMsg("已保存");
  };

  const genPrefs = async () => {
    setBusy(true);
    try {
      const res = await api.aiRules(id);
      setAuthorPreferences(res.author_preferences || res.writing_rules);
      setMsg("本书写作偏好已生成");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-4xl">
      <Link to={`/books/${id}`} className="mb-4 inline-flex items-center gap-1 text-sm text-brand-600 hover:underline">
        <ArrowLeft className="h-4 w-4" /> 返回书籍
      </Link>
      <PageHeader
        title="写作偏好与语料库"
        desc="生成章节与智能体写作时会自动注入；平台合规与语言规范由系统内置，无需在此维护"
      />
      {msg && <p className="mb-4 text-sm text-emerald-600">{msg}</p>}

      <div className="card mb-6 p-6">
        <div className="mb-3 flex items-center justify-between gap-2">
          <h3 className="flex items-center gap-2 font-semibold">
            <BookOpen className="h-5 w-5 text-brand-600" /> 本书写作偏好
          </h3>
          <button type="button" className="btn-secondary text-xs" onClick={genPrefs} disabled={busy}>
            <Sparkles className="h-3.5 w-3.5" /> AI 生成
          </button>
        </div>
        <p className="mb-3 text-xs text-slate-500">
          视角、角色口吻、节奏与本书特有规则；完成创书向导时也会自动生成。平台合规与输出格式等通用规范已内置，不会显示在此。
        </p>
        <textarea
          className="input min-h-[280px] font-mono text-xs"
          value={authorPreferences}
          onChange={(e) => setAuthorPreferences(e.target.value)}
          placeholder="尚未配置本书写作偏好，可点击「AI 生成」或在创书向导最后一步完成设定。"
        />
      </div>

      <div className="card p-6">
        <h3 className="mb-1 font-semibold">角色语料库</h3>
        <p className="mb-3 text-xs text-slate-500">
          各角色口头禅、网络梗、对话范例等；生成正文时会作为补充参考（Markdown 格式，可按角色分段）。
        </p>
        <textarea
          className="input min-h-[240px] font-mono text-xs"
          value={corpus}
          onChange={(e) => setCorpus(e.target.value)}
          placeholder={"## 陈默\n- 口头禅：……\n\n## 冷月\n- 对话范例：……"}
        />
      </div>

      <button type="button" className="btn-primary mt-4" onClick={save}>
        保存全部
      </button>
    </div>
  );
}
