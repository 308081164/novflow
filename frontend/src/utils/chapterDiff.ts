import { diffTextLines, diffTextToHunks, type DiffDisplayLine, type DiffHunk } from "./textDiff";

export type ChapterDiffState = {
  baseContent: string;
  currentContent: string;
  showDiff: boolean;
  hunks: DiffHunk[];
};

export function createChapterDiffState(baseContent: string, currentContent: string): ChapterDiffState {
  return {
    baseContent,
    currentContent,
    showDiff: true,
    hunks: diffTextToHunks(baseContent, currentContent),
  };
}

export function refreshChapterDiffHunks(state: ChapterDiffState): ChapterDiffState {
  return {
    ...state,
    hunks: diffTextToHunks(state.baseContent, state.currentContent),
  };
}

export function setBlockDecision(hunks: DiffHunk[], blockId: string, accepted: boolean): DiffHunk[] {
  return hunks.map((h) => (h.blockId === blockId && h.kind !== "equal" ? { ...h, accepted } : h));
}

export function acceptAllHunks(hunks: DiffHunk[]): DiffHunk[] {
  return hunks.map((h) => (h.kind === "equal" ? h : { ...h, accepted: true }));
}

export function rejectAllHunks(hunks: DiffHunk[]): DiffHunk[] {
  return hunks.map((h) => (h.kind === "equal" ? h : { ...h, accepted: false }));
}

/** 将单个已采纳 hunk 的新内容合并进 base，使该块从 diff 中消失 */
export function mergeAcceptedBlockIntoBase(
  baseContent: string,
  currentContent: string,
  blockId: string,
): string {
  const diffLines = diffTextLines(baseContent, currentContent);
  const out: string[] = [];
  let i = 0;
  while (i < diffLines.length) {
    const line = diffLines[i];
    if (line.kind === "equal") {
      out.push(line.text);
      i += 1;
      continue;
    }

    const bid = line.blockId ?? `b${i}`;
    const useNew = bid === blockId;

    const blockLines: DiffDisplayLine[] = [];
    while (i < diffLines.length && diffLines[i].kind !== "equal" && diffLines[i].blockId === bid) {
      blockLines.push(diffLines[i]);
      i += 1;
    }

    if (useNew) {
      for (const bl of blockLines) {
        if (bl.kind === "add" || bl.kind === "change-new") {
          out.push(bl.text);
        }
      }
    } else {
      for (const bl of blockLines) {
        if (bl.kind === "del" || bl.kind === "change-old") {
          out.push(bl.text);
        }
      }
    }
  }
  return out.join("\n");
}

function refreshHunksPreservingDecisions(
  baseContent: string,
  currentContent: string,
  prevHunks: DiffHunk[],
  mergedBlockId?: string,
): DiffHunk[] {
  const prevByBlock = new Map<string, boolean | null>();
  for (const h of prevHunks) {
    if (h.kind !== "equal") {
      prevByBlock.set(h.blockId, h.accepted);
    }
  }
  return diffTextToHunks(baseContent, currentContent).map((h) => {
    if (h.kind === "equal") return h;
    if (mergedBlockId && h.blockId === mergedBlockId) return { ...h, accepted: true };
    const prev = prevByBlock.get(h.blockId);
    return prev !== undefined ? { ...h, accepted: prev } : h;
  });
}

/** 根据 base + hunk 采纳状态重建工作正文（null 视为采纳新版本） */
export function applyContentFromHunks(
  baseContent: string,
  currentContent: string,
  hunks: DiffHunk[],
): string {
  const diffLines = diffTextLines(baseContent, currentContent);
  const decisions = new Map<string, boolean | null>();
  for (const h of hunks) {
    if (h.kind !== "equal") {
      decisions.set(h.blockId, h.accepted);
    }
  }

  const out: string[] = [];
  let i = 0;
  while (i < diffLines.length) {
    const line = diffLines[i];
    if (line.kind === "equal") {
      out.push(line.text);
      i += 1;
      continue;
    }

    const blockId = line.blockId ?? `b${i}`;
    const accepted = decisions.get(blockId) ?? null;
    const useNew = accepted !== false;

    const blockLines: DiffDisplayLine[] = [];
    while (i < diffLines.length && diffLines[i].kind !== "equal" && diffLines[i].blockId === blockId) {
      blockLines.push(diffLines[i]);
      i += 1;
    }

    if (useNew) {
      for (const bl of blockLines) {
        if (bl.kind === "add" || bl.kind === "change-new") {
          out.push(bl.text);
        }
      }
    } else {
      for (const bl of blockLines) {
        if (bl.kind === "del" || bl.kind === "change-old") {
          out.push(bl.text);
        }
      }
    }
  }
  return out.join("\n");
}

export function applyHunkDecision(
  state: ChapterDiffState,
  blockId: string,
  accepted: boolean,
): { state: ChapterDiffState; content: string } {
  const hunks = setBlockDecision(state.hunks, blockId, accepted);
  const content = applyContentFromHunks(state.baseContent, state.currentContent, hunks);
  const newBase = accepted
    ? mergeAcceptedBlockIntoBase(state.baseContent, state.currentContent, blockId)
    : state.baseContent;
  const newHunks = refreshHunksPreservingDecisions(newBase, content, hunks, accepted ? blockId : undefined);
  return {
    state: { ...state, baseContent: newBase, hunks: newHunks, currentContent: content },
    content,
  };
}

export function applyAllHunkDecision(
  state: ChapterDiffState,
  accept: boolean,
): { state: ChapterDiffState; content: string } {
  const hunks = accept ? acceptAllHunks(state.hunks) : rejectAllHunks(state.hunks);
  const content = applyContentFromHunks(state.baseContent, state.currentContent, hunks);
  const newBase = accept ? content : state.baseContent;
  const newHunks = diffTextToHunks(newBase, content).map((h) =>
    h.kind === "equal" ? h : { ...h, accepted: accept },
  );
  return {
    state: { ...state, baseContent: newBase, hunks: newHunks, currentContent: content },
    content,
  };
}
