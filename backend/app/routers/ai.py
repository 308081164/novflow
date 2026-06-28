from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Book, User
from app.schemas import BookSetupUpdate, CharacterAiIn, CharacterOut, OutlineAiIn, WorldviewOut
from app.services.ai_assist import generate_character, generate_outline, generate_writing_rules

router = APIRouter(prefix="/books/{book_id}/ai", tags=["ai"])


def _book(db: Session, book_id: int, user: User) -> Book:
    book = db.query(Book).filter(Book.id == book_id, Book.user_id == user.id).first()
    if not book:
        raise HTTPException(404, "书籍不存在")
    return book


@router.post("/character", response_model=CharacterOut)
async def ai_character(
    book_id: int,
    data: CharacterAiIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    book = _book(db, book_id, user)
    return await generate_character(db, user, book, data.hint)


@router.post("/outline")
async def ai_outline(
    book_id: int,
    data: OutlineAiIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    book = _book(db, book_id, user)
    plans = await generate_outline(db, user, book, data.start_chapter, data.count)
    return {"count": len(plans), "message": f"已生成/更新 {len(plans)} 章规划"}


@router.post("/writing-rules")
async def ai_rules(
    book_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    book = _book(db, book_id, user)
    text = await generate_writing_rules(db, user, book)
    return {"writing_rules": text, "author_preferences": text}
