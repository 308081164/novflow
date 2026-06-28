"""CLI: 从「我的AI成精了」导入演示书籍"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import Base, SessionLocal, engine
from app.services.import_template import create_book_from_template, seed_demo_user


def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = seed_demo_user(db)
        book = create_book_from_template(db, user, import_chapters=True)
        print(f"已导入书籍: {book.title} (id={book.id})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
