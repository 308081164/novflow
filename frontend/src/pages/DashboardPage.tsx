import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { BookOpen, FileUp, Loader2, Pencil, Plus, Trash2 } from "lucide-react";
import { api, Book } from "../api";
import { PageHeader, EmptyState, StatCard, Badge } from "../components/Layout";

function BookEditModal({
  book,
  onClose,
  onSaved,
}: {
  book: Book;
  onClose: () => void;
  onSaved: (updated: Book) => void;
}) {
  const [title, setTitle] = useState(book.title);
  const [genre, setGenre] = useState(book.genre);
  const [synopsis, setSynopsis] = useState(book.premise || book.blurb);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    if (!title.trim()) {
      setError("书名不能为空");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const updated = await api.updateBook(book.id, {
        title: title.trim(),
        genre: genre.trim(),
        blurb: synopsis.trim(),
        premise: synopsis.trim(),
      });
      onSaved(updated);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="card w-full max-w-lg p-6">
        <h3 className="text-lg font-semibold">编辑作品信息</h3>
        <p className="mt-1 text-xs text-slate-500">修改书名、类型与简介；写作智能体与 AI 创作助手也可通过卡片更新。</p>
        <div className="mt-4 space-y-3">
          <div>
            <label className="label">书名</label>
            <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div>
            <label className="label">类型</label>
            <input
              className="input"
              value={genre}
              onChange={(e) => setGenre(e.target.value)}
              placeholder="如：都市异能 / 脑洞搞笑"
            />
          </div>
          <div>
            <label className="label">简介</label>
            <textarea
              className="input min-h-[120px]"
              value={synopsis}
              onChange={(e) => setSynopsis(e.target.value)}
              placeholder="一句话梗概或卖点…"
            />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" className="btn-secondary" onClick={onClose} disabled={saving}>
            取消
          </button>
          <button type="button" className="btn-primary" onClick={save} disabled={saving}>
            {saving ? "保存中…" : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const packageInputRef = useRef<HTMLInputElement>(null);
  const [books, setBooks] = useState<Book[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Book | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<Book | null>(null);
  const [importingPackage, setImportingPackage] = useState(false);

  useEffect(() => {
    api.books().then(setBooks).finally(() => setLoading(false));
  }, []);

  const totalWritten = books.reduce((s, b) => s + b.written_count, 0);
  const totalApproved = books.reduce((s, b) => s + b.approved_count, 0);

  const handleSaved = (updated: Book) => {
    setBooks((prev) => prev.map((b) => (b.id === updated.id ? updated : b)));
  };

  const handleDelete = async () => {
    if (!confirmDelete) return;
    setDeletingId(confirmDelete.id);
    try {
      await api.deleteBook(confirmDelete.id);
      setBooks((prev) => prev.filter((b) => b.id !== confirmDelete.id));
      setConfirmDelete(null);
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "删除失败");
    } finally {
      setDeletingId(null);
    }
  };

  const handleImportPackage = async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".zip") && !file.name.toLowerCase().endsWith(".novflow.zip")) {
      window.alert("请选择 .novflow.zip 书籍包文件");
      return;
    }
    setImportingPackage(true);
    try {
      const book = await api.importPackage(file);
      setBooks((prev) => [book, ...prev]);
      navigate(`/books/${book.id}`);
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "导入失败");
    } finally {
      setImportingPackage(false);
      if (packageInputRef.current) packageInputRef.current.value = "";
    }
  };

  return (
    <div>
      <PageHeader
        title="我的书库"
        desc="管理作品、继续写作或从模板创建新书"
        action={
          <div className="flex flex-wrap gap-2">
            <input
              ref={packageInputRef}
              type="file"
              accept=".zip,.novflow.zip,application/zip"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void handleImportPackage(file);
              }}
            />
            <button
              type="button"
              className="btn-secondary"
              disabled={importingPackage}
              onClick={() => packageInputRef.current?.click()}
            >
              {importingPackage ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <FileUp className="h-4 w-4" />
              )}
              导入书籍包
            </button>
            <Link to="/new" className="btn-primary">
              <Plus className="h-4 w-4" /> 新建书籍
            </Link>
          </div>
        }
      />

      <div className="mb-8 grid gap-4 sm:grid-cols-3">
        <StatCard label="作品数" value={books.length} />
        <StatCard label="已写章节" value={totalWritten} />
        <StatCard label="已批准章节" value={totalApproved} />
      </div>

      {loading ? (
        <p className="text-slate-500">加载中…</p>
      ) : books.length === 0 ? (
        <EmptyState
          title="还没有书籍"
          desc="从零创建你的第一部作品，或使用试笔模板快速体验"
          action={
            <Link to="/new" className="btn-primary">
              新建书籍
            </Link>
          }
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {books.map((book) => (
            <div
              key={book.id}
              className="card group relative p-5 transition hover:border-brand-300 hover:shadow-md"
            >
              <div className="absolute right-3 top-3 flex gap-1 opacity-0 transition group-hover:opacity-100">
                <button
                  type="button"
                  title="编辑作品信息"
                  className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-brand-600"
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setEditing(book);
                  }}
                >
                  <Pencil className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  title="删除书籍"
                  className="rounded-lg p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600"
                  disabled={deletingId === book.id}
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setConfirmDelete(book);
                  }}
                >
                  {deletingId === book.id ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Trash2 className="h-4 w-4" />
                  )}
                </button>
              </div>
              <Link to={`/books/${book.id}`} className="block pr-16">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="text-lg font-semibold group-hover:text-brand-700">{book.title}</h3>
                    <p className="mt-1 line-clamp-2 text-sm text-slate-500">
                      {book.premise || book.blurb || "暂无简介"}
                    </p>
                  </div>
                  <BookOpen className="h-5 w-5 flex-shrink-0 text-slate-300 group-hover:text-brand-500" />
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Badge color="blue">{book.genre.split("·")[0]?.trim() || "网文"}</Badge>
                  <Badge color="green">
                    已写 {book.written_count}/{book.planned_chapters || book.target_chapters || book.chapter_count}
                  </Badge>
                  {book.approved_count > 0 && <Badge color="amber">批准 {book.approved_count}</Badge>}
                </div>
              </Link>
            </div>
          ))}
        </div>
      )}

      {editing && (
        <BookEditModal book={editing} onClose={() => setEditing(null)} onSaved={handleSaved} />
      )}

      {confirmDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="card w-full max-w-md p-6">
            <h3 className="text-lg font-semibold text-slate-900">确认删除书籍？</h3>
            <p className="mt-2 text-sm text-slate-600">
              将永久删除《{confirmDelete.title}》及其全部章节、角色、设定、对话记录与关联图片，此操作不可恢复。
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setConfirmDelete(null)}
                disabled={deletingId !== null}
              >
                取消
              </button>
              <button
                type="button"
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-60"
                onClick={handleDelete}
                disabled={deletingId !== null}
              >
                {deletingId !== null ? "删除中…" : "确认删除"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
