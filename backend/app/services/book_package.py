"""整本书籍包导出/导入 — 用于跨设备、跨账号迁移。"""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    Book,
    Chapter,
    ChapterIllustration,
    ChapterPlan,
    ChapterVersion,
    Character,
    LintIssue,
    SetupMessage,
    Worldview,
    WriteAgentMessage,
)
from app.services.chapter_content import get_content, set_content
from app.services.character_cards import ingest_character_cards
from app.services.image_gen import media_url, refresh_image_records
from app.services.pipeline import ensure_book_chapter_slots, word_count
from app.services.storage import storage

PACKAGE_VERSION = 1
PACKAGE_APP = "novflow"
MANIFEST_NAME = "manifest.json"

BOOK_FIELDS = (
    "title",
    "blurb",
    "platform",
    "template_id",
    "target_chapters",
    "words_per_chapter",
    "rule_summary",
    "genre",
    "premise",
    "setup_step",
    "writing_rules",
    "plot_framework",
    "corpus",
    "write_agent_session_id",
    "cover_image_key",
    "created_at",
)

WORLDVIEW_FIELDS = ("era", "setting", "tone", "timeline_text", "taboos", "content")
CHARACTER_FIELDS = ("name", "role", "summary", "voice_notes", "content", "arc_json", "images_json")
PLAN_FIELDS = (
    "chapter_no",
    "title",
    "mode",
    "scene",
    "plot_points",
    "comedy_core",
    "pov_switch",
    "character_names",
    "meta_json",
)
CHAPTER_FIELDS = ("chapter_no", "title", "status", "word_count", "updated_at")
SETUP_MSG_FIELDS = ("role", "content", "cards_json", "actions_json", "meta_json", "created_at")
WRITE_MSG_FIELDS = ("session_id", "role", "content", "cards_json", "actions_json", "meta_json", "created_at")


def _dt(value: datetime | None) -> str | None:
    if not value:
        return None
    return value.isoformat()


def _from_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _plan_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(str(x).strip() for x in value if str(x).strip())
    return str(value).strip()


def _chapter_plan_from_row(book_id: int, row: dict[str, Any]) -> ChapterPlan | None:
    """将书籍包中的章节规划行映射为 ChapterPlan（兼容 synopsis/comedy_hook 别名）。"""
    try:
        no = int(row.get("chapter_no") or 0)
    except (TypeError, ValueError):
        return None
    if no < 1:
        return None
    meta = row.get("meta_json") if isinstance(row.get("meta_json"), dict) else {}
    meta = dict(meta)
    for key in ("cast", "events", "entrances", "exits"):
        if key not in meta and row.get(key) is not None:
            meta[key] = row[key]
    cast = meta.get("cast") or []
    character_names = _plan_text(row.get("character_names"))
    if not character_names and isinstance(cast, list):
        character_names = "、".join(str(x) for x in cast if str(x).strip())
    return ChapterPlan(
        book_id=book_id,
        chapter_no=no,
        title=_plan_text(row.get("title")) or f"第{no}章",
        mode=_plan_text(row.get("mode")) or "逃",
        scene=_plan_text(row.get("scene")),
        plot_points=_plan_text(row.get("plot_points") or row.get("synopsis")),
        comedy_core=_plan_text(row.get("comedy_core") or row.get("comedy_hook")),
        pov_switch=bool(row.get("pov_switch")),
        character_names=character_names,
        meta_json=meta,
    )


def _safe_filename(title: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (title or "book").strip())[:80]
    return name or "book"


def _remap_object_key(key: str, old_book_id: int, new_book_id: int) -> str:
    if not key:
        return ""
    if not old_book_id or old_book_id == new_book_id:
        return key
    # Media API URLs: /api/v1/media/images/{book_id}/...
    marker = f"/images/{old_book_id}/"
    if marker in key:
        return key.replace(marker, f"/images/{new_book_id}/")
    if key.startswith(f"images/{old_book_id}/"):
        return f"images/{new_book_id}/" + key[len(f"images/{old_book_id}/") :]
    if key.startswith(f"{old_book_id}/"):
        return f"{new_book_id}/" + key[len(f"{old_book_id}/") :]
    return key.replace(f"/{old_book_id}/", f"/{new_book_id}/")


def _collect_media_keys(db: Session, book: Book) -> set[str]:
    keys: set[str] = set()
    if book.cover_image_key:
        keys.add(book.cover_image_key)
    for char in db.query(Character).filter(Character.book_id == book.id).all():
        for img in char.images_json or []:
            if isinstance(img, dict):
                k = str(img.get("object_key") or "").strip()
                if k:
                    keys.add(k)
        arc = char.arc_json if isinstance(char.arc_json, dict) else {}
        k = str(arc.get("active_portrait_object_key") or "").strip()
        if k:
            keys.add(k)
    chapters = db.query(Chapter).filter(Chapter.book_id == book.id).all()
    chapter_ids = [c.id for c in chapters]
    if storage.enabled:
        for ch in chapters:
            keys.add(storage.object_key(book.id, ch.chapter_no))
    if chapter_ids:
        for ill in db.query(ChapterIllustration).filter(ChapterIllustration.chapter_id.in_(chapter_ids)).all():
            if ill.object_key:
                keys.add(ill.object_key)
    return keys


def _load_book_graph(db: Session, book: Book) -> dict[str, Any]:
    chapters = db.query(Chapter).filter(Chapter.book_id == book.id).order_by(Chapter.chapter_no).all()
    chapter_by_no = {c.chapter_no: c for c in chapters}
    chapter_ids = [c.id for c in chapters]

    versions: list[dict] = []
    lint_issues: list[dict] = []
    illustrations: list[dict] = []
    if chapter_ids:
        id_to_no = {c.id: c.chapter_no for c in chapters}
        for v in (
            db.query(ChapterVersion)
            .filter(ChapterVersion.chapter_id.in_(chapter_ids))
            .order_by(ChapterVersion.id)
            .all()
        ):
            versions.append(
                {
                    "chapter_no": id_to_no.get(v.chapter_id),
                    "content": v.content,
                    "source": v.source,
                    "created_at": _dt(v.created_at),
                }
            )
        for li in db.query(LintIssue).filter(LintIssue.chapter_id.in_(chapter_ids)).all():
            lint_issues.append(
                {
                    "chapter_no": id_to_no.get(li.chapter_id),
                    "rule_id": li.rule_id,
                    "severity": li.severity,
                    "line_no": li.line_no,
                    "excerpt": li.excerpt,
                    "message": li.message,
                    "auto_fixable": li.auto_fixable,
                    "fixed": li.fixed,
                }
            )
        ill_rows = (
            db.query(ChapterIllustration)
            .filter(ChapterIllustration.chapter_id.in_(chapter_ids))
            .order_by(ChapterIllustration.id)
            .all()
        )
        id_to_export: dict[int, int] = {}
        for idx, ill in enumerate(ill_rows, start=1):
            id_to_export[ill.id] = idx
            illustrations.append(
                {
                    "export_id": idx,
                    "parent_export_id": id_to_export.get(ill.parent_id) if ill.parent_id else None,
                    "chapter_no": id_to_no.get(ill.chapter_id),
                    "object_key": ill.object_key,
                    "prompt": ill.prompt,
                    "created_at": _dt(ill.created_at),
                }
            )

    wv = db.query(Worldview).filter(Worldview.book_id == book.id).first()
    chars = db.query(Character).filter(Character.book_id == book.id).order_by(Character.id).all()
    plans = db.query(ChapterPlan).filter(ChapterPlan.book_id == book.id).order_by(ChapterPlan.chapter_no).all()
    setup_msgs = (
        db.query(SetupMessage).filter(SetupMessage.book_id == book.id).order_by(SetupMessage.id).all()
    )
    write_msgs = (
        db.query(WriteAgentMessage)
        .filter(WriteAgentMessage.book_id == book.id)
        .order_by(WriteAgentMessage.id)
        .all()
    )

    chapter_payload = []
    for ch in chapters:
        content = get_content(ch)
        chapter_payload.append(
            {
                **{f: getattr(ch, f) if f != "updated_at" else _dt(ch.updated_at) for f in CHAPTER_FIELDS},
                "has_content": bool(content.strip()),
            }
        )

    return {
        "manifest": {
            "format": PACKAGE_APP,
            "version": PACKAGE_VERSION,
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "source_book_id": book.id,
            "title": book.title,
        },
        "book": {f: getattr(book, f) if f != "created_at" else _dt(book.created_at) for f in BOOK_FIELDS},
        "worldview": ({f: getattr(wv, f) for f in WORLDVIEW_FIELDS} if wv else None),
        "characters": [
            {"id": c.id, **{f: getattr(c, f) for f in CHARACTER_FIELDS}} for c in chars
        ],
        "chapter_plans": [{f: getattr(p, f) for f in PLAN_FIELDS} for p in plans],
        "chapters": chapter_payload,
        "chapter_versions": versions,
        "lint_issues": lint_issues,
        "chapter_illustrations": illustrations,
        "setup_messages": [
            {f: getattr(m, f) if f != "created_at" else _dt(m.created_at) for f in SETUP_MSG_FIELDS}
            for m in setup_msgs
        ],
        "write_agent_messages": [
            {f: getattr(m, f) if f != "created_at" else _dt(m.created_at) for f in WRITE_MSG_FIELDS}
            for m in write_msgs
        ],
        "chapter_by_no": chapter_by_no,
        "media_keys": _collect_media_keys(db, book),
    }


def export_book_package(db: Session, book: Book) -> tuple[bytes, str]:
    """导出 .novflow.zip，返回 (bytes, 建议文件名)。"""
    graph = _load_book_graph(db, book)
    chapter_by_no: dict[int, Chapter] = graph.pop("chapter_by_no")
    media_keys: set[str] = graph.pop("media_keys")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(graph["manifest"], ensure_ascii=False, indent=2))
        zf.writestr("book.json", json.dumps(graph["book"], ensure_ascii=False, indent=2))
        if graph["worldview"]:
            zf.writestr("worldview.json", json.dumps(graph["worldview"], ensure_ascii=False, indent=2))
        zf.writestr("characters.json", json.dumps(graph["characters"], ensure_ascii=False, indent=2))
        zf.writestr("chapter_plans.json", json.dumps(graph["chapter_plans"], ensure_ascii=False, indent=2))
        zf.writestr("chapters.json", json.dumps(graph["chapters"], ensure_ascii=False, indent=2))
        zf.writestr("chapter_versions.json", json.dumps(graph["chapter_versions"], ensure_ascii=False, indent=2))
        zf.writestr("lint_issues.json", json.dumps(graph["lint_issues"], ensure_ascii=False, indent=2))
        zf.writestr(
            "chapter_illustrations.json",
            json.dumps(graph["chapter_illustrations"], ensure_ascii=False, indent=2),
        )
        zf.writestr("setup_messages.json", json.dumps(graph["setup_messages"], ensure_ascii=False, indent=2))
        zf.writestr(
            "write_agent_messages.json",
            json.dumps(graph["write_agent_messages"], ensure_ascii=False, indent=2),
        )

        for ch in chapter_by_no.values():
            content = get_content(ch)
            if content.strip():
                zf.writestr(f"chapters/{ch.chapter_no:04d}.md", content.encode("utf-8"))

        for key in sorted(media_keys):
            data = storage.get_bytes(key)
            if data:
                zf.writestr(f"media/{key}", data)

    filename = f"{_safe_filename(book.title)}.novflow.zip"
    return buf.getvalue(), filename


def _read_zip_json(zf: zipfile.ZipFile, name: str, default: Any) -> Any:
    try:
        raw = zf.read(name)
    except KeyError:
        return default
    return json.loads(raw.decode("utf-8"))


def _rewrite_json_keys(obj: Any, old_book_id: int, new_book_id: int) -> Any:
    if isinstance(obj, str):
        if not old_book_id or old_book_id == new_book_id:
            return obj
        if (
            obj.startswith("images/")
            or obj.startswith(f"{old_book_id}/")
            or f"/images/{old_book_id}/" in obj
        ):
            return _remap_object_key(obj, old_book_id, new_book_id)
        return obj
    if isinstance(obj, list):
        return [_rewrite_json_keys(x, old_book_id, new_book_id) for x in obj]
    if isinstance(obj, dict):
        return {k: _rewrite_json_keys(v, old_book_id, new_book_id) for k, v in obj.items()}
    return obj


def _rewrite_character_ids(obj: Any, id_map: dict[int, int]) -> Any:
    """Remap character_id fields after import assigns new primary keys."""
    if not id_map:
        return obj
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k == "character_id" and v is not None:
                try:
                    old = int(v)
                    out[k] = id_map.get(old, old)
                    continue
                except (TypeError, ValueError):
                    pass
            out[k] = _rewrite_character_ids(v, id_map)
        return out
    if isinstance(obj, list):
        return [_rewrite_character_ids(x, id_map) for x in obj]
    return obj


def _normalize_character_images(images: Any) -> list:
    if not isinstance(images, list):
        return []
    return refresh_image_records(images)


def _character_cards_from_messages(setup_msgs: Any, write_msgs: Any) -> list[dict[str, Any]]:
    """Collect character cards embedded in chat history (fallback when characters.json is thin)."""
    cards: list[dict[str, Any]] = []
    for msgs in (setup_msgs, write_msgs):
        if not isinstance(msgs, list):
            continue
        for row in msgs:
            if not isinstance(row, dict):
                continue
            for card in row.get("cards_json") or []:
                if isinstance(card, dict) and card.get("type") == "character":
                    cards.append(card)
    return cards


def import_book_package(db: Session, user_id: int, raw: bytes) -> tuple[Book, dict[str, int]]:
    """从 .novflow.zip 导入整本书，返回新书与统计。"""
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        manifest = _read_zip_json(zf, MANIFEST_NAME, {})
        if manifest.get("format") != PACKAGE_APP:
            raise ValueError("不是有效的 NovFlow 书籍包（缺少 manifest）")
        if int(manifest.get("version") or 0) > PACKAGE_VERSION:
            raise ValueError("书籍包版本过新，请升级 NovFlow 后重试")

        book_data = _read_zip_json(zf, "book.json", None)
        if not book_data or not str(book_data.get("title") or "").strip():
            raise ValueError("书籍包缺少 book.json 或书名")

        old_book_id = int(manifest.get("source_book_id") or 0)
        wv_data = _read_zip_json(zf, "worldview.json", None)
        characters = _read_zip_json(zf, "characters.json", [])
        plans = _read_zip_json(zf, "chapter_plans.json", [])
        chapters_meta = _read_zip_json(zf, "chapters.json", [])
        versions = _read_zip_json(zf, "chapter_versions.json", [])
        lint_issues = _read_zip_json(zf, "lint_issues.json", [])
        illustrations = _read_zip_json(zf, "chapter_illustrations.json", [])
        setup_msgs = _read_zip_json(zf, "setup_messages.json", [])
        write_msgs = _read_zip_json(zf, "write_agent_messages.json", [])

        book = Book(user_id=user_id)
        for field in BOOK_FIELDS:
            if field == "created_at":
                book.created_at = _from_dt(book_data.get("created_at")) or datetime.utcnow()
            elif field == "cover_image_key":
                continue
            elif field == "plot_framework":
                book.plot_framework = book_data.get("plot_framework") or {}
            else:
                val = book_data.get(field)
                if val is not None:
                    setattr(book, field, val)
        db.add(book)
        db.flush()

        new_book_id = book.id
        if old_book_id:
            book_data = _rewrite_json_keys(book_data, old_book_id, new_book_id)
            if wv_data:
                wv_data = _rewrite_json_keys(wv_data, old_book_id, new_book_id)
            characters = _rewrite_json_keys(characters, old_book_id, new_book_id)
            illustrations = _rewrite_json_keys(illustrations, old_book_id, new_book_id)
            setup_msgs = _rewrite_json_keys(setup_msgs, old_book_id, new_book_id)
            write_msgs = _rewrite_json_keys(write_msgs, old_book_id, new_book_id)

        book.cover_image_key = str(book_data.get("cover_image_key") or "")

        if wv_data:
            wv = Worldview(book_id=book.id, **{f: wv_data.get(f, "") for f in WORLDVIEW_FIELDS})
            db.add(wv)

        char_id_map: dict[int, int] = {}
        for row in characters if isinstance(characters, list) else []:
            if not isinstance(row, dict):
                continue
            images = _normalize_character_images(row.get("images_json"))
            ch = Character(
                book_id=book.id,
                name=str(row.get("name") or "未命名"),
                role=str(row.get("role") or "support"),
                summary=str(row.get("summary") or ""),
                voice_notes=str(row.get("voice_notes") or ""),
                content=str(row.get("content") or ""),
                arc_json=row.get("arc_json") if isinstance(row.get("arc_json"), dict) else {},
                images_json=images,
            )
            db.add(ch)
            db.flush()
            old_cid = row.get("id")
            if old_cid is not None:
                try:
                    char_id_map[int(old_cid)] = ch.id
                except (TypeError, ValueError):
                    pass
            if images:
                for img in images:
                    img["character_id"] = ch.id
                    key = str(img.get("object_key") or "").strip()
                    if key:
                        img["url"] = media_url(key)
                ch.images_json = list(images)

        plans_imported = 0
        for row in plans if isinstance(plans, list) else []:
            if not isinstance(row, dict):
                continue
            plan = _chapter_plan_from_row(book.id, row)
            if not plan:
                continue
            db.add(plan)
            plans_imported += 1

        chapter_id_by_no: dict[int, int] = {}
        chapters_imported = 0
        for row in chapters_meta if isinstance(chapters_meta, list) else []:
            if not isinstance(row, dict):
                continue
            no = int(row.get("chapter_no") or 0)
            if no < 1:
                continue
            ch = Chapter(
                book_id=book.id,
                chapter_no=no,
                title=str(row.get("title") or f"第{no}章"),
                status=str(row.get("status") or "planned"),
                word_count=int(row.get("word_count") or 0),
                updated_at=_from_dt(row.get("updated_at")) or datetime.utcnow(),
            )
            md_name = f"chapters/{no:04d}.md"
            try:
                body = zf.read(md_name).decode("utf-8")
            except KeyError:
                body = ""
            if body.strip():
                set_content(ch, body)
                ch.word_count = word_count(body)
                chapters_imported += 1
            db.add(ch)
            db.flush()
            chapter_id_by_no[no] = ch.id

        ensure_book_chapter_slots(db, book, commit=False)

        for row in versions if isinstance(versions, list) else []:
            if not isinstance(row, dict):
                continue
            no = int(row.get("chapter_no") or 0)
            cid = chapter_id_by_no.get(no)
            if not cid or not row.get("content"):
                continue
            db.add(
                ChapterVersion(
                    chapter_id=cid,
                    content=str(row["content"]),
                    source=str(row.get("source") or "import"),
                    created_at=_from_dt(row.get("created_at")) or datetime.utcnow(),
                )
            )

        for row in lint_issues if isinstance(lint_issues, list) else []:
            if not isinstance(row, dict):
                continue
            no = int(row.get("chapter_no") or 0)
            cid = chapter_id_by_no.get(no)
            if not cid:
                continue
            db.add(
                LintIssue(
                    chapter_id=cid,
                    rule_id=str(row.get("rule_id") or ""),
                    severity=str(row.get("severity") or "error"),
                    line_no=int(row.get("line_no") or 0),
                    excerpt=str(row.get("excerpt") or ""),
                    message=str(row.get("message") or ""),
                    auto_fixable=bool(row.get("auto_fixable")),
                    fixed=bool(row.get("fixed")),
                )
            )

        ill_id_map: dict[int, int] = {}
        ill_pending: list[tuple[dict, ChapterIllustration]] = []
        for row in illustrations if isinstance(illustrations, list) else []:
            if not isinstance(row, dict):
                continue
            no = int(row.get("chapter_no") or 0)
            cid = chapter_id_by_no.get(no)
            if not cid:
                continue
            ill = ChapterIllustration(
                chapter_id=cid,
                object_key=str(row.get("object_key") or ""),
                prompt=str(row.get("prompt") or ""),
                created_at=_from_dt(row.get("created_at")) or datetime.utcnow(),
            )
            db.add(ill)
            db.flush()
            export_id = int(row.get("export_id") or 0)
            if export_id:
                ill_id_map[export_id] = ill.id
            parent_export = row.get("parent_export_id")
            if parent_export:
                ill_pending.append((row, ill))

        for row, ill in ill_pending:
            parent_export = int(row.get("parent_export_id") or 0)
            ill.parent_id = ill_id_map.get(parent_export)

        if char_id_map:
            setup_msgs = _rewrite_character_ids(setup_msgs, char_id_map)
            write_msgs = _rewrite_character_ids(write_msgs, char_id_map)

        for row in setup_msgs if isinstance(setup_msgs, list) else []:
            if not isinstance(row, dict):
                continue
            meta = row.get("meta_json") or {}
            if isinstance(meta, dict) and isinstance(meta.get("images"), list):
                meta = {**meta, "images": refresh_image_records(meta.get("images"))}
            db.add(
                SetupMessage(
                    book_id=book.id,
                    role=str(row.get("role") or "user"),
                    content=str(row.get("content") or ""),
                    cards_json=row.get("cards_json") or [],
                    actions_json=row.get("actions_json") or [],
                    meta_json=meta if isinstance(meta, dict) else {},
                    created_at=_from_dt(row.get("created_at")) or datetime.utcnow(),
                )
            )

        for row in write_msgs if isinstance(write_msgs, list) else []:
            if not isinstance(row, dict):
                continue
            meta = row.get("meta_json") or {}
            if isinstance(meta, dict) and isinstance(meta.get("images"), list):
                meta = {**meta, "images": refresh_image_records(meta.get("images"))}
            db.add(
                WriteAgentMessage(
                    book_id=book.id,
                    session_id=str(row.get("session_id") or book.write_agent_session_id or ""),
                    role=str(row.get("role") or "user"),
                    content=str(row.get("content") or ""),
                    cards_json=row.get("cards_json") or [],
                    actions_json=row.get("actions_json") or [],
                    meta_json=meta if isinstance(meta, dict) else {},
                    created_at=_from_dt(row.get("created_at")) or datetime.utcnow(),
                )
            )

        media_imported = 0
        for name in zf.namelist():
            if not name.startswith("media/"):
                continue
            key = name[len("media/") :]
            if old_book_id and new_book_id:
                key = _remap_object_key(key, old_book_id, new_book_id)
            data = zf.read(name)
            if not data:
                continue
            ct = "application/octet-stream"
            lower = key.lower()
            if lower.endswith(".png"):
                ct = "image/png"
            elif lower.endswith(".jpg") or lower.endswith(".jpeg"):
                ct = "image/jpeg"
            elif lower.endswith(".webp"):
                ct = "image/webp"
            elif lower.endswith(".gif"):
                ct = "image/gif"
            elif lower.endswith(".md"):
                ct = "text/markdown; charset=utf-8"
            storage.put_bytes(key, data, content_type=ct)
            media_imported += 1

        msg_char_cards = _character_cards_from_messages(setup_msgs, write_msgs)

    db.commit()
    db.refresh(book)

    # After commit: fill Character table from chat cards when characters.json was empty/partial.
    if msg_char_cards:
        ingest_character_cards(db, book, msg_char_cards, overwrite=False)
        db.refresh(book)

    char_count = db.query(Character).filter(Character.book_id == book.id).count()
    stats = {
        "characters": char_count,
        "chapter_plans": plans_imported,
        "chapters_with_content": chapters_imported,
        "setup_messages": len(setup_msgs) if isinstance(setup_msgs, list) else 0,
        "write_agent_messages": len(write_msgs) if isinstance(write_msgs, list) else 0,
        "media_files": media_imported,
        "illustrations": len(illustrations) if isinstance(illustrations, list) else 0,
    }
    return book, stats
