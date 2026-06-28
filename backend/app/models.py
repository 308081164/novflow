from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(100), default="作者")
    deepseek_api_key: Mapped[str] = mapped_column(String(255), default="")
    jimeng_api_key: Mapped[str] = mapped_column(String(255), default="")
    jimeng_base_url: Mapped[str] = mapped_column(String(255), default="")
    jimeng_model: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    books: Mapped[list["Book"]] = relationship(back_populates="owner")


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200))
    blurb: Mapped[str] = mapped_column(Text, default="")
    platform: Mapped[str] = mapped_column(String(50), default="fanqie")
    template_id: Mapped[str] = mapped_column(String(80), default="chase-comedy")
    target_chapters: Mapped[int] = mapped_column(Integer, default=300)
    words_per_chapter: Mapped[int] = mapped_column(Integer, default=2000)
    rule_summary: Mapped[str] = mapped_column(Text, default="")
    genre: Mapped[str] = mapped_column(String(100), default="")
    premise: Mapped[str] = mapped_column(Text, default="")
    setup_step: Mapped[int] = mapped_column(Integer, default=5)
    writing_rules: Mapped[str] = mapped_column(Text, default="")
    plot_framework: Mapped[dict] = mapped_column(JSON, default=dict)
    corpus: Mapped[str] = mapped_column(Text, default="")
    write_agent_session_id: Mapped[str] = mapped_column(String(36), default="")
    cover_image_key: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    owner: Mapped["User"] = relationship(back_populates="books")
    characters: Mapped[list["Character"]] = relationship(back_populates="book", cascade="all, delete-orphan")
    chapter_plans: Mapped[list["ChapterPlan"]] = relationship(back_populates="book", cascade="all, delete-orphan")
    chapters: Mapped[list["Chapter"]] = relationship(back_populates="book", cascade="all, delete-orphan")
    worldview: Mapped["Worldview | None"] = relationship(back_populates="book", cascade="all, delete-orphan", uselist=False)
    setup_messages: Mapped[list["SetupMessage"]] = relationship(back_populates="book", cascade="all, delete-orphan")
    write_agent_messages: Mapped[list["WriteAgentMessage"]] = relationship(
        back_populates="book", cascade="all, delete-orphan"
    )


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"))
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(50), default="support")
    summary: Mapped[str] = mapped_column(Text, default="")
    voice_notes: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    arc_json: Mapped[dict] = mapped_column(JSON, default=dict)
    images_json: Mapped[list] = mapped_column(JSON, default=list)

    book: Mapped["Book"] = relationship(back_populates="characters")


class ChapterPlan(Base):
    __tablename__ = "chapter_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"))
    chapter_no: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200), default="")
    mode: Mapped[str] = mapped_column(String(20), default="逃")
    scene: Mapped[str] = mapped_column(String(200), default="")
    plot_points: Mapped[str] = mapped_column(Text, default="")
    comedy_core: Mapped[str] = mapped_column(String(200), default="")
    pov_switch: Mapped[bool] = mapped_column(Boolean, default=False)
    character_names: Mapped[str] = mapped_column(String(500), default="")
    meta_json: Mapped[dict] = mapped_column(JSON, default=dict)

    book: Mapped["Book"] = relationship(back_populates="chapter_plans")


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"))
    chapter_no: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="planned")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    book: Mapped["Book"] = relationship(back_populates="chapters")
    versions: Mapped[list["ChapterVersion"]] = relationship(back_populates="chapter", cascade="all, delete-orphan")
    lint_issues: Mapped[list["LintIssue"]] = relationship(back_populates="chapter", cascade="all, delete-orphan")
    illustrations: Mapped[list["ChapterIllustration"]] = relationship(
        back_populates="chapter", cascade="all, delete-orphan"
    )


class ChapterVersion(Base):
    __tablename__ = "chapter_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"))
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(30), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    chapter: Mapped["Chapter"] = relationship(back_populates="versions")


class LintIssue(Base):
    __tablename__ = "lint_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"))
    rule_id: Mapped[str] = mapped_column(String(80))
    severity: Mapped[str] = mapped_column(String(20), default="error")
    line_no: Mapped[int] = mapped_column(Integer, default=0)
    excerpt: Mapped[str] = mapped_column(Text, default="")
    message: Mapped[str] = mapped_column(Text, default="")
    auto_fixable: Mapped[bool] = mapped_column(Boolean, default=False)
    fixed: Mapped[bool] = mapped_column(Boolean, default=False)

    chapter: Mapped["Chapter"] = relationship(back_populates="lint_issues")


class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"))
    chapter_no: Mapped[int] = mapped_column(Integer)
    job_type: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    instruction: Mapped[str] = mapped_column(Text, default="")
    result_content: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Worldview(Base):
    __tablename__ = "worldviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), unique=True)
    era: Mapped[str] = mapped_column(String(200), default="")
    setting: Mapped[str] = mapped_column(String(200), default="")
    tone: Mapped[str] = mapped_column(String(200), default="")
    timeline_text: Mapped[str] = mapped_column(Text, default="")
    taboos: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")

    book: Mapped["Book"] = relationship(back_populates="worldview")


class SetupMessage(Base):
    __tablename__ = "setup_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, default="")
    cards_json: Mapped[list] = mapped_column(JSON, default=list)
    actions_json: Mapped[list] = mapped_column(JSON, default=list)
    meta_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    book: Mapped["Book"] = relationship(back_populates="setup_messages")


class ChapterIllustration(Base):
    __tablename__ = "chapter_illustrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"), index=True)
    object_key: Mapped[str] = mapped_column(String(500))
    prompt: Mapped[str] = mapped_column(Text, default="")
    parent_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("chapter_illustrations.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    chapter: Mapped["Chapter"] = relationship(back_populates="illustrations")


class WriteAgentMessage(Base):
    __tablename__ = "write_agent_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[str] = mapped_column(Text, default="")
    cards_json: Mapped[list] = mapped_column(JSON, default=list)
    actions_json: Mapped[list] = mapped_column(JSON, default=list)
    meta_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    book: Mapped["Book"] = relationship(back_populates="write_agent_messages")
