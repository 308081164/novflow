import type { ChapterPlan } from "../api";

/** 与后端 chapter_plan_has_outline 一致：占位「第N章」不算已规划。 */
export function planHasOutlineContent(p: Pick<
  ChapterPlan,
  "chapter_no" | "title" | "plot_points" | "scene" | "comedy_core" | "comedy_hook" | "character_names" | "meta_json"
>): boolean {
  if (p.plot_points?.trim()) return true;
  if (p.scene?.trim()) return true;
  if (p.comedy_core?.trim() || p.comedy_hook?.trim()) return true;
  if (p.character_names?.trim()) return true;
  const title = p.title?.trim() || "";
  if (title && title !== `第${p.chapter_no}章` && title !== `第 ${p.chapter_no} 章`) return true;
  const meta = p.meta_json || {};
  for (const key of ["events", "cast", "entrances", "exits"] as const) {
    const v = meta[key];
    if (Array.isArray(v) && v.some((x) => String(x).trim())) return true;
    if (typeof v === "string" && v.trim()) return true;
  }
  return false;
}
