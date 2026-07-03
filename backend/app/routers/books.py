import zipfile
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Book, Chapter, User
from app.schemas import (
    BookCreate,
    BookImportOut,
    BookOut,
    BookPackageImportOut,
    BookResourcesIn,
    BookResourcesOut,
    BookSetupUpdate,
    SyncSettingsOut,
)
from app.services.book_delete import delete_book as delete_book_service
from app.services.book_import import create_book_from_import
from app.services.book_package import export_book_package, import_book_package
from app.services.chapter_content import get_content, has_content
from app.services.image_gen import media_url
from app.services.pipeline import create_book_from_template, export_book_txt, ensure_book_chapter_slots, count_outline_planned
from app.services.setup_agent import resolve_effective_target_chapters, sync_settings_from_messages

router = APIRouter(prefix="/books", tags=["books"])


def book_to_out(book: Book, db: Session) -> BookOut:
    ensure_book_chapter_slots(db, book)
    chapters = db.query(Chapter).filter(Chapter.book_id == book.id).all()
    approved = sum(1 for c in chapters if c.status == "approved")
    written = sum(1 for c in chapters if has_content(c) or c.word_count > 100)
    planned = resolve_effective_target_chapters(book)
    return BookOut(
        id=book.id,
        title=book.title,
        blurb=book.blurb,
        platform=book.platform,
        template_id=book.template_id,
        genre=book.genre or "",
        premise=book.premise or "",
        setup_step=book.setup_step,
        target_chapters=book.target_chapters,
        words_per_chapter=book.words_per_chapter,
        planned_chapters=planned,
        outline_planned_count=count_outline_planned(db, book.id),
        chapter_count=len(chapters),
        written_count=written,
        approved_count=approved,
        cover_image_url=media_url(book.cover_image_key) if book.cover_image_key else "",
    )


def _get_owned(db: Session, book_id: int, user: User) -> Book:
    book = db.query(Book).filter(Book.id == book_id, Book.user_id == user.id).first()
    if not book:
        raise HTTPException(404, "书籍不存在")
    return book


@router.get("", response_model=list[BookOut])
def list_books(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    books = db.query(Book).filter(Book.user_id == user.id).order_by(Book.id.desc()).all()
    return [book_to_out(b, db) for b in books]


@router.post("", response_model=BookOut)
def create_book(data: BookCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    book = create_book_from_template(
        db,
        user.id,
        data.title,
        data.blurb,
        data.template_id,
        genre=data.genre,
        premise=data.premise or data.blurb,
        target_chapters=data.target_chapters,
    )
    return book_to_out(book, db)


@router.post("/import", response_model=BookImportOut)
async def import_book(
    title: str = Form(...),
    genre: str = Form(""),
    premise: str = Form(""),
    target_chapters: int = Form(300),
    adapt_with_ai: bool = Form(True),
    worldview: UploadFile | None = File(None),
    outline: UploadFile | None = File(None),
    writing_prefs: UploadFile | None = File(None),
    conventions: UploadFile | None = File(None),
    characters: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not title.strip():
        raise HTTPException(400, "请填写书名")
    try:
        book, stats = await create_book_from_import(
            db,
            user,
            title=title,
            genre=genre,
            premise=premise,
            target_chapters=max(10, min(2000, target_chapters)),
            worldview_file=worldview,
            outline_file=outline,
            writing_prefs_file=writing_prefs,
            conventions_file=conventions,
            character_files=characters,
            adapt_with_ai=adapt_with_ai,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    out = book_to_out(book, db)
    return BookImportOut(
        **out.model_dump(),
        imported_characters=int(stats.get("characters") or 0),
        has_worldview=bool(stats.get("has_worldview")),
        has_outline=bool(stats.get("has_outline")),
        has_writing_prefs=bool(stats.get("has_writing_prefs")),
        ai_adapted=bool(stats.get("ai_adapted")),
        adapt_warning=str(stats.get("adapt_warning") or ""),
    )


@router.post("/import-package", response_model=BookPackageImportOut)
async def import_book_package_route(
    package: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    raw = await package.read()
    if not raw:
        raise HTTPException(400, "请上传 .novflow.zip 书籍包")
    try:
        book, stats = import_book_package(db, user.id, raw)
    except zipfile.BadZipFile as exc:
        raise HTTPException(400, "无效的 zip 文件") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    out = book_to_out(book, db)
    return BookPackageImportOut(
        **out.model_dump(),
        imported_characters=int(stats.get("characters") or 0),
        chapter_plans=int(stats.get("chapter_plans") or 0),
        chapters_with_content=int(stats.get("chapters_with_content") or 0),
        setup_messages=int(stats.get("setup_messages") or 0),
        write_agent_messages=int(stats.get("write_agent_messages") or 0),
        media_files=int(stats.get("media_files") or 0),
        illustrations=int(stats.get("illustrations") or 0),
    )


@router.get("/{book_id}", response_model=BookOut)
def get_book(book_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return book_to_out(_get_owned(db, book_id, user), db)


@router.delete("/{book_id}")
def delete_book(book_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    book = _get_owned(db, book_id, user)
    delete_book_service(db, book)
    return {"ok": True}


@router.patch("/{book_id}/setup", response_model=BookOut)
def update_setup(
    book_id: int,
    data: BookSetupUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    book = _get_owned(db, book_id, user)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(book, k, v)
    db.commit()
    db.refresh(book)
    return book_to_out(book, db)


@router.patch("/{book_id}", response_model=BookOut)
def update_book(
    book_id: int,
    data: BookSetupUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新书名、简介、类型等基本信息（书库与智能体共用）。"""
    book = _get_owned(db, book_id, user)
    payload = data.model_dump(exclude_unset=True)
    payload.pop("setup_step", None)
    for k, v in payload.items():
        setattr(book, k, v)
    db.commit()
    db.refresh(book)
    return book_to_out(book, db)


@router.get("/{book_id}/export")
def export_book(book_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _get_owned(db, book_id, user)
    text = export_book_txt(db, book_id)
    return PlainTextResponse(text, media_type="text/plain; charset=utf-8")


@router.get("/{book_id}/export-package")
def export_book_package_route(
    book_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    book = _get_owned(db, book_id, user)
    data, filename = export_book_package(db, book)
    disp = f"attachment; filename*=UTF-8''{quote(filename)}"
    return Response(content=data, media_type="application/zip", headers={"Content-Disposition": disp})


def _book_resources_out(book: Book) -> BookResourcesOut:
    prefs = (book.writing_rules or "").strip()
    return BookResourcesOut(
        author_preferences=prefs,
        has_author_preferences=bool(prefs),
        writing_rules=prefs,
        corpus=(book.corpus or "").strip(),
        has_writing_rules=bool(prefs),
    )


@router.get("/{book_id}/resources", response_model=BookResourcesOut)
def get_book_resources(book_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    book = _get_owned(db, book_id, user)
    return _book_resources_out(book)


@router.patch("/{book_id}/resources", response_model=BookResourcesOut)
def update_book_resources(
    book_id: int,
    data: BookResourcesIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    book = _get_owned(db, book_id, user)
    prefs = data.author_preferences if data.author_preferences is not None else data.writing_rules
    if prefs is not None:
        book.writing_rules = prefs
    if data.corpus is not None:
        book.corpus = data.corpus
    db.commit()
    db.refresh(book)
    return _book_resources_out(book)


@router.post("/{book_id}/sync-settings", response_model=SyncSettingsOut)
def sync_book_settings(book_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    book = _get_owned(db, book_id, user)
    stats = sync_settings_from_messages(db, book)
    return SyncSettingsOut(**stats)
