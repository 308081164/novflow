from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Book, Chapter, ChapterPlan, ChapterVersion, GenerationJob, LintIssue
from app.services import deepseek, prompt_assembler, rule_engine
from app.services.agent_intent import finalize_chapter_edit_content
from app.services.chapter_content import set_content


def count_words(content: str) -> int:
    _, body = rule_engine.extract_body(content)
    return rule_engine.count_chars(body)


def save_version(db: Session, chapter: Chapter, note: str = "") -> None:
    version_no = len(chapter.versions) + 1
    db.add(
        ChapterVersion(
            chapter_id=chapter.id,
            version_no=version_no,
            content=chapter.content,
            note=note,
        )
    )


def apply_content(db: Session, chapter: Chapter, content: str, note: str = "") -> Chapter:
    if chapter.content.strip():
        save_version(db, chapter, note=note or "自动保存")
    sanitized = finalize_chapter_edit_content(
        content,
        chapter_no=chapter.chapter_no,
        original_content=chapter.content or "",
        edit_scope="chapter",
    )
    body = sanitized or content
    set_content(chapter, body)
    chapter.word_count = count_words(body)
    chapter.status = "written" if chapter.word_count > 100 else "draft"
    chapter.updated_at = datetime.utcnow()
    title, _ = rule_engine.extract_body(body)
    if title:
        chapter.title = title.replace(f"第{chapter.chapter_no:03d}章", "").strip()
        if chapter.title.startswith("章"):
            chapter.title = chapter.title[1:].strip()
    return chapter


def sync_lint_issues(db: Session, chapter: Chapter) -> list[LintIssue]:
    db.query(LintIssue).filter(LintIssue.chapter_id == chapter.id).delete()
    hits = rule_engine.lint_chapter(chapter.content, chapter.chapter_no)
    issues = []
    for h in hits:
        issue = LintIssue(
            chapter_id=chapter.id,
            rule_id=h.rule_id,
            severity=h.severity,
            message=h.message,
            line_no=h.line_no,
            snippet=h.snippet,
        )
        db.add(issue)
        issues.append(issue)
    db.commit()
    return issues


async def run_generation_job(db: Session, job_id: int) -> None:
    job = db.query(GenerationJob).filter(GenerationJob.id == job_id).first()
    if not job:
        return

    book = db.query(Book).filter(Book.id == job.book_id).first()
    chapter = (
        db.query(Chapter)
        .filter(Chapter.book_id == job.book_id, Chapter.chapter_no == job.chapter_no)
        .first()
    )
    if not book or not chapter:
        job.status = "failed"
        job.error = "书籍或章节不存在"
        db.commit()
        return

    job.status = "running"
    job.stream_buffer = ""
    db.commit()

    ctx = prompt_assembler.assemble_context(db, book, job.chapter_no)

    def on_chunk(text: str) -> None:
        job.stream_buffer += text
        db.commit()

    try:
        if job.job_type == "generate":
            messages = prompt_assembler.build_generate_messages(ctx)
            result = await deepseek.chat_completion_stream(messages, on_chunk=on_chunk)
        elif job.job_type == "expand":
            extra = job.result or "{}"
            import json

            params = json.loads(extra) if extra.startswith("{") else {}
            messages = prompt_assembler.build_expand_messages(
                ctx,
                chapter.content,
                params.get("target_words", 500),
                params.get("focus", ""),
            )
            result = await deepseek.chat_completion_stream(messages, on_chunk=on_chunk)
        elif job.job_type == "fix":
            issues = db.query(LintIssue).filter(LintIssue.chapter_id == chapter.id).all()
            issues_text = "\n".join(f"- [{i.severity}] {i.message}" for i in issues)
            messages = prompt_assembler.build_fix_messages(ctx, chapter.content, issues_text)
            result = await deepseek.chat_completion_stream(messages, on_chunk=on_chunk)
        else:
            raise deepseek.DeepSeekError(f"未知任务类型: {job.job_type}")

        apply_content(db, chapter, result, note=job.job_type)
        sync_lint_issues(db, chapter)
        plan = (
            db.query(ChapterPlan)
            .filter(ChapterPlan.book_id == book.id, ChapterPlan.chapter_no == job.chapter_no)
            .first()
        )
        if plan:
            plan.status = "written"
        job.status = "completed"
        job.result = result
        job.completed_at = datetime.utcnow()
        db.commit()
    except deepseek.DeepSeekError as e:
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.utcnow()
        db.commit()
    except Exception as e:
        job.status = "failed"
        job.error = f"生成失败: {e}"
        job.completed_at = datetime.utcnow()
        db.commit()


def fix_commas_local(db: Session, chapter: Chapter) -> Chapter:
    save_version(db, chapter, note="fix-commas")
    chapter.content = rule_engine.fix_commas(chapter.content)
    chapter.word_count = count_words(chapter.content)
    sync_lint_issues(db, chapter)
    db.commit()
    return chapter


def approve_chapter(db: Session, chapter: Chapter) -> Chapter:
    hits = rule_engine.lint_chapter(chapter.content, chapter.chapter_no)
    errors = [h for h in hits if h.severity == "error"]
    if errors:
        raise ValueError("存在 error 级 lint 问题，请先修复")
    chapter.approved = True
    chapter.status = "approved"
    plan = (
        db.query(ChapterPlan)
        .filter(ChapterPlan.book_id == chapter.book_id, ChapterPlan.chapter_no == chapter.chapter_no)
        .first()
    )
    if plan:
        plan.status = "approved"
    db.commit()
    return chapter
