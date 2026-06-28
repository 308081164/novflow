import type {
  SetupAction,
  SetupCard,
  WriteAgentApplied,
  WriteAgentMessage,
  WriteAgentRevertSnapshot,
  GeneratedImage,
} from "../api";

export type WriteAgentUserMsg = {
  id: string;
  dbId?: number;
  role: "user";
  payload: string;
  inputText: string;
  quote: string | null;
};

export type TaskPlanStep = {
  id?: string;
  description?: string;
  action?: string;
};

export type TaskPlanMeta = {
  execution_mode?: string;
  resources?: string[];
  steps?: TaskPlanStep[];
};

export type WriteAgentAssistantMsg = {
  id: string;
  dbId?: number;
  role: "assistant";
  content: string;
  streaming?: boolean;
  applied?: WriteAgentApplied[];
  revertSnapshots?: WriteAgentRevertSnapshot[];
  reverted?: boolean;
  cards?: SetupCard[];
  actions?: SetupAction[];
  images?: GeneratedImage[];
  isContextSummary?: boolean;
  archivedCount?: number;
  taskPlan?: TaskPlanMeta;
};

export type WriteAgentChatMsg = WriteAgentUserMsg | WriteAgentAssistantMsg;

export function writeAgentMessageToChat(m: WriteAgentMessage): WriteAgentChatMsg {
  const dbId = m.id;
  const id = `db_${m.id}`;

  if (m.role === "user") {
    return {
      id,
      dbId,
      role: "user",
      payload: m.content,
      inputText: String(m.meta?.input_text || m.content),
      quote: typeof m.meta?.quote === "string" ? m.meta.quote : null,
    };
  }

  const applied = (m.meta?.applied as WriteAgentApplied[] | undefined)?.filter(Boolean);
  const revertSnapshots = (m.meta?.revert_snapshots as WriteAgentRevertSnapshot[] | undefined)?.filter(Boolean);
  const isContextSummary = Boolean(m.meta?.context_summary);
  const archivedCount =
    typeof m.meta?.archived_count === "number" ? (m.meta.archived_count as number) : undefined;
  const images = (m.meta?.images as GeneratedImage[] | undefined)?.filter(Boolean);
  const taskPlan = m.meta?.task_plan as TaskPlanMeta | undefined;
  let content = m.content;
  if (applied?.length) {
    content += `\n\n✅ 已写入：${applied.map((a) => `第${a.chapter_no}章`).join("、")}`;
  }

  return {
    id,
    dbId,
    role: "assistant",
    content,
    applied: applied?.length ? applied : undefined,
    revertSnapshots: revertSnapshots?.length ? revertSnapshots : undefined,
    cards: m.cards?.length ? m.cards : undefined,
    actions: m.actions?.length ? m.actions : undefined,
    images: images?.length ? images : undefined,
    isContextSummary,
    archivedCount,
    taskPlan: taskPlan?.steps?.length ? taskPlan : undefined,
  };
}

export function writeAgentMessagesToChat(messages: WriteAgentMessage[]): WriteAgentChatMsg[] {
  return messages.map(writeAgentMessageToChat);
}
