import type { SetupCard, SetupMessage } from "../api";

const LEAKED_RE = /\[已输出卡片[·.．](\w+)[-－](\w+)\]\s*([^\n\[]+)/g;
const INTERNAL_RE = /\[已输出卡片[·.．]/;

/** 兼容历史消息：content 里误存了 JSON / 泄漏标记时，前端恢复 reply + cards */
export function normalizeSetupMessage(m: SetupMessage): SetupMessage {
  if (m.role !== "assistant") return m;

  let content = (m.content || "").trim();
  let cards = [...(m.cards || [])];

  if (INTERNAL_RE.test(content)) {
    const recovered = recoverCardsFromLeakedText(content, m.id);
    if (!cards.length && recovered.cards.length) cards = recovered.cards;
    content = recovered.cleaned || (cards.length ? fallbackReplyFromCards(cards) : "");
  }

  if (looksLikeJson(content)) {
    const parsed = tryParseAgentPayload(content);
    if (parsed) {
      content = parsed.reply || content;
      if (!cards.length) cards = parsed.cards;
    }
  }

  if (!content && cards.length > 0) {
    content = fallbackReplyFromCards(cards);
  }

  return { ...m, content, cards };
}

function recoverCardsFromLeakedText(text: string, messageId?: number): { cleaned: string; cards: SetupCard[] } {
  const cards: SetupCard[] = [];
  let idx = 0;
  for (const m of text.matchAll(LEAKED_RE)) {
    const type = m[1];
    if (type.includes("draft")) continue;
    const status = m[2];
    const title = m[3].trim();
    const data: Record<string, unknown> =
      type === "plot" ? { summary: title, title } : type === "outline" ? { chapters: [], note: title } : {};
    cards.push({
      id: messageId != null ? `m${messageId}_${idx++}` : `leak_${idx++}`,
      type,
      title,
      status,
      data,
    });
  }
  const cleaned = text.replace(LEAKED_RE, "").replace(INTERNAL_RE, "").trim();
  return { cleaned, cards };
}

function fallbackReplyFromCards(cards: SetupCard[]): string {
  const names = cards.map((c) => {
    if (c.type === "character" && c.data?.name) return `「${c.data.name}」`;
    return `「${c.title || c.type}」`;
  });
  return `已生成 ${cards.length} 张设定卡片：${names.join("、")}。请查看下方卡片并点「采纳」写入。`;
}

function looksLikeJson(s: string): boolean {
  const t = s.trim();
  return t.startsWith("{") && t.includes('"reply"');
}

function tryParseAgentPayload(text: string): { reply: string; cards: SetupCard[] } | null {
  const blob = extractJsonBlob(text);
  if (!blob) return null;
  try {
    const data = JSON.parse(blob) as Record<string, unknown>;
    const cards = normalizeCards(data.cards);
    const reply = String(data.reply || "").trim();
    if (reply || cards.length) return { reply, cards };
  } catch {
    /* fall through */
  }
  return null;
}

function extractJsonBlob(text: string): string | null {
  let t = text.trim();
  const fence = t.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fence) t = fence[1].trim();
  if (t.startsWith("{") && t.endsWith("}")) return t;
  const start = t.indexOf("{");
  const end = t.lastIndexOf("}");
  if (start >= 0 && end > start) return t.slice(start, end + 1);
  return null;
}

function normalizeCards(raw: unknown): SetupCard[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((c): c is Record<string, unknown> => typeof c === "object" && c !== null)
    .map((c, i) => ({
      id: String(c.id || `recovered_${i}`),
      type: String(c.type || "premise"),
      title: String(c.title || c.type || "设定"),
      status: String(c.status || "draft"),
      data: (c.data as Record<string, unknown>) || {},
    }));
}
