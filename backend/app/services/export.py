from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Book, Chapter
from app.services.chapter_content import get_content, has_content


def strip_md(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text.rstrip()


def render_chapter(content: str) -> str:
    lines: list[str] = []
    for raw in content.splitlines():
        line = strip_md(raw)
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if line.startswith("# "):
            lines.append("")
            lines.append(line[2:].strip())
            lines.append("")
        elif line.startswith("---"):
            lines.append("")
        else:
            lines.append(line)
    return "\n".join(lines).strip()


def export_book_txt(db: Session, book: Book) -> str:
    chapters = (
        db.query(Chapter)
        .filter(Chapter.book_id == book.id)
        .order_by(Chapter.chapter_no)
        .all()
    )
    written = [c for c in chapters if has_content(c)]
    toc = []
    for ch in written:
        title = ch.title or f"第{ch.chapter_no}章"
        toc.append(f"第{ch.chapter_no:03d}章 {title}")

    parts = [
        book.title,
        "",
        book.blurb,
        "",
        f"共 {len(written)} 章",
        "",
        "目录",
        "\n".join(toc),
        "",
        "=" * 40,
        "",
    ]
    for i, ch in enumerate(written):
        parts.append(render_chapter(get_content(ch)))
        if i < len(written) - 1:
            parts.extend(["", "=" * 40, ""])
    return "\n".join(parts) + "\n"
