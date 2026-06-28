"""数据库轻量迁移：为已有库添加新列"""
from sqlalchemy import inspect, text

from app.database import engine


def column_exists(table: str, column: str) -> bool:
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def _default_clause(dialect: str, typ: str, default: str) -> str:
    """生成各方言兼容的 DEFAULT 子句。"""
    if default.isdigit():
        return f"DEFAULT {default}"
    if dialect == "postgresql":
        base = typ.split("(")[0].upper()
        if base in ("INTEGER", "INT", "BIGINT", "SMALLINT"):
            return f"DEFAULT {default}"
        return "DEFAULT ''"
    return f"DEFAULT {default}"


def migrate() -> None:
    dialect = engine.dialect.name
    tables = set(inspect(engine).get_table_names())
    alters = [
        ("users", "deepseek_api_key", "VARCHAR(255)", "''"),
        ("books", "genre", "VARCHAR(100)", "''"),
        ("books", "premise", "TEXT", "''"),
        ("books", "setup_step", "INTEGER", "5"),
        ("books", "writing_rules", "TEXT", "''"),
        ("books", "corpus", "TEXT", "''"),
        ("characters", "content", "TEXT", "''"),
    ]

    pending = [
        (table, col, typ, default)
        for table, col, typ, default in alters
        if table in tables and not column_exists(table, col)
    ]

    for table, col, typ, default in pending:
        clause = _default_clause(dialect, typ, default)
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typ} {clause}"))

    if "worldviews" not in inspect(engine).get_table_names():
        from app.models import Worldview  # noqa: F401

        Worldview.__table__.create(bind=engine, checkfirst=True)

    if "setup_messages" not in inspect(engine).get_table_names():
        from app.models import SetupMessage  # noqa: F401

        SetupMessage.__table__.create(bind=engine, checkfirst=True)

    if "chapter_plans" in inspect(engine).get_table_names() and not column_exists("chapter_plans", "meta_json"):
        with engine.begin() as conn:
            if dialect == "postgresql":
                conn.execute(text("ALTER TABLE chapter_plans ADD COLUMN meta_json JSONB DEFAULT '{}'::jsonb"))
            else:
                conn.execute(text("ALTER TABLE chapter_plans ADD COLUMN meta_json JSON DEFAULT '{}'"))

    if "books" in inspect(engine).get_table_names() and not column_exists("books", "plot_framework"):
        with engine.begin() as conn:
            if dialect == "postgresql":
                conn.execute(text("ALTER TABLE books ADD COLUMN plot_framework JSONB DEFAULT '{}'::jsonb"))
            else:
                conn.execute(text("ALTER TABLE books ADD COLUMN plot_framework JSON DEFAULT '{}'"))

    if "setup_messages" in inspect(engine).get_table_names() and not column_exists("setup_messages", "actions_json"):
        with engine.begin() as conn:
            if dialect == "postgresql":
                conn.execute(text("ALTER TABLE setup_messages ADD COLUMN actions_json JSONB DEFAULT '[]'::jsonb"))
            else:
                conn.execute(text("ALTER TABLE setup_messages ADD COLUMN actions_json JSON DEFAULT '[]'"))

    if "generation_jobs" in inspect(engine).get_table_names() and not column_exists("generation_jobs", "instruction"):
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE generation_jobs ADD COLUMN instruction TEXT DEFAULT ''"))

    if "books" in tables and not column_exists("books", "write_agent_session_id"):
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE books ADD COLUMN write_agent_session_id VARCHAR(36) DEFAULT ''"))

    if "write_agent_messages" not in inspect(engine).get_table_names():
        from app.models import WriteAgentMessage  # noqa: F401

        WriteAgentMessage.__table__.create(bind=engine, checkfirst=True)

    user_alters = [
        ("users", "jimeng_api_key", "VARCHAR(255)", "''"),
        ("users", "jimeng_base_url", "VARCHAR(255)", "''"),
        ("users", "jimeng_model", "VARCHAR(120)", "''"),
        ("books", "cover_image_key", "VARCHAR(500)", "''"),
        ("characters", "images_json", "JSON", "'[]'"),
    ]
    for table, col, typ, default in user_alters:
        if table in inspect(engine).get_table_names() and not column_exists(table, col):
            clause = _default_clause(dialect, typ, default)
            with engine.begin() as conn:
                if dialect == "postgresql" and col == "images_json":
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} JSONB DEFAULT '[]'::jsonb"))
                elif dialect != "postgresql" and col == "images_json":
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} JSON DEFAULT '[]'"))
                else:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typ} {clause}"))

    if "chapter_illustrations" not in inspect(engine).get_table_names():
        from app.models import ChapterIllustration  # noqa: F401

        ChapterIllustration.__table__.create(bind=engine, checkfirst=True)

    if "setup_messages" in inspect(engine).get_table_names() and not column_exists("setup_messages", "meta_json"):
        with engine.begin() as conn:
            if dialect == "postgresql":
                conn.execute(text("ALTER TABLE setup_messages ADD COLUMN meta_json JSONB DEFAULT '{}'::jsonb"))
            else:
                conn.execute(text("ALTER TABLE setup_messages ADD COLUMN meta_json JSON DEFAULT '{}'"))
