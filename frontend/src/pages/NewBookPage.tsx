import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FileUp, Plus, X } from "lucide-react";
import { api } from "../api";
import { PageHeader } from "../components/Layout";

type CreateMode = "blank" | "import";

const MODES = [
  {
    id: "blank" as const,
    name: "从零开始（推荐）",
    desc: "空白项目 + AI 对话助手：头脑风暴 → 卡片采纳 → 写作",
    tag: "新建",
  },
  {
    id: "import" as const,
    name: "导入已有书籍",
    desc: "上传角色设定、世界观、故事大纲、写作偏好与规约等文档，快速初始化项目",
    tag: "导入",
  },
];

const GENRE_PRESETS = [
  "现实",
  "悬疑",
  "喜剧",
  "玄幻",
  "科幻",
  "言情",
  "历史",
  "都市",
  "奇幻",
  "惊悚",
  "武侠",
  "仙侠",
];

const ACCEPT_DOCS = ".txt,.md,.markdown";

function GenrePicker({
  selected,
  custom,
  onToggle,
  onCustomChange,
}: {
  selected: string[];
  custom: string;
  onToggle: (g: string) => void;
  onCustomChange: (v: string) => void;
}) {
  const combined = useMemo(() => {
    const parts = [...selected];
    const extra = custom
      .split(/[/·、,，]/)
      .map((s) => s.trim())
      .filter(Boolean)
      .filter((s) => !parts.includes(s));
    return [...parts, ...extra].join(" · ");
  }, [selected, custom]);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {GENRE_PRESETS.map((g) => {
          const active = selected.includes(g);
          return (
            <button
              key={g}
              type="button"
              onClick={() => onToggle(g)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition ${
                active
                  ? "bg-brand-600 text-white shadow-sm"
                  : "bg-slate-100 text-slate-600 ring-1 ring-slate-200 hover:bg-slate-200"
              }`}
            >
              {g}
            </button>
          );
        })}
      </div>
      <input
        className="input text-sm"
        value={custom}
        onChange={(e) => onCustomChange(e.target.value)}
        placeholder="自定义类型，多个用 · 或逗号分隔，如：现实 · 悬疑"
      />
      {combined && (
        <p className="text-xs text-slate-500">
          已选类型：<span className="font-medium text-slate-700">{combined}</span>
        </p>
      )}
    </div>
  );
}

function FileField({
  label,
  hint,
  multiple,
  files,
  onChange,
}: {
  label: string;
  hint?: string;
  multiple?: boolean;
  files: File[];
  onChange: (files: File[]) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50/50 p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-sm font-medium text-slate-800">{label}</div>
          {hint && <p className="mt-0.5 text-xs text-slate-500">{hint}</p>}
        </div>
        <button
          type="button"
          className="btn-secondary shrink-0 py-1 text-xs"
          onClick={() => inputRef.current?.click()}
        >
          <FileUp className="h-3.5 w-3.5" />
          选择文件
        </button>
      </div>
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        accept={ACCEPT_DOCS}
        multiple={multiple}
        onChange={(e) => {
          const list = Array.from(e.target.files || []);
          onChange(multiple ? [...files, ...list] : list.slice(0, 1));
          e.target.value = "";
        }}
      />
      {files.length > 0 && (
        <ul className="mt-2 space-y-1">
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`} className="flex items-center justify-between gap-2 rounded bg-white px-2 py-1 text-xs ring-1 ring-slate-100">
              <span className="truncate text-slate-700">{f.name}</span>
              <button
                type="button"
                className="shrink-0 text-slate-400 hover:text-red-600"
                onClick={() => onChange(files.filter((_, j) => j !== i))}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function NewBookPage() {
  const nav = useNavigate();
  const [mode, setMode] = useState<CreateMode>("blank");
  const [title, setTitle] = useState("");
  const [selectedGenres, setSelectedGenres] = useState<string[]>([]);
  const [customGenre, setCustomGenre] = useState("");
  const [premise, setPremise] = useState("");
  const [targetChapters, setTargetChapters] = useState(300);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [worldviewFiles, setWorldviewFiles] = useState<File[]>([]);
  const [outlineFiles, setOutlineFiles] = useState<File[]>([]);
  const [writingPrefsFiles, setWritingPrefsFiles] = useState<File[]>([]);
  const [conventionsFiles, setConventionsFiles] = useState<File[]>([]);
  const [characterFiles, setCharacterFiles] = useState<File[]>([]);
  const [adaptWithAi, setAdaptWithAi] = useState(true);

  const genre = useMemo(() => {
    const parts = [...selectedGenres];
    customGenre
      .split(/[/·、,，]/)
      .map((s) => s.trim())
      .filter(Boolean)
      .forEach((g) => {
        if (!parts.includes(g)) parts.push(g);
      });
    return parts.join(" · ");
  }, [selectedGenres, customGenre]);

  const toggleGenre = (g: string) => {
    setSelectedGenres((prev) => (prev.includes(g) ? prev.filter((x) => x !== g) : [...prev, g]));
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) {
      setError("请填写书名");
      return;
    }
    setLoading(true);
    setError("");
    try {
      if (mode === "blank") {
        const book = await api.createBook({
          title: title.trim(),
          blurb: premise,
          premise,
          genre,
          template_id: "blank",
          target_chapters: targetChapters,
        });
        nav(`/books/${book.id}/setup`);
        return;
      }

      const form = new FormData();
      form.append("title", title.trim());
      form.append("genre", genre);
      form.append("premise", premise);
      form.append("target_chapters", String(targetChapters));
      form.append("adapt_with_ai", adaptWithAi ? "true" : "false");
      if (worldviewFiles[0]) form.append("worldview", worldviewFiles[0]);
      if (outlineFiles[0]) form.append("outline", outlineFiles[0]);
      if (writingPrefsFiles[0]) form.append("writing_prefs", writingPrefsFiles[0]);
      if (conventionsFiles[0]) form.append("conventions", conventionsFiles[0]);
      for (const f of characterFiles) {
        form.append("characters", f);
      }

      const book = await api.importBook(form);
      if (book.adapt_warning) {
        window.alert(book.adapt_warning);
      }
      nav(`/books/${book.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-2xl">
      <PageHeader title="新建书籍" desc="从零创建，或导入已有设定文档" />
      <form onSubmit={submit} className="card space-y-6 p-6">
        <div>
          <label className="label">创建方式</label>
          <div className="space-y-3">
            {MODES.map((t) => (
              <label
                key={t.id}
                className={`flex cursor-pointer items-start gap-3 rounded-lg border p-4 transition ${
                  mode === t.id ? "border-brand-500 bg-brand-50" : "border-slate-200 hover:border-slate-300"
                }`}
              >
                <input
                  type="radio"
                  name="mode"
                  value={t.id}
                  checked={mode === t.id}
                  onChange={() => setMode(t.id)}
                  className="mt-1"
                />
                <div>
                  <div className="font-medium">
                    {t.name} <span className="text-xs text-brand-600">({t.tag})</span>
                  </div>
                  <p className="mt-1 text-sm text-slate-500">{t.desc}</p>
                </div>
              </label>
            ))}
          </div>
        </div>

        <div>
          <label className="label">书名 *</label>
          <input
            className="input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            placeholder="你的小说书名"
          />
        </div>

        <div>
          <label className="label">类型</label>
          <GenrePicker
            selected={selectedGenres}
            custom={customGenre}
            onToggle={toggleGenre}
            onCustomChange={setCustomGenre}
          />
        </div>

        <div>
          <label className="label">一句话梗概</label>
          <textarea
            className="input min-h-[80px]"
            value={premise}
            onChange={(e) => setPremise(e.target.value)}
            placeholder="核心冲突与卖点（向导中可再完善）"
          />
        </div>

        <div>
          <label className="label">计划总章数</label>
          <input
            className="input"
            type="number"
            min={10}
            max={2000}
            value={targetChapters}
            onChange={(e) => setTargetChapters(Number(e.target.value))}
          />
        </div>

        {mode === "import" && (
          <div className="space-y-3 border-t border-slate-100 pt-4">
            <div className="flex items-center gap-2 text-sm font-medium text-slate-800">
              <Plus className="h-4 w-4 text-brand-600" />
              上传设定文档（txt / md，可选填）
            </div>
            <FileField
              label="角色设定"
              hint="可上传多个文件，每个文件对应一名角色；文件名建议含角色名"
              multiple
              files={characterFiles}
              onChange={setCharacterFiles}
            />
            <FileField
              label="世界观"
              hint="时代背景、舞台、规则等"
              files={worldviewFiles}
              onChange={setWorldviewFiles}
            />
            <FileField
              label="故事大纲"
              hint="主线剧情、阶段划分或章节规划"
              files={outlineFiles}
              onChange={setOutlineFiles}
            />
            <FileField
              label="写作偏好"
              hint="文风、视角、节奏等个人偏好"
              files={writingPrefsFiles}
              onChange={setWritingPrefsFiles}
            />
            <FileField
              label="写作规约"
              hint="禁忌、平台规范、本书特有规则"
              files={conventionsFiles}
              onChange={setConventionsFiles}
            />
            <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-slate-200 bg-white p-3">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={adaptWithAi}
                onChange={(e) => setAdaptWithAi(e.target.checked)}
              />
              <div>
                <div className="text-sm font-medium text-slate-800">AI 梳理导入内容（推荐）</div>
                <p className="mt-0.5 text-xs text-slate-500">
                  上传后由 AI 整理为系统角色卡、世界观、大纲等结构化格式；未配置 API Key 时自动按原文导入
                </p>
              </div>
            </label>
          </div>
        )}

        {error && <p className="text-sm text-red-600">{error}</p>}
        <button type="submit" className="btn-primary" disabled={loading}>
          {loading
            ? mode === "import" && adaptWithAi
              ? "AI 正在梳理导入内容…"
              : "处理中…"
            : mode === "blank"
              ? "创建并进入 AI 助手"
              : "导入并创建书籍"}
        </button>
      </form>
    </div>
  );
}
