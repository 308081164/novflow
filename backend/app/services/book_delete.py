"""删除书籍及其关联数据与 MinIO 资源。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Book, GenerationJob
from app.services.storage import storage


def delete_book(db: Session, book: Book) -> None:
    book_id = book.id

    if storage.enabled:
        storage.delete_prefix(f"{book_id}/")
        storage.delete_prefix(f"images/{book_id}/")

    db.query(GenerationJob).filter(GenerationJob.book_id == book_id).delete()
    db.delete(book)
    db.commit()
