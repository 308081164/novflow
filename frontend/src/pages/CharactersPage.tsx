import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Plus, RefreshCw } from "lucide-react";
import { api, GeneratedImage, SetupCard, SyncSettingsResult } from "../api";
import CharacterPortraitCard from "../components/CharacterPortraitCard";
import { PageHeader } from "../components/Layout";
import { SetupCardEditModal } from "../components/setup/SetupCard";

const EMPTY_CHARACTER: SetupCard = {
  id: "new_character",
  type: "character",
  title: "",
  status: "draft",
  data: { name: "", role: "support", summary: "", voice_notes: "", content: "" },
};

export default function CharactersPage() {
  const { bookId } = useParams();
  const id = Number(bookId);
  const [cards, setCards] = useState<SetupCard[]>([]);
  const [editCard, setEditCard] = useState<SetupCard | null>(null);
  const [syncInfo, setSyncInfo] = useState<SyncSettingsResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [charImages, setCharImages] = useState<Record<number, GeneratedImage[]>>({});
  const [generatingCharId, setGeneratingCharId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const sync = await api.syncBookSettings(id);
      setSyncInfo(sync);
      const list = await api.characterCards(id);
      setCards(list);
      const imgMap: Record<number, GeneratedImage[]> = {};
      for (const c of list) {
        const charId = c.data?.character_id as number | undefined;
        if (charId) {
          try {
            imgMap[charId] = await api.characterImages(id, charId);
          } catch {
            imgMap[charId] = [];
          }
        }
      }
      setCharImages(imgMap);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const saveCard = async (card: SetupCard) => {
    const d = card.data || {};
    const payload = {
      name: String(d.name || card.title || ""),
      role: String(d.role || "support"),
      summary: String(d.summary || ""),
      voice_notes: String(d.voice_notes || ""),
      content: String(d.content || ""),
    };
    const charId = d.character_id as number | undefined;
    if (charId) {
      await api.updateCharacter(id, charId, payload);
    } else {
      await api.createCharacter(id, payload);
    }
    setEditCard(null);
    await load();
  };

  const syncBanner =
    syncInfo &&
    (syncInfo.cards_applied > 0 || syncInfo.duplicates_removed > 0) &&
    `已同步 ${syncInfo.characters_synced} 个角色卡${
      syncInfo.duplicates_removed ? `，合并重复 ${syncInfo.duplicates_removed} 条` : ""
    }`;

  const generateCharImage = async (charId: number) => {
    setGeneratingCharId(charId);
    try {
      const img = await api.generateCharacterImage(id, charId);
      setCharImages((prev) => ({
        ...prev,
        [charId]: [...(prev[charId] || []), img],
      }));
      return img;
    } finally {
      setGeneratingCharId(null);
    }
  };

  const uploadCharImage = async (charId: number, file: File) => {
    const img = await api.uploadCharacterImage(id, charId, file);
    setCharImages((prev) => ({
      ...prev,
      [charId]: [...(prev[charId] || []), img],
    }));
    return img;
  };

  const refineCharImage = async (charId: number, img: GeneratedImage, prompt: string) => {
    const refined = await api.refineImage(id, {
      kind: "character",
      prompt,
      parent_object_key: img.object_key,
      character_id: charId,
    });
    setCharImages((prev) => ({
      ...prev,
      [charId]: [...(prev[charId] || []), refined],
    }));
    return refined;
  };

  const setActivePortrait = async (charId: number, objectKey: string) => {
    const updated = await api.setCharacterActivePortrait(id, charId, objectKey);
    setCharImages((prev) => ({ ...prev, [charId]: updated }));
    return updated;
  };

  const deleteCharacter = async (charId: number) => {
    await api.deleteCharacter(id, charId);
    setCharImages((prev) => {
      const next = { ...prev };
      delete next[charId];
      return next;
    });
    setCards((prev) => prev.filter((c) => c.data?.character_id !== charId));
  };

  return (
    <div>
      <Link to={`/books/${id}`} className="mb-4 inline-flex items-center gap-1 text-sm text-brand-600 hover:underline">
        <ArrowLeft className="h-4 w-4" /> 返回书籍
      </Link>
      <PageHeader
        title="角色管理"
        desc="与写作智能体、AI 创作助手共用同一份角色卡数据"
        action={
          <div className="flex gap-2">
            <button type="button" className="btn-secondary text-xs" onClick={load} disabled={loading}>
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> 同步
            </button>
            <button
              type="button"
              className="btn-primary"
              onClick={() => setEditCard({ ...EMPTY_CHARACTER, id: `new_${Date.now()}` })}
            >
              <Plus className="h-4 w-4" /> 新建角色
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
      ) : cards.length === 0 ? (
        <div className="card p-8 text-center text-sm text-slate-500">
          尚无角色。在写作智能体中说「调出男主角色卡」，或在{" "}
          <Link to={`/books/${id}/setup`} className="text-brand-600 underline">
            AI 创作助手
          </Link>{" "}
          中设计并采纳角色。
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {cards.map((c) => {
            const charId = c.data?.character_id as number | undefined;
            const imgs = charId ? charImages[charId] || [] : [];
            return (
              <CharacterPortraitCard
                key={c.id}
                card={c}
                images={imgs}
                generating={charId ? generatingCharId === charId : false}
                onEdit={() => setEditCard(c)}
                onDelete={charId ? () => deleteCharacter(charId) : undefined}
                onGenerate={charId ? () => generateCharImage(charId) : undefined}
                onUpload={charId ? (file) => uploadCharImage(charId, file) : undefined}
                onRefine={charId ? (img, prompt) => refineCharImage(charId, img, prompt) : undefined}
                onSetActive={charId ? (objectKey) => setActivePortrait(charId, objectKey) : undefined}
                onImagesUpdated={
                  charId
                    ? (next) => setCharImages((prev) => ({ ...prev, [charId]: next }))
                    : undefined
                }
              />
            );
          })}
        </div>
      )}

      {editCard && (
        <SetupCardEditModal
          card={editCard}
          onClose={() => setEditCard(null)}
          onSave={(updated) => saveCard(updated)}
        />
      )}
    </div>
  );
}
