from fastapi import APIRouter, Depends, HTTPException

from sqlalchemy.orm import Session



from app.database import get_db

from app.deps import get_current_user

from app.models import Book, Character, User

from app.schemas import CharacterIn, CharacterOut, SetupCardOut

from app.services.character_cards import list_character_cards, sync_character_card
from app.services.storage import storage



router = APIRouter(prefix="/books/{book_id}/characters", tags=["characters"])





def _book(db: Session, book_id: int, user: User) -> Book:

    book = db.query(Book).filter(Book.id == book_id, Book.user_id == user.id).first()

    if not book:

        raise HTTPException(404, "书籍不存在")

    return book





@router.get("/cards", response_model=list[SetupCardOut])

def list_character_cards_api(book_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):

    _book(db, book_id, user)

    return [SetupCardOut(**c) for c in list_character_cards(db, book_id)]





@router.get("", response_model=list[CharacterOut])

def list_characters(book_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):

    _book(db, book_id, user)

    cards = list_character_cards(db, book_id)

    ids = [c["data"]["character_id"] for c in cards if c.get("data", {}).get("character_id")]

    if not ids:

        return []

    chars = db.query(Character).filter(Character.id.in_(ids)).all()

    by_id = {c.id: c for c in chars}

    return [by_id[i] for i in ids if i in by_id]





@router.post("", response_model=CharacterOut)

def create_character(

    book_id: int, data: CharacterIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)

):

    book = _book(db, book_id, user)

    ch = sync_character_card(

        db,

        book,

        {

            "type": "character",

            "title": data.name,

            "data": data.model_dump(),

        },

        overwrite=True,

    )

    return ch





@router.put("/{char_id}", response_model=CharacterOut)

def update_character(

    book_id: int,

    char_id: int,

    data: CharacterIn,

    db: Session = Depends(get_db),

    user: User = Depends(get_current_user),

):

    book = _book(db, book_id, user)

    ch = db.query(Character).filter(Character.id == char_id, Character.book_id == book_id).first()

    if not ch:

        raise HTTPException(404, "角色不存在")

    payload = data.model_dump()

    payload["character_id"] = char_id

    ch = sync_character_card(

        db,

        book,

        {"type": "character", "title": data.name, "data": payload},

        overwrite=True,

    )

    return ch





@router.delete("/{char_id}")

def delete_character(

    book_id: int,

    char_id: int,

    db: Session = Depends(get_db),

    user: User = Depends(get_current_user),

):

    _book(db, book_id, user)

    ch = db.query(Character).filter(Character.id == char_id, Character.book_id == book_id).first()

    if not ch:

        raise HTTPException(404, "角色不存在")

    for item in ch.images_json or []:
        if isinstance(item, dict) and item.get("object_key"):
            storage.delete_object(str(item["object_key"]))

    db.delete(ch)

    db.commit()

    return {"ok": True}


