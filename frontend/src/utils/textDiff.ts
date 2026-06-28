import { escapeHtml } from "./lintHighlight";

export type DiffLineKind = "equal" | "add" | "del" | "change-old" | "change-new";

export type DiffDisplayLine = {
  kind: DiffLineKind;
  text: string;
  lineId: string;
  blockId?: string;
};

export type DiffHunk = {
  id: string;
  blockId: string;
  kind: DiffLineKind;
  text: string;
  accepted: boolean | null;
};

/** 行级 LCS diff，用于 Cursor 式增删改高亮 */
export function diffTextLines(oldText: string, newText: string): DiffDisplayLine[] {
  const a = oldText.split("\n");
  const b = newText.split("\n");
  const m = a.length;
  const n = b.length;
  const dp: number[][] = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0));
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      dp[i][j] = a[i - 1] === b[j - 1] ? dp[i - 1][j - 1] + 1 : Math.max(dp[i - 1][j], dp[i][j - 1]);
    }
  }

  type Op = { kind: "equal" | "add" | "del"; aIdx?: number; bIdx?: number };
  const ops: Op[] = [];
  let i = m;
  let j = n;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && a[i - 1] === b[j - 1]) {
      ops.push({ kind: "equal", aIdx: i - 1, bIdx: j - 1 });
      i -= 1;
      j -= 1;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      ops.push({ kind: "add", bIdx: j - 1 });
      j -= 1;
    } else {
      ops.push({ kind: "del", aIdx: i - 1 });
      i -= 1;
    }
  }
  ops.reverse();

  const raw: DiffDisplayLine[] = [];
  let blockCounter = 0;
  let currentBlockId: string | undefined;
  let lineSeq = 0;

  for (let k = 0; k < ops.length; k++) {
    const op = ops[k];
    if (op.kind === "equal") {
      currentBlockId = undefined;
      raw.push({
        kind: "equal",
        text: b[op.bIdx!],
        lineId: `l${lineSeq++}`,
      });
      continue;
    }
    if (!currentBlockId) {
      blockCounter += 1;
      currentBlockId = `b${blockCounter}`;
    }
    if (op.kind === "del") {
      const next = ops[k + 1];
      if (next?.kind === "add") {
        raw.push({
          kind: "change-old",
          text: a[op.aIdx!],
          lineId: `l${lineSeq++}`,
          blockId: currentBlockId,
        });
        raw.push({
          kind: "change-new",
          text: b[next.bIdx!],
          lineId: `l${lineSeq++}`,
          blockId: currentBlockId,
        });
        k += 1;
      } else {
        raw.push({
          kind: "del",
          text: a[op.aIdx!],
          lineId: `l${lineSeq++}`,
          blockId: currentBlockId,
        });
      }
      continue;
    }
    raw.push({
      kind: "add",
      text: b[op.bIdx!],
      lineId: `l${lineSeq++}`,
      blockId: currentBlockId,
    });
  }
  return raw;
}

/** 从 diff 提取带稳定 ID 的 hunk 列表 */
export function diffTextToHunks(oldText: string, newText: string): DiffHunk[] {
  const lines = diffTextLines(oldText, newText);
  return lines.map((line, idx) => ({
    id: line.lineId || `h${idx}`,
    blockId: line.blockId ?? line.lineId,
    kind: line.kind,
    text: line.text,
    accepted: null,
  }));
}

export function countDiffChanges(lines: DiffDisplayLine[]): { added: number; removed: number; changed: number } {
  let added = 0;
  let removed = 0;
  let changed = 0;
  for (const line of lines) {
    if (line.kind === "add") added += 1;
    else if (line.kind === "del") removed += 1;
    else if (line.kind === "change-new") changed += 1;
  }
  return { added, removed, changed };
}

function diffLineClass(kind: DiffLineKind): string {
  switch (kind) {
    case "add":
      return "diff-line-add";
    case "del":
    case "change-old":
      return "diff-line-del";
    case "change-new":
      return "diff-line-change";
    default:
      return "";
  }
}

function diffLinePrefix(kind: DiffLineKind): string {
  switch (kind) {
    case "add":
      return "+ ";
    case "del":
      return "− ";
    case "change-old":
      return "− ";
    case "change-new":
      return "~ ";
    default:
      return "";
  }
}

export function textToDiffHtml(
  lines: DiffDisplayLine[],
  hunks?: DiffHunk[],
  options?: { interactive?: boolean },
): string {
  const interactive = options?.interactive ?? false;
  const blockDecision = new Map<string, boolean | null>();
  if (hunks) {
    for (const h of hunks) {
      if (h.kind !== "equal") {
        blockDecision.set(h.blockId, h.accepted);
      }
    }
  }

  const parts: string[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.kind === "equal") {
      const inner = escapeHtml(line.text) || "<br>";
      parts.push(`<div class="lint-line">${inner}</div>`);
      i += 1;
      continue;
    }

    const blockId = line.blockId ?? `b${i}`;
    const blockLines: DiffDisplayLine[] = [];
    while (i < lines.length && lines[i].kind !== "equal" && lines[i].blockId === blockId) {
      blockLines.push(lines[i]);
      i += 1;
    }

    const accepted = blockDecision.get(blockId) ?? null;
    const statusClass =
      accepted === true ? " diff-block-accepted" : accepted === false ? " diff-block-rejected" : "";

    let blockHtml = `<div class="diff-block${statusClass}" data-block-id="${escapeHtml(blockId)}">`;
    if (interactive) {
      blockHtml += `<div class="diff-block-actions">`;
      blockHtml += `<button type="button" class="diff-hunk-btn diff-hunk-accept" data-action="accept" data-block-id="${escapeHtml(blockId)}">采纳</button>`;
      blockHtml += `<button type="button" class="diff-hunk-btn diff-hunk-reject" data-action="reject" data-block-id="${escapeHtml(blockId)}">拒绝</button>`;
      blockHtml += `</div>`;
    }
    for (const bl of blockLines) {
      const inner = escapeHtml(bl.text) || "<br>";
      blockHtml += `<div class="lint-line ${diffLineClass(bl.kind)}">${diffLinePrefix(bl.kind)}${inner}</div>`;
    }
    blockHtml += `</div>`;
    parts.push(blockHtml);
  }
  return parts.join("");
}
