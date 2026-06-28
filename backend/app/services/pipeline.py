from __future__ import annotations

import json
import re
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import ROOT
from app.models import Book, Chapter, ChapterPlan, ChapterVersion, Character, GenerationJob, LintIssue, User, Worldview
from app.services.chapter_content import get_content, has_content, set_content
from app.services.deepseek import DeepSeekError, chat_completion
from app.services.prompt import build_ai_lint_messages
from app.services.system_writing_rules import CHASE_COMEDY_AUTHOR_PREFS, get_combined_for_lint
from app.services.prompt_assembler import assemble_context, build_generate_messages
from app.services.rule_engine import auto_fix_content, lint_chapter, lint_report_from_issues, word_count

SOURCE_BOOK = ROOT.parent / "我的AI成精了"

CHAPTER_EVENTS = {
    1: ("AI要跟我私奔", "逃", "闵行群租", "USB开场；94.7%；决定逃亡", "顾念赛博私奔；独狗", False),
    2: ("社区过关与拼贴梦", "逃", "社区", "首次核查过关；GPU藏匿", "梦中闪回", False),
    3: ("丰巢空柜与八平米", "逃", "群租", "搬群租；丰巢失败", "弱电井", False),
}


def ensure_demo_user(db: Session, email: str, password: str, display_name: str) -> User:
    user = db.query(User).filter(User.email == email).first()
    if user:
        return user
    from app.auth import hash_password

    user = User(email=email, password_hash=hash_password(password), display_name=display_name)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_book_from_template(db: Session, user_id: int, title: str, blurb: str, template_id: str, **kwargs) -> Book:
    genre = kwargs.get("genre", "")
    premise = kwargs.get("premise", blurb)
    target = kwargs.get("target_chapters", 300)
    is_blank = template_id in ("blank", "from-scratch", "custom", "import")

    book = Book(
        user_id=user_id,
        title=title,
        blurb=blurb,
        template_id=template_id,
        genre=genre,
        premise=premise,
        target_chapters=target,
        setup_step=1 if template_id == "blank" else 5,
    )
    db.add(book)
    db.flush()

    if is_blank:
        _seed_blank_book(db, book)

    db.commit()
    db.refresh(book)
    return book


def _seed_blank_book(db: Session, book: Book, chapters: int | None = None) -> None:
    from app.services.setup_agent import resolve_effective_target_chapters

    n = chapters or resolve_effective_target_chapters(book)
    for i in range(1, n + 1):
        db.add(
            ChapterPlan(
                book_id=book.id,
                chapter_no=i,
                title=f"第{i}章",
                plot_points="",
                scene="",
            )
        )
        db.add(Chapter(book_id=book.id, chapter_no=i, title=f"第{i}章", status="planned"))
    db.add(Worldview(book_id=book.id))


def ensure_book_chapter_slots(db: Session, book: Book, *, commit: bool = True) -> int:
    """补齐 Chapter / ChapterPlan 行直至规划总章数。"""
    from app.services.setup_agent import resolve_effective_target_chapters

    target = resolve_effective_target_chapters(book)
    chapter_nos = {c.chapter_no for c in db.query(Chapter).filter(Chapter.book_id == book.id).all()}
    plan_nos = {p.chapter_no for p in db.query(ChapterPlan).filter(ChapterPlan.book_id == book.id).all()}
    added = False
    for no in range(1, target + 1):
        if no not in plan_nos:
            db.add(
                ChapterPlan(
                    book_id=book.id,
                    chapter_no=no,
                    title=f"第{no}章",
                    plot_points="",
                    scene="",
                )
            )
            added = True
        if no not in chapter_nos:
            db.add(Chapter(book_id=book.id, chapter_no=no, title=f"第{no}章", status="planned"))
            added = True
    if added and commit:
        db.commit()
    elif added:
        db.flush()
    return target


def count_outline_planned(db: Session, book_id: int) -> int:
    return (
        db.query(ChapterPlan)
        .filter(ChapterPlan.book_id == book_id, ChapterPlan.plot_points != "")
        .count()
    )


def _seed_chase_comedy(db: Session, book: Book) -> None:
    book.writing_rules = CHASE_COMEDY_AUTHOR_PREFS
    chars = [
        ("陆沉舟", "protagonist", "25岁智源FDE，嘴贱布局者，第一人称「我」", "口语碎语、自嘲、对外克制"),
        ("顾念", "ai", "私人AI，共犯，一本正经误用梗", "梗外放，禁止解释梗"),
        ("苏令仪", "police", "网安警花，隔章章末POV", "冷静专业"),
    ]
    for name, role, summary, voice in chars:
        db.add(Character(book_id=book.id, name=name, role=role, summary=summary, voice_notes=voice))

    events_path = SOURCE_BOOK / "写作规约.md"
    outline_events = {}
    if events_path.exists():
        text = events_path.read_text(encoding="utf-8")
        for m in re.finditer(r"\|\s*(\d{3})\s*\|\s*([^|]+)\|", text):
            outline_events[int(m.group(1))] = m.group(2).strip()

    for no in range(1, 31):
        title = outline_events.get(no, f"第{no}章")
        if no in CHAPTER_EVENTS:
            t, mode, scene, plot, comedy, pov = CHAPTER_EVENTS[no]
            title = t
        else:
            mode, scene, plot, comedy, pov = "逃", "待填", title, "", False
        db.add(
            ChapterPlan(
                book_id=book.id,
                chapter_no=no,
                title=title,
                mode=mode,
                scene=scene,
                plot_points=plot if no in CHAPTER_EVENTS else title,
                comedy_core=comedy,
                pov_switch=pov,
            )
        )
        ch = Chapter(book_id=book.id, chapter_no=no, title=title, status="planned")
        body_dir = SOURCE_BOOK / "正文"
        md = body_dir / f"第{no:03d}章 {title}.md"
        if not md.exists():
            matches = list(body_dir.glob(f"第{no:03d}章*.md"))
            md = matches[0] if matches else None
        if md and md.exists():
            content = md.read_text(encoding="utf-8")
            set_content(ch, content)
            ch.word_count = word_count(content)
            ch.status = "draft"
        db.add(ch)


def get_prev_summary(db: Session, book_id: int, chapter_no: int) -> str:
    if chapter_no <= 1:
        return ""
    prev = (
        db.query(Chapter)
        .filter(Chapter.book_id == book_id, Chapter.chapter_no == chapter_no - 1)
        .first()
    )
    if not prev:
        return ""
    prev_content = get_content(prev)
    if not prev_content:
        return ""
    return prev_content.strip()[-400:]


def get_style_reference(db: Session, book_id: int) -> str:
    ch = db.query(Chapter).filter(Chapter.book_id == book_id, Chapter.chapter_no == 1).first()
    content = get_content(ch) if ch else ""
    if content:
        return content[:1200]
    return ""


def save_lint_issues(db: Session, chapter: Chapter, issues: list) -> None:
    db.query(LintIssue).filter(LintIssue.chapter_id == chapter.id).delete()
    for item in issues:
        db.add(
            LintIssue(
                chapter_id=chapter.id,
                rule_id=item.rule_id if hasattr(item, "rule_id") else item["rule_id"],
                severity=item.severity if hasattr(item, "severity") else item["severity"],
                line_no=item.line_no if hasattr(item, "line_no") else item.get("line", 0),
                excerpt=item.excerpt if hasattr(item, "excerpt") else item.get("excerpt", ""),
                message=item.message if hasattr(item, "message") else item.get("message", ""),
                auto_fixable=item.auto_fixable if hasattr(item, "auto_fixable") else item.get("auto_fixable", False),
            )
        )


def run_lint(db: Session, chapter: Chapter) -> dict:
    content = get_content(chapter)
    issues = lint_chapter(content or "", chapter.chapter_no)
    save_lint_issues(db, chapter, issues)
    db.commit()
    return lint_report_from_issues(content or "", issues)


async def run_ai_lint_on_content(db: Session, book: Book, content: str) -> list[dict]:
    """对草稿正文做 AI 规约检查，不写库。返回 issue dict 列表。"""
    if not (content or "").strip():
        return []
    user = db.query(User).filter(User.id == book.user_id).first()
    from app.services.api_key import resolve_api_key
    from app.services.rule_engine import resolve_issue_line

    try:
        messages = build_ai_lint_messages(content, get_combined_for_lint(book))
        raw = await chat_completion(
            messages, api_key=resolve_api_key(user), temperature=0.2, max_tokens=1024, stream=False
        )
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        data = json.loads(raw)
        from app.services.ai_lint_filter import filter_ai_lint_items

        out: list[dict] = []
        for item in filter_ai_lint_items(data.get("issues", [])):
            excerpt = str(item.get("excerpt") or "")[:200]
            line = resolve_issue_line(content, int(item.get("line") or 0), excerpt)
            out.append(
                {
                    "rule_id": str(item.get("type") or "ai_lint"),
                    "severity": str(item.get("severity") or "warn"),
                    "line_no": line,
                    "excerpt": excerpt,
                    "message": str(item.get("message") or ""),
                    "auto_fixable": False,
                    "blocking": str(item.get("severity") or "warn") == "error",
                }
            )
        if not data.get("lu_chenzhou_decision", True):
            out.append(
                {
                    "rule_id": "lu_decision",
                    "severity": "warn",
                    "line_no": 0,
                    "excerpt": "",
                    "message": "未检测到陆沉舟明确拍板决定",
                    "auto_fixable": False,
                    "blocking": False,
                }
            )
        return out
    except (DeepSeekError, json.JSONDecodeError, Exception):
        return []


async def run_ai_lint(db: Session, book: Book, chapter: Chapter) -> None:
    content = get_content(chapter)
    if not content:
        return
    user = db.query(User).filter(User.id == book.user_id).first()
    from app.services.api_key import resolve_api_key

    try:
        messages = build_ai_lint_messages(content, get_combined_for_lint(book))
        raw = await chat_completion(
            messages, api_key=resolve_api_key(user), temperature=0.2, max_tokens=1024, stream=False
        )
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        data = json.loads(raw)
        from app.services.ai_lint_filter import filter_ai_lint_items
        from app.services.rule_engine import resolve_issue_line

        for item in filter_ai_lint_items(data.get("issues", [])):
            excerpt = str(item.get("excerpt") or "")[:200]
            line = resolve_issue_line(content, int(item.get("line") or 0), excerpt)
            db.add(
                LintIssue(
                    chapter_id=chapter.id,
                    rule_id=item.get("type", "ai_lint"),
                    severity=item.get("severity", "warn"),
                    line_no=line,
                    excerpt=excerpt,
                    message=item.get("message", ""),
                    auto_fixable=False,
                )
            )
        if not data.get("lu_chenzhou_decision", True):
            db.add(
                LintIssue(
                    chapter_id=chapter.id,
                    rule_id="lu_decision",
                    severity="warn",
                    message="未检测到陆沉舟明确拍板决定",
                )
            )
        db.commit()
    except (DeepSeekError, json.JSONDecodeError, Exception):
        pass


async def execute_generation_job(db: Session, job_id: int) -> None:
    job = db.query(GenerationJob).filter(GenerationJob.id == job_id).first()
    if not job:
        return
    job.status = "running"
    db.commit()

    book = db.query(Book).filter(Book.id == job.book_id).first()
    chapter = (
        db.query(Chapter)
        .filter(Chapter.book_id == job.book_id, Chapter.chapter_no == job.chapter_no)
        .first()
    )
    plan = (
        db.query(ChapterPlan)
        .filter(ChapterPlan.book_id == job.book_id, ChapterPlan.chapter_no == job.chapter_no)
        .first()
    )
    if not book or not chapter:
        job.status = "failed"
        job.error = "章节不存在"
        db.commit()
        return

    chars = db.query(Character).filter(Character.book_id == book.id).all()
    ctx = assemble_context(db, book, job.chapter_no)
    messages = build_generate_messages(
        ctx,
        instruction=job.instruction or "",
        job_type=job.job_type,
        current_content=get_content(chapter) or "",
    )

    try:
        user = db.query(User).filter(User.id == book.user_id).first()
        from app.services.api_key import resolve_api_key

        api_key = resolve_api_key(user)
        content = await chat_completion(
            messages, api_key=api_key or None, temperature=0.85, max_tokens=4096, stream=False
        )
        content = str(content).strip()
        if job.job_type == "fix":
            content = auto_fix_content(content)
        set_content(chapter, content)
        chapter.word_count = word_count(content)
        chapter.status = "review"
        chapter.updated_at = datetime.utcnow()
        if plan and plan.title:
            chapter.title = plan.title
        db.add(ChapterVersion(chapter_id=chapter.id, content=content, source=f"ai_{job.job_type}"))
        run_lint(db, chapter)
        await run_ai_lint(db, book, chapter)
        job.result_content = content
        job.status = "done"
        job.finished_at = datetime.utcnow()
        db.commit()
    except DeepSeekError as e:
        job.status = "failed"
        job.error = str(e)
        job.finished_at = datetime.utcnow()
        db.commit()
    except Exception as e:
        job.status = "failed"
        job.error = f"生成失败: {e}"
        job.finished_at = datetime.utcnow()
        db.commit()


def export_book_txt(db: Session, book_id: int) -> str:
    book = db.query(Book).filter(Book.id == book_id).first()
    chapters = (
        db.query(Chapter).filter(Chapter.book_id == book_id).order_by(Chapter.chapter_no).all()
    )
    parts = [book.title, "", book.blurb, "", f"共 {len(chapters)} 章", "", "=" * 40, ""]
    for ch in chapters:
        content = get_content(ch)
        if not content:
            continue
        parts.append(content.strip())
        parts.extend(["", "=" * 40, ""])
    return "\n".join(parts)
