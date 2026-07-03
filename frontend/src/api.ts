const API = "/api/v1";

export type User = {
  id: number;
  email: string;
  display_name: string;
  deepseek_configured: boolean;
};

export type Book = {
  id: number;
  title: string;
  blurb: string;
  platform: string;
  template_id: string;
  genre: string;
  premise: string;
  setup_step: number;
  target_chapters: number;
  words_per_chapter: number;
  planned_chapters: number;
  outline_planned_count: number;
  chapter_count: number;
  written_count: number;
  approved_count: number;
  cover_image_url?: string;
};

export type BookResources = {
  author_preferences: string;
  has_author_preferences: boolean;
  writing_rules: string;
  corpus: string;
  has_writing_rules: boolean;
};

export type SyncSettingsResult = {
  cards_applied: number;
  outline_chapters: number;
  outline_planned_count: number;
  planned_chapters: number;
  characters_synced: number;
  duplicates_removed: number;
  errors: string[];
  target_chapters?: number;
};

export type Worldview = {
  id: number;
  book_id: number;
  era: string;
  setting: string;
  tone: string;
  timeline_text: string;
  taboos: string;
  content: string;
};

export type Character = {
  id: number;
  book_id: number;
  name: string;
  role: string;
  summary: string;
  voice_notes: string;
  content: string;
};

export type ChapterPlan = {
  id: number;
  chapter_no: number;
  title: string;
  mode: string;
  scene: string;
  plot_points: string;
  comedy_core: string;
  status: string;
  character_names?: string;
  meta_json?: Record<string, unknown>;
  synopsis?: string;
  comedy_hook?: string;
};

export type Chapter = {
  id: number;
  chapter_no: number;
  title: string;
  content: string;
  word_count: number;
  status: string;
  approved: boolean;
};

export type LintIssue = {
  rule_id: string;
  severity: string;
  line_no: number;
  excerpt: string;
  snippet: string;
  message: string;
  auto_fixable: boolean;
  blocking?: boolean;
};

export type LintResult = {
  word_count: number;
  issues: LintIssue[];
  error_count: number;
  warn_count: number;
  passed: boolean;
};

export type Job = {
  id: number;
  job_type: string;
  status: string;
  chapter_no: number;
  result_content: string;
  error: string;
};

export type WriteAgentContextStatus = {
  estimated_chars: number;
  estimated_tokens: number;
  system_chars?: number;
  history_chars?: number;
  message_count: number;
  active_message_count: number;
  warn: boolean;
  suggest_compress: boolean;
  has_summary: boolean;
};

export type WriteAgentApplied = {
  chapter_no: number;
  title: string;
  word_count: number;
  previous_content?: string;
};

export type WriteAgentRevertSnapshot = {
  chapter_no: number;
  title: string;
  content: string;
};

export type WriteAgentChatResult = {
  reply: string;
  edits: { chapter_no: number; title?: string; content: string; reason: string }[];
  applied: WriteAgentApplied[];
  revert_snapshots: WriteAgentRevertSnapshot[];
  cards: SetupCard[];
  card_applied: Record<string, unknown>[];
  actions?: SetupAction[];
  images?: GeneratedImage[];
  user_message?: WriteAgentMessage;
  assistant_message?: WriteAgentMessage;
  session_id?: string;
  context_status?: WriteAgentContextStatus;
};

export type WriteAgentMessage = {
  id: number;
  role: "user" | "assistant" | string;
  content: string;
  cards: SetupCard[];
  actions: SetupAction[];
  meta: Record<string, unknown>;
  created_at: string;
};

export type WriteAgentMessagesResult = {
  session_id: string;
  messages: WriteAgentMessage[];
  context_status?: WriteAgentContextStatus;
};

export type WriteAgentCompressResult = {
  ok: boolean;
  message: string;
  archived_count: number;
  summary_message?: WriteAgentMessage;
  context_status: WriteAgentContextStatus;
  messages: WriteAgentMessage[];
};

export type UserSettings = {
  display_name: string;
  deepseek_configured: boolean;
  deepseek_api_key_masked: string;
  jimeng_configured: boolean;
  jimeng_api_key_masked: string;
  jimeng_base_url: string;
  jimeng_model: string;
  image_backend: "jimeng" | "local_dlc" | "off";
  local_dlc_base_url: string;
  local_dlc_tier: string;
  local_dlc_prompt_mode: "raw" | "assist";
  local_dlc_eula_accepted: boolean;
  local_dlc_eula_accepted_at?: string | null;
};

export type ImageEngineStatus = {
  backend: string;
  reachable: boolean;
  status: string;
  tier: string;
  model: string;
  vram_mb: number;
  message: string;
};

export type GeneratedImage = {
  id?: number;
  url: string;
  object_key?: string;
  kind?: string;
  prompt?: string;
  parent_id?: number | null;
  character_id?: number;
  created_at?: string;
  is_active?: boolean;
};

export type SetupCard = {
  id: string;
  type: "premise" | "worldview" | "character" | "outline" | "plot" | "writing_prefs" | string;
  title: string;
  status: "draft" | "applied" | string;
  data: Record<string, unknown>;
};

export type SetupAction = {
  type: "write_chapter" | "open_outline" | "open_overview" | "open_resources" | string;
  label: string;
  chapter_no?: number;
  description?: string;
};

export type SetupMessage = {
  id: number;
  role: "user" | "assistant" | "system";
  content: string;
  cards: SetupCard[];
  actions?: SetupAction[];
  meta?: Record<string, unknown>;
  created_at: string;
};

export type SetupProgress = {
  checklist: { id: string; label: string; done: boolean }[];
  completed: string[];
  pending: string[];
  next_step: number;
  next_action: string;
  character_names: string[];
  outline_written: number;
  outline_target: number;
  has_author_preferences: boolean;
  has_writing_rules: boolean;
};

export type SetupSnapshot = {
  title: string;
  genre: string;
  premise: string;
  target_chapters: number;
  setup_step: number;
  phase: string;
  worldview: { era: string; setting: string; tone: string; content: string };
  characters: { id: number; name: string; role: string; summary: string }[];
  outline_preview: { chapter_no: number; title: string; plot_points: string }[];
  plot_summary: string;
  progress?: SetupProgress;
};

export function getToken() {
  return localStorage.getItem("token");
}

/** 为需鉴权的媒体 URL 附加 access_token，供 img 标签使用 */
export function withMediaAuth(url: string): string {
  if (!url) return url;
  const token = getToken();
  if (!token || url.includes("access_token=")) return url;
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}access_token=${encodeURIComponent(token)}`;
}

export function setToken(t: string) {
  localStorage.setItem("token", t);
}

export function clearToken() {
  localStorage.removeItem("token");
}

function headers(): HeadersInit {
  const token = getToken();
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

/** 带 JWT 鉴权的 fetch；流式/SSE 请求须走此入口，不可裸调 fetch。 */
async function authFetch(path: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(API + path, { ...init, headers: { ...headers(), ...init?.headers } });
  if (res.status === 401) {
    clearToken();
    window.location.href = "/login";
    throw new Error("未登录");
  }
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || `HTTP ${res.status}`);
  }
  return res;
}

async function consumeSseResponse<T>(
  res: Response,
  handlers: {
    onProgress?: (data: Record<string, unknown>) => void;
    onToken?: (text: string) => void;
    onReply?: (text: string) => void;
    onError?: (message: string) => void;
    onDone?: (result: T) => void;
  },
): Promise<T> {
  const reader = res.body?.getReader();
  if (!reader) throw new Error("无法读取流式响应");
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult: T | null = null;

  const dispatch = (block: string) => {
    const lines = block.split("\n");
    let event = "message";
    let dataLine = "";
    for (const line of lines) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      if (line.startsWith("data:")) dataLine = line.slice(5).trim();
    }
    if (!dataLine) return;
    const payload = JSON.parse(dataLine) as Record<string, unknown>;
    if (event === "token" && typeof payload.text === "string") handlers.onToken?.(payload.text);
    if (event === "reply" && typeof payload.text === "string") handlers.onReply?.(payload.text);
    if (event === "progress") handlers.onProgress?.(payload);
    if (event === "error") {
      const msg = String(payload.message || "流式请求失败");
      handlers.onError?.(msg);
      throw new Error(msg);
    }
    if (event === "done") {
      finalResult = payload as T;
      handlers.onDone?.(finalResult);
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (value) {
      buffer += decoder.decode(value, { stream: !done });
    }
    const parts = buffer.split("\n\n");
    buffer = done ? "" : parts.pop() || "";
    for (const part of parts) {
      if (part.trim()) dispatch(part);
    }
    if (done) {
      buffer += decoder.decode(undefined, { stream: false });
      break;
    }
  }
  const tail = buffer.trim();
  if (tail) {
    for (const part of tail.split("\n\n")) {
      if (part.trim()) dispatch(part);
    }
  }
  if (finalResult) return finalResult;
  throw new Error("流式响应未返回完整结果");
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API + path, { ...init, headers: { ...headers(), ...init?.headers } });
  if (res.status === 401) {
    clearToken();
    window.location.href = "/login";
    throw new Error("未登录");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = err.detail;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (res.headers.get("content-type")?.includes("text/plain")) {
    return (await res.text()) as T;
  }
  const text = await res.text();
  try {
    return JSON.parse(text) as T;
  } catch {
    return text as T;
  }
}

function mapPlan(p: ChapterPlan): ChapterPlan {
  return { ...p, synopsis: p.plot_points, comedy_hook: p.comedy_core };
}

export const api = {
  login: (email: string, password: string) =>
    req<{ access_token: string; user: User }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  register: (email: string, password: string, display_name: string) =>
    req<{ access_token: string; user: User }>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, display_name }),
    }),
  me: () => req<User>("/auth/me"),
  health: () =>
    req<{ status: string; deepseek_configured: boolean }>("/health"),

  getSettings: () => req<UserSettings>("/settings"),
  updateSettings: (data: {
    deepseek_api_key?: string;
    display_name?: string;
    jimeng_api_key?: string;
    jimeng_base_url?: string;
    jimeng_model?: string;
    image_backend?: "jimeng" | "local_dlc" | "off";
    local_dlc_base_url?: string;
    local_dlc_tier?: string;
    local_dlc_prompt_mode?: "raw" | "assist";
  }) => req<UserSettings>("/settings", { method: "PUT", body: JSON.stringify(data) }),

  getImageEngineStatus: () => req<ImageEngineStatus>("/settings/image-engine/status"),

  testImageEngine: () =>
    req<{ ok: boolean; message: string }>("/settings/image-engine/test", { method: "POST" }),

  acceptImageEngineEula: () =>
    req<UserSettings>("/settings/image-engine/eula", {
      method: "POST",
      body: JSON.stringify({ accepted: true }),
    }),

  testJimeng: (data?: { api_key?: string; base_url?: string; model?: string }) =>
    req<{ status: string; message: string; model?: string; requested_model?: string }>(
      "/settings/jimeng/test",
      {
        method: "POST",
        body: JSON.stringify(data || {}),
      },
    ),

  generateCover: (bookId: number, prompt?: string) =>
    req<GeneratedImage>(`/books/${bookId}/cover/generate`, {
      method: "POST",
      body: JSON.stringify({ prompt }),
    }),

  uploadCover: async (bookId: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const token = getToken();
    const res = await fetch(`${API}/books/${bookId}/cover/upload`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
    });
    if (res.status === 401) {
      clearToken();
      window.location.href = "/login";
      throw new Error("未登录");
    }
    if (!res.ok) {
      let msg = "上传失败";
      try {
        const j = await res.json();
        msg = typeof j.detail === "string" ? j.detail : msg;
      } catch {
        msg = (await res.text()) || msg;
      }
      throw new Error(msg);
    }
    return res.json() as Promise<GeneratedImage>;
  },

  getCover: (bookId: number) =>
    req<{ url: string; object_key: string }>(`/books/${bookId}/cover`),

  generateCharacterImage: (bookId: number, charId: number, data?: { prompt?: string; parent_object_key?: string }) =>
    req<GeneratedImage>(`/books/${bookId}/characters/${charId}/images/generate`, {
      method: "POST",
      body: JSON.stringify(data || {}),
    }),

  uploadCharacterImage: async (bookId: number, charId: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const token = getToken();
    const res = await fetch(`${API}/books/${bookId}/characters/${charId}/images/upload`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
    });
    if (res.status === 401) {
      clearToken();
      window.location.href = "/login";
      throw new Error("未登录");
    }
    if (!res.ok) {
      let msg = "上传失败";
      try {
        const j = await res.json();
        msg = typeof j.detail === "string" ? j.detail : msg;
      } catch {
        msg = (await res.text()) || msg;
      }
      throw new Error(msg);
    }
    return res.json() as Promise<GeneratedImage>;
  },

  characterImages: (bookId: number, charId: number) =>
    req<GeneratedImage[]>(`/books/${bookId}/characters/${charId}/images`),

  setCharacterActivePortrait: async (bookId: number, charId: number, objectKey: string) => {
    await req<GeneratedImage>(`/books/${bookId}/characters/${charId}/images/active`, {
      method: "POST",
      body: JSON.stringify({ object_key: objectKey }),
    });
    return req<GeneratedImage[]>(`/books/${bookId}/characters/${charId}/images`);
  },

  deleteCharacterImage: (bookId: number, charId: number, index: number) =>
    req<{ ok: boolean }>(`/books/${bookId}/characters/${charId}/images/${index}`, { method: "DELETE" }),

  chapterIllustrations: (bookId: number, chapterNo: number) =>
    req<GeneratedImage[]>(`/books/${bookId}/chapters/${chapterNo}/illustrations`),

  generateIllustration: (
    bookId: number,
    chapterNo: number,
    data?: { passage?: string; prompt?: string; parent_id?: number; character_ids?: number[] },
  ) =>
    req<GeneratedImage>(`/books/${bookId}/chapters/${chapterNo}/illustrations/generate`, {
      method: "POST",
      body: JSON.stringify(data || {}),
    }),

  uploadIllustration: async (bookId: number, chapterNo: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const token = getToken();
    const res = await fetch(`${API}/books/${bookId}/chapters/${chapterNo}/illustrations/upload`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
    });
    if (res.status === 401) {
      clearToken();
      window.location.href = "/login";
      throw new Error("未登录");
    }
    if (!res.ok) {
      let msg = "上传失败";
      try {
        const j = await res.json();
        msg = typeof j.detail === "string" ? j.detail : msg;
      } catch {
        msg = (await res.text()) || msg;
      }
      throw new Error(msg);
    }
    return res.json() as Promise<GeneratedImage>;
  },

  refineImage: (
    bookId: number,
    data: {
      kind: string;
      prompt: string;
      parent_object_key?: string;
      parent_id?: number;
      character_id?: number;
      chapter_no?: number;
    },
  ) =>
    req<GeneratedImage>(`/books/${bookId}/images/refine`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  books: () => req<Book[]>("/books"),
  createBook: (data: {
    title: string;
    blurb?: string;
    premise?: string;
    genre?: string;
    template_id: string;
    target_chapters?: number;
  }) => req<Book>("/books", { method: "POST", body: JSON.stringify({ platform: "fanqie", ...data }) }),

  importBook: async (form: FormData) => {
    const token = getToken();
    const res = await fetch(`${API}/books/import`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
    });
    if (res.status === 401) {
      clearToken();
      window.location.href = "/login";
      throw new Error("未登录");
    }
    if (!res.ok) {
      let msg = "导入失败";
      try {
        const j = await res.json();
        msg = typeof j.detail === "string" ? j.detail : msg;
      } catch {
        msg = (await res.text()) || msg;
      }
      throw new Error(msg);
    }
    return res.json() as Promise<
      Book & {
        imported_characters: number;
        has_worldview: boolean;
        has_outline: boolean;
        has_writing_prefs: boolean;
        ai_adapted: boolean;
        adapt_warning: string;
      }
    >;
  },
  book: (id: number) => req<Book>(`/books/${id}`),
  deleteBook: (id: number) => req<{ ok: boolean }>(`/books/${id}`, { method: "DELETE" }),
  updateBook: (id: number, data: Partial<Pick<Book, "title" | "blurb" | "premise" | "genre">>) =>
    req<Book>(`/books/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  updateSetup: (id: number, data: Partial<Book>) =>
    req<Book>(`/books/${id}/setup`, { method: "PATCH", body: JSON.stringify(data) }),
  exportUrl: (id: number) => `${API}/books/${id}/export`,
  exportPackage: async (id: number) => {
    const token = getToken();
    const res = await fetch(`${API}/books/${id}/export-package`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (res.status === 401) {
      clearToken();
      window.location.href = "/login";
      throw new Error("未登录");
    }
    if (!res.ok) {
      let msg = "导出失败";
      try {
        const j = await res.json();
        msg = typeof j.detail === "string" ? j.detail : msg;
      } catch {
        msg = (await res.text()) || msg;
      }
      throw new Error(msg);
    }
    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") || "";
    const match = cd.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i);
    const filename = match ? decodeURIComponent(match[1] || match[2]) : "book.novflow.zip";
    return { blob, filename };
  },
  importPackage: async (file: File) => {
    const token = getToken();
    const form = new FormData();
    form.append("package", file);
    const res = await fetch(`${API}/books/import-package`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
    });
    if (res.status === 401) {
      clearToken();
      window.location.href = "/login";
      throw new Error("未登录");
    }
    if (!res.ok) {
      let msg = "导入失败";
      try {
        const j = await res.json();
        msg = typeof j.detail === "string" ? j.detail : msg;
      } catch {
        msg = (await res.text()) || msg;
      }
      throw new Error(msg);
    }
    return res.json() as Promise<
      Book & {
        imported_characters: number;
        chapter_plans: number;
        chapters_with_content: number;
        setup_messages: number;
        write_agent_messages: number;
        media_files: number;
        illustrations: number;
      }
    >;
  },
  bookResources: (id: number) => req<BookResources>(`/books/${id}/resources`),
  saveBookResources: (id: number, data: Partial<Pick<BookResources, "author_preferences" | "writing_rules" | "corpus">>) =>
    req<BookResources>(`/books/${id}/resources`, { method: "PATCH", body: JSON.stringify(data) }),
  syncBookSettings: (id: number) =>
    req<SyncSettingsResult>(`/books/${id}/sync-settings`, { method: "POST" }),

  setupChatContext: (bookId: number) =>
    req<{ book: Book; snapshot: SetupSnapshot; messages: SetupMessage[] }>(`/books/${bookId}/setup/chat`),
  setupChatSend: (bookId: number, message: string) =>
    req<{
      user_message: SetupMessage;
      assistant_message: SetupMessage;
      applied: Record<string, unknown>[];
      book: Book;
      snapshot: SetupSnapshot;
    }>(`/books/${bookId}/setup/chat`, { method: "POST", body: JSON.stringify({ message }) }),
  setupChatStream: (
    bookId: number,
    message: string,
    handlers: {
      onProgress?: (data: { step?: string; detail?: string; [key: string]: unknown }) => void;
      onDone?: (result: {
        user_message: SetupMessage;
        assistant_message: SetupMessage;
        applied: Record<string, unknown>[];
        book: Book;
        snapshot: SetupSnapshot;
      }) => void;
      onError?: (message: string) => void;
    },
  ): Promise<{
    user_message: SetupMessage;
    assistant_message: SetupMessage;
    applied: Record<string, unknown>[];
    book: Book;
    snapshot: SetupSnapshot;
  }> =>
    authFetch(`/books/${bookId}/setup/chat/stream`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }).then((res) =>
      consumeSseResponse(res, {
        onProgress: handlers.onProgress,
        onError: handlers.onError,
        onDone: handlers.onDone,
      }),
    ),
  setupChatApply: (bookId: number, card: SetupCard) =>
    req<{ result: Record<string, unknown>; book: Book; snapshot: SetupSnapshot; messages: SetupMessage[] }>(
      `/books/${bookId}/setup/chat/apply`,
      { method: "POST", body: JSON.stringify({ card }) },
    ),
  setupChatFinish: (bookId: number) =>
    req<Book>(`/books/${bookId}/setup/chat/finish`, { method: "POST" }),

  worldview: (bookId: number) => req<Worldview>(`/books/${bookId}/worldview`),
  saveWorldview: (bookId: number, data: Partial<Worldview>) =>
    req<Worldview>(`/books/${bookId}/worldview`, { method: "PUT", body: JSON.stringify(data) }),
  aiWorldview: (bookId: number) =>
    req<Worldview>(`/books/${bookId}/worldview/ai-generate-sync`, { method: "POST" }),

  characters: (bookId: number) => req<Character[]>(`/books/${bookId}/characters`),
  characterCards: (bookId: number) => req<SetupCard[]>(`/books/${bookId}/characters/cards`),
  createCharacter: (bookId: number, data: Partial<Character>) =>
    req<Character>(`/books/${bookId}/characters`, { method: "POST", body: JSON.stringify(data) }),
  updateCharacter: (bookId: number, charId: number, data: Partial<Character>) =>
    req<Character>(`/books/${bookId}/characters/${charId}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteCharacter: (bookId: number, charId: number) =>
    req<{ ok: boolean }>(`/books/${bookId}/characters/${charId}`, { method: "DELETE" }),
  aiCharacter: (bookId: number, hint: string) =>
    req<Character>(`/books/${bookId}/ai/character`, { method: "POST", body: JSON.stringify({ hint }) }),
  aiOutline: (bookId: number, start: number, count: number) =>
    req<{ count: number }>(`/books/${bookId}/ai/outline`, {
      method: "POST",
      body: JSON.stringify({ start_chapter: start, count }),
    }),
  aiRules: (bookId: number) =>
    req<{ writing_rules: string; author_preferences: string }>(`/books/${bookId}/ai/writing-rules`, { method: "POST" }),

  chapterPlans: async (bookId: number) => {
    const plans = await req<ChapterPlan[]>(`/books/${bookId}/plans`);
    return plans.map(mapPlan);
  },
  updateChapterPlan: (bookId: number, no: number, data: { title?: string; synopsis?: string; comedy_hook?: string }) =>
    req<ChapterPlan>(`/books/${bookId}/plans/${no}`, {
      method: "PUT",
      body: JSON.stringify({
        title: data.title,
        plot_points: data.synopsis,
        comedy_core: data.comedy_hook,
      }),
    }),

  chapters: (bookId: number) => req<Chapter[]>(`/books/${bookId}/chapters`),
  chapter: (bookId: number, no: number) => req<Chapter>(`/books/${bookId}/chapters/${no}`),
  updateChapter: (bookId: number, no: number, data: { content: string; title?: string }) =>
    req<Chapter>(`/books/${bookId}/chapters/${no}`, { method: "PUT", body: JSON.stringify(data) }),
  saveChapter: (bookId: number, no: number, content: string, title?: string) =>
    req<Chapter>(`/books/${bookId}/chapters/${no}`, {
      method: "PUT",
      body: JSON.stringify({ content, title }),
    }),

  lint: (bookId: number, no: number, useAi = false) =>
    req<LintResult>(`/books/${bookId}/chapters/${no}/lint?use_ai=${useAi}`),
  lintDraft: (bookId: number, no: number, content: string, includeAi = false) =>
    req<LintResult>(`/books/${bookId}/chapters/${no}/lint`, {
      method: "POST",
      body: JSON.stringify({ content, include_ai: includeAi }),
    }),
  fixDraft: (bookId: number, no: number, content: string) =>
    req<{ content: string; lint: LintResult; fixed_count: number }>(`/books/${bookId}/chapters/${no}/fix-draft`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  fixIssueDraft: (bookId: number, no: number, content: string, issue: Pick<LintIssue, "rule_id" | "line_no">) =>
    req<{ content: string; lint: LintResult }>(`/books/${bookId}/chapters/${no}/fix-issue`, {
      method: "POST",
      body: JSON.stringify({ content, rule_id: issue.rule_id, line_no: issue.line_no }),
    }),
  fixAll: (bookId: number, no: number, content?: string) =>
    req<Chapter>(`/books/${bookId}/chapters/${no}/fix-all`, {
      method: "POST",
      body: JSON.stringify(content ? { content } : {}),
    }),
  fixCommas: (bookId: number, no: number) =>
    req<Chapter>(`/books/${bookId}/chapters/${no}/fix-commas`, { method: "POST" }),
  approve: (bookId: number, no: number) =>
    req<Chapter>(`/books/${bookId}/chapters/${no}/approve`, { method: "POST" }),

  generate: (bookId: number, no: number, instruction = "") =>
    req<Job>(`/books/${bookId}/chapters/${no}/generate`, {
      method: "POST",
      body: JSON.stringify({ instruction }),
    }),
  expand: (bookId: number, no: number, _extra = 500, _instruction = "") =>
    req<Job>(`/books/${bookId}/chapters/${no}/expand`, { method: "POST" }),
  fixAi: (bookId: number, no: number) =>
    req<Job>(`/books/${bookId}/chapters/${no}/fix-ai`, { method: "POST" }),
  job: (bookId: number, jobId: number) => req<Job>(`/books/${bookId}/jobs/${jobId}`),

  writeAgentMessages: (bookId: number, chapterNo?: number) =>
    req<WriteAgentMessagesResult>(
      `/books/${bookId}/write-agent/messages${chapterNo != null ? `?chapter_no=${chapterNo}` : ""}`,
    ),
  writeAgentNewSession: (bookId: number) =>
    req<WriteAgentMessagesResult>(`/books/${bookId}/write-agent/new-session`, { method: "POST" }),
  writeAgentCompressContext: (bookId: number) =>
    req<WriteAgentCompressResult>(`/books/${bookId}/write-agent/compress-context`, { method: "POST" }),
  writeAgentChat: (
    bookId: number,
    body: {
      message: string;
      chapter_no: number;
      draft_content?: string;
      input_text?: string;
      quote?: string | null;
      lint_issues?: { rule_id: string; line_no: number; message: string; excerpt?: string }[];
      resend_from_message_id?: number;
    },
  ) =>
    req<WriteAgentChatResult>(`/books/${bookId}/write-agent/chat`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  writeAgentChatStream: (
    bookId: number,
    body: {
      message: string;
      chapter_no: number;
      draft_content?: string;
      input_text?: string;
      quote?: string | null;
      lint_issues?: { rule_id: string; line_no: number; message: string; excerpt?: string }[];
      resend_from_message_id?: number;
    },
    handlers: {
      onToken?: (text: string) => void;
      onReply?: (text: string) => void;
      onProgress?: (data: Record<string, unknown>) => void;
      onDone?: (result: WriteAgentChatResult) => void;
      onError?: (message: string) => void;
    },
  ): Promise<WriteAgentChatResult> =>
    authFetch(`/books/${bookId}/write-agent/chat/stream`, {
      method: "POST",
      body: JSON.stringify(body),
    }).then((res) =>
      consumeSseResponse<WriteAgentChatResult>(res, {
        onToken: handlers.onToken,
        onReply: handlers.onReply,
        onProgress: handlers.onProgress,
        onError: handlers.onError,
        onDone: handlers.onDone,
      }),
    ),
  writeAgentRevert: (bookId: number, snapshots: WriteAgentRevertSnapshot[]) =>
    req<{ reverted: WriteAgentApplied[] }>(`/books/${bookId}/write-agent/revert`, {
      method: "POST",
      body: JSON.stringify({ snapshots }),
    }),
  writeAgentApply: (bookId: number, card: SetupCard) =>
    req<{ result: Record<string, unknown>; card: SetupCard }>(`/books/${bookId}/write-agent/apply`, {
      method: "POST",
      body: JSON.stringify({ card }),
    }),
};

export function streamJob(
  bookId: number,
  jobId: number,
  onToken: (t: string) => void,
  onDone: (status: string, error?: string) => void,
): () => void {
  let cancelled = false;
  const poll = async () => {
    while (!cancelled) {
      try {
        const j = await api.job(bookId, jobId);
        if (j.status === "done") {
          if (j.result_content) onToken(j.result_content);
          onDone("completed");
          return;
        }
        if (j.status === "failed") {
          onDone("failed", j.error);
          return;
        }
      } catch (e) {
        onDone("failed", String(e));
        return;
      }
      await new Promise((r) => setTimeout(r, 1500));
    }
  };
  poll();
  return () => {
    cancelled = true;
  };
}

export type BookDetail = Book;
