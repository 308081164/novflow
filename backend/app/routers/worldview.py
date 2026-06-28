from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Book, User, Worldview
from app.schemas import WorldviewIn, WorldviewOut
from app.services.ai_assist import generate_worldview

router = APIRouter(prefix="/books/{book_id}/worldview", tags=["worldview"])


def _book(db: Session, book_id: int, user: User) -> Book:
    book = db.query(Book).filter(Book.id == book_id, Book.user_id == user.id).first()
    if not book:
        raise HTTPException(404, "书籍不存在")
    return book


@router.get("", response_model=WorldviewOut)
def get_worldview(book_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _book(db, book_id, user)
    wv = db.query(Worldview).filter(Worldview.book_id == book_id).first()
    if not wv:
        wv = Worldview(book_id=book_id)
        db.add(wv)
        db.commit()
        db.refresh(wv)
    return wv


@router.put("", response_model=WorldviewOut)
def update_worldview(
    book_id: int,
    data: WorldviewIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _book(db, book_id, user)
    wv = db.query(Worldview).filter(Worldview.book_id == book_id).first()
    if not wv:
        wv = Worldview(book_id=book_id)
        db.add(wv)
    for k, v in data.model_dump().items():
        setattr(wv, k, v)
    db.commit()
    db.refresh(wv)
    return wv


async def _run_ai_wv(job_book_id: int, user_id: int):
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        book = db.query(Book).filter(Book.id == job_book_id).first()
        if user and book:
            await generate_worldview(db, user, book)
    finally:
        db.close()


@router.post("/ai-generate")
def ai_generate_worldview(
    book_id: int,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    book = _book(db, book_id, user)
    if not book.premise and not book.blurb:
        raise HTTPException(400, "请先填写作品梗概")
    bg.add_task(_run_ai_wv, book_id, user.id)
    return {"status": "started", "message": "AI 正在生成世界观，请稍后刷新"}


@router.post("/ai-generate-sync", response_model=WorldviewOut)
async def ai_generate_worldview_sync(
    book_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    book = _book(db, book_id, user)
    wv = await generate_worldview(db, user, book)
    return wv
