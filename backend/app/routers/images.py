from fastapi import APIRouter, Depends, File, HTTPException, Header, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth import get_current_user_id
from app.database import get_db
from app.models import Book, Chapter, Character, ChapterIllustration, User
from app.schemas import (
    CharacterImageGenerateIn,
    CharacterPortraitActiveIn,
    CoverGenerateIn,
    GeneratedImageOut,
    IllustrationGenerateIn,
    ImageRefineIn,
    JimengTestIn,
)
from app.services.image_gen import (
    enrich_character_images,
    generate_book_cover,
    generate_character_image,
    generate_chapter_illustration,
    list_chapter_illustrations,
    media_url,
    set_active_portrait_object_key,
)
from app.services.image_upload import ImageUploadError, upload_book_cover, upload_character_image, upload_chapter_illustration
from app.services.jimeng_image import JimengError, test_connection
from app.services.storage import storage

router = APIRouter(tags=["images"])


async def _read_image_file(file: UploadFile) -> tuple[bytes, str, str | None]:
    if not file or not file.filename:
        raise HTTPException(400, "请选择图片文件")
    data = await file.read()
    return data, file.filename, file.content_type


def _auth_user(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    access_token: str | None = Query(default=None),
) -> User:
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    elif access_token:
        token = access_token
    if not token:
        raise HTTPException(401, "未登录")
    user_id = get_current_user_id(token)
    if not user_id:
        raise HTTPException(401, "登录已过期")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(401, "用户不存在")
    return user


def _owned_book(db: Session, book_id: int, user: User) -> Book:
    book = db.query(Book).filter(Book.id == book_id, Book.user_id == user.id).first()
    if not book:
        raise HTTPException(404, "书籍不存在")
    return book


def _chapter(db: Session, book_id: int, chapter_no: int) -> Chapter:
    ch = db.query(Chapter).filter(Chapter.book_id == book_id, Chapter.chapter_no == chapter_no).first()
    if not ch:
        raise HTTPException(404, "章节不存在")
    return ch


@router.get("/media/{object_key:path}")
def serve_media(
    object_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(_auth_user),
):
    if not object_key.startswith("images/"):
        raise HTTPException(403, "无效路径")
    parts = object_key.split("/")
    if len(parts) < 2 or not parts[1].isdigit():
        raise HTTPException(403, "无效路径")
    _owned_book(db, int(parts[1]), user)
    data = storage.get_bytes(object_key)
    if not data:
        raise HTTPException(404, "文件不存在")
    ct = "image/png"
    if object_key.endswith(".jpg") or object_key.endswith(".jpeg"):
        ct = "image/jpeg"
    elif object_key.endswith(".webp"):
        ct = "image/webp"
    elif object_key.endswith(".gif"):
        ct = "image/gif"
    return Response(content=data, media_type=ct)


@router.post("/settings/jimeng/test")
async def test_jimeng_api(data: JimengTestIn, user: User = Depends(_auth_user)):
    from app.services.api_key import resolve_jimeng_config

    cfg = resolve_jimeng_config(user)
    key = (data.api_key or "").strip() or cfg["api_key"]
    base = (data.base_url or "").strip() or cfg["base_url"]
    model = (data.model or "").strip() or cfg["model"]
    if not key:
        raise HTTPException(400, "请提供 API Key")
    try:
        return await test_connection(key, base_url=base, model=model)
    except JimengError as exc:
        raise HTTPException(400, str(exc))


@router.post("/books/{book_id}/cover/upload", response_model=GeneratedImageOut)
async def upload_cover(
    book_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(_auth_user),
):
    book = _owned_book(db, book_id, user)
    data, filename, content_type = await _read_image_file(file)
    try:
        img = upload_book_cover(db, user, book, data, filename, content_type)
        return GeneratedImageOut(**img)
    except ImageUploadError as exc:
        raise HTTPException(400, str(exc))


@router.post("/books/{book_id}/cover/generate", response_model=GeneratedImageOut)
async def generate_cover(
    book_id: int,
    data: CoverGenerateIn,
    db: Session = Depends(get_db),
    user: User = Depends(_auth_user),
):
    book = _owned_book(db, book_id, user)
    try:
        img = await generate_book_cover(db, user, book, data.prompt)
        return GeneratedImageOut(**img)
    except JimengError as exc:
        raise HTTPException(400, str(exc))


@router.get("/books/{book_id}/cover")
def get_cover(book_id: int, db: Session = Depends(get_db), user: User = Depends(_auth_user)):
    book = _owned_book(db, book_id, user)
    if not book.cover_image_key:
        return {"url": "", "object_key": ""}
    return {"url": media_url(book.cover_image_key), "object_key": book.cover_image_key}


@router.post("/books/{book_id}/characters/{char_id}/images/upload", response_model=GeneratedImageOut)
async def upload_character_image_api(
    book_id: int,
    char_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(_auth_user),
):
    _owned_book(db, book_id, user)
    ch = db.query(Character).filter(Character.id == char_id, Character.book_id == book_id).first()
    if not ch:
        raise HTTPException(404, "角色不存在")
    book = db.query(Book).filter(Book.id == book_id).first()
    data, filename, content_type = await _read_image_file(file)
    try:
        img = upload_character_image(db, book, ch, data, filename, content_type)
        return GeneratedImageOut(**img)
    except ImageUploadError as exc:
        raise HTTPException(400, str(exc))


@router.post("/books/{book_id}/characters/{char_id}/images/generate", response_model=GeneratedImageOut)
async def generate_character_image_api(
    book_id: int,
    char_id: int,
    data: CharacterImageGenerateIn,
    db: Session = Depends(get_db),
    user: User = Depends(_auth_user),
):
    _owned_book(db, book_id, user)
    ch = db.query(Character).filter(Character.id == char_id, Character.book_id == book_id).first()
    if not ch:
        raise HTTPException(404, "角色不存在")
    book = db.query(Book).filter(Book.id == book_id).first()
    try:
        img = await generate_character_image(
            db, user, book, ch, data.prompt, data.parent_object_key
        )
        return GeneratedImageOut(**img)
    except JimengError as exc:
        raise HTTPException(400, str(exc))


@router.get("/books/{book_id}/characters/{char_id}/images")
def list_character_images(
    book_id: int,
    char_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_auth_user),
):
    _owned_book(db, book_id, user)
    ch = db.query(Character).filter(Character.id == char_id, Character.book_id == book_id).first()
    if not ch:
        raise HTTPException(404, "角色不存在")
    return [GeneratedImageOut(**x) for x in enrich_character_images(ch)]


@router.post("/books/{book_id}/characters/{char_id}/images/active", response_model=GeneratedImageOut)
def set_character_active_portrait(
    book_id: int,
    char_id: int,
    data: CharacterPortraitActiveIn,
    db: Session = Depends(get_db),
    user: User = Depends(_auth_user),
):
    _owned_book(db, book_id, user)
    ch = db.query(Character).filter(Character.id == char_id, Character.book_id == book_id).first()
    if not ch:
        raise HTTPException(404, "角色不存在")
    key = (data.object_key or "").strip()
    if not key:
        raise HTTPException(400, "请指定 object_key")
    found = None
    for raw in ch.images_json or []:
        if isinstance(raw, dict) and raw.get("object_key") == key:
            found = raw
            break
    if not found:
        raise HTTPException(404, "立绘版本不存在")
    set_active_portrait_object_key(ch, key)
    db.commit()
    db.refresh(ch)
    enriched = enrich_character_images(ch)
    for item in enriched:
        if item.get("object_key") == key:
            return GeneratedImageOut(**item)
    raise HTTPException(500, "设置失败")


@router.delete("/books/{book_id}/characters/{char_id}/images/{image_index}")
def delete_character_image(
    book_id: int,
    char_id: int,
    image_index: int,
    db: Session = Depends(get_db),
    user: User = Depends(_auth_user),
):
    _owned_book(db, book_id, user)
    ch = db.query(Character).filter(Character.id == char_id, Character.book_id == book_id).first()
    if not ch:
        raise HTTPException(404, "角色不存在")
    images = list(ch.images_json or [])
    if image_index < 0 or image_index >= len(images):
        raise HTTPException(404, "图片不存在")
    item = images.pop(image_index)
    if isinstance(item, dict) and item.get("object_key"):
        deleted_key = str(item["object_key"])
        storage.delete_object(deleted_key)
        arc = dict(ch.arc_json or {})
        if arc.get("active_portrait_object_key") == deleted_key:
            arc.pop("active_portrait_object_key", None)
            if images:
                last = images[-1]
                if isinstance(last, dict) and last.get("object_key"):
                    arc["active_portrait_object_key"] = str(last["object_key"])
            ch.arc_json = arc
    ch.images_json = images
    db.commit()
    return {"ok": True}


@router.get("/books/{book_id}/chapters/{chapter_no}/illustrations", response_model=list[GeneratedImageOut])
def get_chapter_illustrations(
    book_id: int,
    chapter_no: int,
    db: Session = Depends(get_db),
    user: User = Depends(_auth_user),
):
    _owned_book(db, book_id, user)
    chapter = _chapter(db, book_id, chapter_no)
    return [GeneratedImageOut(**x) for x in list_chapter_illustrations(db, chapter)]


@router.post("/books/{book_id}/chapters/{chapter_no}/illustrations/upload", response_model=GeneratedImageOut)
async def upload_illustration_api(
    book_id: int,
    chapter_no: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(_auth_user),
):
    book = _owned_book(db, book_id, user)
    chapter = _chapter(db, book_id, chapter_no)
    data, filename, content_type = await _read_image_file(file)
    try:
        img = upload_chapter_illustration(db, book, chapter, data, filename, content_type)
        return GeneratedImageOut(**img)
    except ImageUploadError as exc:
        raise HTTPException(400, str(exc))


@router.post("/books/{book_id}/chapters/{chapter_no}/illustrations/generate", response_model=GeneratedImageOut)
async def generate_illustration_api(
    book_id: int,
    chapter_no: int,
    data: IllustrationGenerateIn,
    db: Session = Depends(get_db),
    user: User = Depends(_auth_user),
):
    book = _owned_book(db, book_id, user)
    chapter = _chapter(db, book_id, chapter_no)
    try:
        img = await generate_chapter_illustration(
            db,
            user,
            book,
            chapter,
            passage=data.passage,
            prompt=data.prompt,
            parent_id=data.parent_id,
            character_ids=data.character_ids,
        )
        return GeneratedImageOut(**img)
    except JimengError as exc:
        raise HTTPException(400, str(exc))


@router.delete("/books/{book_id}/chapters/{chapter_no}/illustrations/{ill_id}")
def delete_illustration(
    book_id: int,
    chapter_no: int,
    ill_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_auth_user),
):
    _owned_book(db, book_id, user)
    chapter = _chapter(db, book_id, chapter_no)
    ill = db.query(ChapterIllustration).filter(
        ChapterIllustration.id == ill_id,
        ChapterIllustration.chapter_id == chapter.id,
    ).first()
    if not ill:
        raise HTTPException(404, "插图不存在")
    storage.delete_object(ill.object_key)
    db.delete(ill)
    db.commit()
    return {"ok": True}


@router.post("/books/{book_id}/images/refine", response_model=GeneratedImageOut)
async def refine_image(
    book_id: int,
    data: ImageRefineIn,
    db: Session = Depends(get_db),
    user: User = Depends(_auth_user),
):
    book = _owned_book(db, book_id, user)
    kind = data.kind
    try:
        if kind == "cover":
            from app.services.image_gen import _call_and_store, _image_record, build_cover_prompt

            prompt = f"{build_cover_prompt(book)}。调整要求：{data.prompt}"
            object_key, _ = await _call_and_store(
                user, book.id, "cover", prompt, reference_keys=[data.parent_object_key] if data.parent_object_key else None
            )
            book.cover_image_key = object_key
            db.commit()
            return GeneratedImageOut(**_image_record(object_key, prompt, "cover"))

        if kind == "character" and data.character_id:
            ch = db.query(Character).filter(Character.id == data.character_id, Character.book_id == book_id).first()
            if not ch:
                raise HTTPException(404, "角色不存在")
            img = await generate_character_image(
                db, user, book, ch, data.prompt, data.parent_object_key
            )
            return GeneratedImageOut(**img)

        if kind == "illustration" and data.chapter_no:
            chapter = _chapter(db, book_id, data.chapter_no)
            img = await generate_chapter_illustration(
                db,
                user,
                book,
                chapter,
                prompt=data.prompt,
                parent_id=data.parent_id,
                parent_object_key=data.parent_object_key,
            )
            return GeneratedImageOut(**img)

        raise HTTPException(400, "无效的精修参数")
    except JimengError as exc:
        raise HTTPException(400, str(exc))
