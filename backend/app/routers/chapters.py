from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.deps_license import require_desktop_license
from app.models import Book, Chapter, ChapterPlan, ChapterVersion, GenerationJob, LintIssue, User
from app.schemas import ChapterOut, ChapterPlanOut, ChapterPlanUpdate, ChapterSave, FixDraftIn, FixDraftOut, FixIssueIn, GenerateIn, JobOut, LintCheckIn, LintReport
from app.services.chapter_content import get_content, has_content, set_content
from app.services.pipeline import ensure_book_chapter_slots, execute_generation_job, run_ai_lint_on_content, run_lint
from app.services.rule_engine import auto_fix_content, auto_fix_issue, lint_chapter, lint_report_from_issues, word_count

router = APIRouter(prefix="/books/{book_id}", tags=["chapters"])


def _chapter_out(ch: Chapter) -> ChapterOut:
    content = get_content(ch)
    return ChapterOut(
        id=ch.id,
        chapter_no=ch.chapter_no,
        title=ch.title,
        content=content,
        word_count=ch.word_count or word_count(content),
        status=ch.status,
        approved=ch.status == "approved",
        updated_at=ch.updated_at,
    )


def _book(db: Session, book_id: int, user: User) -> Book:
    book = db.query(Book).filter(Book.id == book_id, Book.user_id == user.id).first()
    if not book:
        raise HTTPException(404, "书籍不存在")
    return book


@router.get("/plans", response_model=list[ChapterPlanOut])
def list_plans(book_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    book = _book(db, book_id, user)
    ensure_book_chapter_slots(db, book)
    plans = db.query(ChapterPlan).filter(ChapterPlan.book_id == book_id).order_by(ChapterPlan.chapter_no).all()
    chapters = {c.chapter_no: c for c in db.query(Chapter).filter(Chapter.book_id == book_id).all()}
    out = []
    for p in plans:
        st = chapters.get(p.chapter_no)
        if st:
            status = st.status
            if status == "planned" and has_content(st):
                status = "draft"
        else:
            status = "planned"
        out.append(
            ChapterPlanOut(
                id=p.id,
                chapter_no=p.chapter_no,
                title=p.title,
                mode=p.mode,
                scene=p.scene,
                plot_points=p.plot_points,
                comedy_core=p.comedy_core,
                pov_switch=p.pov_switch,
                character_names=p.character_names,
                meta_json=p.meta_json or {},
                status=status,
            )
        )
    return out


@router.put("/plans/{chapter_no}", response_model=ChapterPlanOut)
def update_plan(
    book_id: int,
    chapter_no: int,
    data: ChapterPlanUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _book(db, book_id, user)
    plan = (
        db.query(ChapterPlan)
        .filter(ChapterPlan.book_id == book_id, ChapterPlan.chapter_no == chapter_no)
        .first()
    )
    if not plan:
        raise HTTPException(404, "章节规划不存在")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(plan, k, v)
    db.commit()
    ch = db.query(Chapter).filter(Chapter.book_id == book_id, Chapter.chapter_no == chapter_no).first()
    return ChapterPlanOut(
        id=plan.id,
        chapter_no=plan.chapter_no,
        title=plan.title,
        mode=plan.mode,
        scene=plan.scene,
        plot_points=plan.plot_points,
        comedy_core=plan.comedy_core,
        pov_switch=plan.pov_switch,
        character_names=plan.character_names,
        meta_json=plan.meta_json or {},
        status=ch.status if ch else "planned",
    )


@router.get("/chapters", response_model=list[ChapterOut])
def list_chapters(book_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    book = _book(db, book_id, user)
    ensure_book_chapter_slots(db, book)
    chapters = db.query(Chapter).filter(Chapter.book_id == book_id).order_by(Chapter.chapter_no).all()
    return [_chapter_out(c) for c in chapters]


@router.get("/chapters/{chapter_no}", response_model=ChapterOut)
def get_chapter(
    book_id: int, chapter_no: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    _book(db, book_id, user)
    ch = db.query(Chapter).filter(Chapter.book_id == book_id, Chapter.chapter_no == chapter_no).first()
    if not ch:
        ch = Chapter(book_id=book_id, chapter_no=chapter_no, title=f"第{chapter_no}章")
        db.add(ch)
        db.commit()
        db.refresh(ch)
    ch.content = get_content(ch)
    return _chapter_out(ch)


@router.put("/chapters/{chapter_no}", response_model=ChapterOut)
def save_chapter(
    book_id: int,
    chapter_no: int,
    data: ChapterSave,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _book(db, book_id, user)
    ch = db.query(Chapter).filter(Chapter.book_id == book_id, Chapter.chapter_no == chapter_no).first()
    if not ch:
        ch = Chapter(book_id=book_id, chapter_no=chapter_no)
        db.add(ch)
    set_content(ch, data.content)
    ch.word_count = word_count(data.content)
    if data.title:
        ch.title = data.title
    if ch.status == "planned":
        ch.status = "draft"
    ch.updated_at = datetime.utcnow()
    db.add(ch)
    db.flush()
    db.add(ChapterVersion(chapter_id=ch.id, content=data.content, source="manual"))
    db.commit()
    db.refresh(ch)
    ch.content = data.content
    db.query(LintIssue).filter(LintIssue.chapter_id == ch.id).delete()
    run_lint(db, ch)
    return _chapter_out(ch)


@router.get("/chapters/{chapter_no}/lint", response_model=LintReport)
async def lint_chapter_api(
    book_id: int,
    chapter_no: int,
    use_ai: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.services.pipeline import run_ai_lint

    _book(db, book_id, user)
    book = db.query(Book).filter(Book.id == book_id).first()
    ch = db.query(Chapter).filter(Chapter.book_id == book_id, Chapter.chapter_no == chapter_no).first()
    if not ch:
        raise HTTPException(404, "章节不存在")
    if use_ai:
        await run_ai_lint(db, book, ch)
    report = run_lint(db, ch)
    for i in report["issues"]:
        i.setdefault("snippet", i.get("excerpt", ""))
        i.setdefault("blocking", i.get("severity") == "error")
    return LintReport(**report)


def _lint_report_out(report: dict) -> LintReport:
    for i in report["issues"]:
        i.setdefault("snippet", i.get("excerpt", ""))
        i.setdefault("blocking", i.get("severity") == "error")
    return LintReport(**report)


@router.post("/chapters/{chapter_no}/lint", response_model=LintReport)
async def lint_draft(
    book_id: int,
    chapter_no: int,
    data: LintCheckIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """对编辑器草稿做规则检查（不写库）；可选 AI 规约检查。"""
    book = _book(db, book_id, user)
    content = data.content or ""
    from app.services.rule_engine import LintResult

    issues: list[LintResult] = list(lint_chapter(content, chapter_no))
    if data.include_ai:
        ai_items = await run_ai_lint_on_content(db, book, content)
        seen: set[tuple[str, int, str]] = set()
        for item in ai_items:
            key = (item["rule_id"], item["line_no"], item.get("message", "")[:40])
            if key in seen:
                continue
            seen.add(key)
            issues.append(
                LintResult(
                    rule_id=item["rule_id"],
                    severity=item["severity"],
                    line_no=item["line_no"],
                    excerpt=item.get("excerpt", ""),
                    message=item.get("message", ""),
                    auto_fixable=item.get("auto_fixable", False),
                    blocking=item.get("blocking", False),
                )
            )
    report = lint_report_from_issues(content, issues)
    return _lint_report_out(report)


def _chapter_title(ch: Chapter | None, chapter_no: int) -> str:
    if ch and (ch.title or "").strip():
        return ch.title.strip()
    return f"第{chapter_no}章"


@router.post("/chapters/{chapter_no}/fix-draft", response_model=FixDraftOut)
def fix_draft(
    book_id: int,
    chapter_no: int,
    data: FixDraftIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """对草稿应用可自动修复的规则（章标题、逗号、破折号等），不写库，返回修复后正文与规则 lint。"""
    _book(db, book_id, user)
    ch = db.query(Chapter).filter(Chapter.book_id == book_id, Chapter.chapter_no == chapter_no).first()
    source = data.content or ""
    before = lint_chapter(source, chapter_no)
    before_auto = sum(1 for i in before if i.auto_fixable)
    content = auto_fix_content(
        source,
        chapter_no=chapter_no,
        chapter_title=_chapter_title(ch, chapter_no),
    )
    after = lint_chapter(content, chapter_no)
    after_auto = sum(1 for i in after if i.auto_fixable)
    report = lint_report_from_issues(content, after)
    return FixDraftOut(
        content=content,
        lint=_lint_report_out(report),
        fixed_count=max(0, before_auto - after_auto),
    )


@router.post("/chapters/{chapter_no}/fix-issue")
def fix_issue_draft(
    book_id: int,
    chapter_no: int,
    data: FixIssueIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """修复单条可自动修复的问题（草稿，不写库）。"""
    _book(db, book_id, user)
    ch = db.query(Chapter).filter(Chapter.book_id == book_id, Chapter.chapter_no == chapter_no).first()
    content = auto_fix_issue(
        data.content or "",
        {"rule_id": data.rule_id, "line_no": data.line_no, "auto_fixable": True},
        chapter_no=chapter_no,
        chapter_title=_chapter_title(ch, chapter_no),
    )
    report = lint_report_from_issues(content, lint_chapter(content, chapter_no))
    return {"content": content, "lint": _lint_report_out(report)}


@router.post("/chapters/{chapter_no}/fix-all", response_model=ChapterOut)
def fix_all(
    book_id: int,
    chapter_no: int,
    data: FixDraftIn | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _book(db, book_id, user)
    ch = db.query(Chapter).filter(Chapter.book_id == book_id, Chapter.chapter_no == chapter_no).first()
    if not ch:
        ch = Chapter(book_id=book_id, chapter_no=chapter_no, title=f"第{chapter_no}章", status="draft")
        db.add(ch)
        db.flush()
    source = (data.content if data and data.content.strip() else "") or get_content(ch)
    if not source.strip():
        raise HTTPException(400, "无正文可修复")
    content = auto_fix_content(
        source,
        chapter_no=chapter_no,
        chapter_title=_chapter_title(ch, chapter_no),
    )
    set_content(ch, content)
    ch.word_count = word_count(content)
    ch.updated_at = datetime.utcnow()
    if ch.status == "planned":
        ch.status = "draft"
    db.add(ChapterVersion(chapter_id=ch.id, content=content, source="auto_fix"))
    db.commit()
    run_lint(db, ch)
    db.refresh(ch)
    ch.content = content
    return _chapter_out(ch)


@router.post("/chapters/{chapter_no}/fix-commas", response_model=ChapterOut)
def fix_commas(
    book_id: int, chapter_no: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    return fix_all(book_id, chapter_no, db, user)


@router.post("/chapters/{chapter_no}/approve", response_model=ChapterOut)
def approve(
    book_id: int, chapter_no: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    _book(db, book_id, user)
    ch = db.query(Chapter).filter(Chapter.book_id == book_id, Chapter.chapter_no == chapter_no).first()
    if not ch:
        raise HTTPException(404, "章节不存在")
    report = run_lint(db, ch)
    blocking = [i for i in report["issues"] if i.get("severity") == "error" and i.get("blocking", True)]
    if blocking:
        raise HTTPException(
            400,
            f"仍有 {len(blocking)} 个须修复的错误（警告可忽略），请先处理或使用智能体改文",
        )
    ch.status = "approved"
    ch.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(ch)
    ch.content = get_content(ch)
    return _chapter_out(ch)


def _start_job(
    db: Session,
    bg: BackgroundTasks,
    book_id: int,
    chapter_no: int,
    job_type: str,
    instruction: str = "",
) -> GenerationJob:
    job = GenerationJob(
        book_id=book_id,
        chapter_no=chapter_no,
        job_type=job_type,
        status="pending",
        instruction=instruction or "",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    bg.add_task(_run_job_task, job.id)
    return job


async def _run_job_task(job_id: int):
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        await execute_generation_job(db, job_id)
    finally:
        db.close()


@router.post("/chapters/{chapter_no}/generate", response_model=JobOut, dependencies=[Depends(require_desktop_license)])
def generate(
    book_id: int,
    chapter_no: int,
    bg: BackgroundTasks,
    body: GenerateIn | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _book(db, book_id, user)
    ch = db.query(Chapter).filter(Chapter.book_id == book_id, Chapter.chapter_no == chapter_no).first()
    if not ch:
        ch = Chapter(book_id=book_id, chapter_no=chapter_no, status="planned")
        db.add(ch)
        db.commit()
    job = _start_job(db, bg, book_id, chapter_no, "draft", instruction=(body.instruction if body else "") or "")
    return job


@router.post("/chapters/{chapter_no}/expand", response_model=JobOut, dependencies=[Depends(require_desktop_license)])
def expand(
    book_id: int,
    chapter_no: int,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _book(db, book_id, user)
    job = _start_job(db, bg, book_id, chapter_no, "expand")
    return job


@router.post("/chapters/{chapter_no}/fix-ai", response_model=JobOut, dependencies=[Depends(require_desktop_license)])
def fix_ai(
    book_id: int,
    chapter_no: int,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _book(db, book_id, user)
    job = _start_job(db, bg, book_id, chapter_no, "fix")
    return job


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(
    book_id: int, job_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    _book(db, book_id, user)
    job = db.query(GenerationJob).filter(GenerationJob.id == job_id, GenerationJob.book_id == book_id).first()
    if not job:
        raise HTTPException(404, "任务不存在")
    return job
