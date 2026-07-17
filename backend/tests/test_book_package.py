"""书籍包导出/导入往返与封面浏览接口测试。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.deps_license import require_desktop_license
from app.models import Chapter, ChapterPlan, Character, SetupMessage, User, WriteAgentMessage
from app.routers.books import book_to_out
from app.routers.chapters import list_chapters, list_plans
from app.routers.characters import list_character_cards_api
from app.routers.images import router as images_router
from app.services.book_package import (
    _remap_object_key,
    _rewrite_json_keys,
    export_book_package,
    import_book_package,
)
from app.services.chapter_content import set_content
from app.services.character_cards import list_character_cards
from app.services.image_gen import enrich_character_images, media_url, refresh_meta_images
from app.services.pipeline import chapter_plan_has_outline, count_outline_planned, create_book_from_template
from app.auth import hash_password


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _user(db):
    user = User(email="pkg@test.com", password_hash=hash_password("pass"), display_name="Pkg")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_book_package_import_round_trip():
    db = _session()
    user = _user(db)
    book = create_book_from_template(db, user.id, "往返测试", "简介", "blank", genre="测试", target_chapters=5)
    ch = db.query(Chapter).filter(Chapter.book_id == book.id, Chapter.chapter_no == 1).first()
    set_content(ch, "第一章正文内容。")
    ch.word_count = 8
    ch.status = "draft"
    plan10 = (
        db.query(ChapterPlan)
        .filter(ChapterPlan.book_id == book.id, ChapterPlan.chapter_no == 1)
        .first()
    )
    plan10.title = "开局逃亡"
    plan10.scene = "闵行群租"
    plan10.plot_points = "USB开场；决定逃亡"
    plan10.character_names = "陆沉舟、顾念"
    plan10.meta_json = {"cast": ["陆沉舟", "顾念"], "events": ["赛博私奔"]}
    # 仅有标题/场景、无 plot_points 也应算已规划
    plan2 = (
        db.query(ChapterPlan)
        .filter(ChapterPlan.book_id == book.id, ChapterPlan.chapter_no == 2)
        .first()
    )
    plan2.title = "社区过关"
    plan2.scene = "社区门口"
    plan2.plot_points = ""
    db.commit()

    assert count_outline_planned(db, book.id) >= 2

    raw, _ = export_book_package(db, book)
    db2 = _session()
    user2 = _user(db2)
    imported, stats = import_book_package(db2, user2.id, raw)

    assert imported.title == "往返测试"
    assert stats["chapters_with_content"] == 1
    assert stats["chapter_plans"] >= 5
    out = book_to_out(imported, db2)
    assert out.written_count >= 1
    assert out.outline_planned_count >= 2

    chapters = list_chapters(imported.id, db2, user2)
    assert len(chapters) >= 5
    first = next(c for c in chapters if c.chapter_no == 1)
    assert "第一章正文" in first.content

    plans = list_plans(imported.id, db2, user2)
    assert len(plans) >= 5
    p1 = next(p for p in plans if p.chapter_no == 1)
    assert p1.title == "开局逃亡"
    assert p1.scene == "闵行群租"
    assert "逃亡" in p1.plot_points
    assert chapter_plan_has_outline(
        db2.query(ChapterPlan)
        .filter(ChapterPlan.book_id == imported.id, ChapterPlan.chapter_no == 1)
        .first()
    )
    p2 = next(p for p in plans if p.chapter_no == 2)
    assert p2.title == "社区过关"
    assert p2.scene == "社区门口"
    assert count_outline_planned(db2, imported.id) >= 2


def test_chapter_plan_from_synopsis_alias():
    """书籍包若使用 synopsis/comedy_hook 别名，导入后应写入 plot_points/comedy_core。"""
    import io
    import json
    import zipfile

    from app.services.book_package import PACKAGE_APP, PACKAGE_VERSION

    db = _session()
    user = _user(db)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps({"format": PACKAGE_APP, "version": PACKAGE_VERSION, "source_book_id": 1}),
        )
        zf.writestr("book.json", json.dumps({"title": "别名测试", "target_chapters": 3}))
        zf.writestr(
            "chapter_plans.json",
            json.dumps(
                [
                    {
                        "chapter_no": 10,
                        "title": "第十章标题",
                        "synopsis": "情节要点写在 synopsis",
                        "scene": "诊所",
                        "comedy_hook": "一本正经",
                        "cast": ["陈默"],
                        "events": ["对峙"],
                    }
                ]
            ),
        )
        zf.writestr("chapters.json", json.dumps([{"chapter_no": 10, "title": "第十章标题", "status": "planned"}]))
    imported, stats = import_book_package(db, user.id, buf.getvalue())
    assert stats["chapter_plans"] == 1
    plans = list_plans(imported.id, db, user)
    p10 = next(p for p in plans if p.chapter_no == 10)
    assert p10.plot_points == "情节要点写在 synopsis"
    assert p10.comedy_core == "一本正经"
    assert p10.scene == "诊所"
    assert "陈默" in (p10.character_names or "")
    assert count_outline_planned(db, imported.id) >= 1
    out = book_to_out(imported, db)
    assert out.outline_planned_count >= 1


def test_images_read_routes_not_globally_license_gated():
    """浏览类接口不应挂在 router 级授权依赖上。"""
    assert not images_router.dependencies

    gated_paths = set()
    for route in images_router.routes:
        path = getattr(route, "path", "")
        for dep in getattr(route, "dependencies", []) or []:
            if getattr(dep, "dependency", None) is require_desktop_license:
                gated_paths.add(path)
    assert "/books/{book_id}/cover" not in gated_paths
    assert "/media/{object_key:path}" not in gated_paths
    assert "/books/{book_id}/cover/generate" in gated_paths


def test_rewrite_media_urls_and_object_keys():
    old, new = 3, 99
    key = "images/3/characters/abc.png"
    assert _remap_object_key(key, old, new) == "images/99/characters/abc.png"
    url = "/api/v1/media/images/3/characters/abc.png"
    assert _rewrite_json_keys(url, old, new) == "/api/v1/media/images/99/characters/abc.png"
    payload = {
        "images": [{"object_key": key, "url": url, "character_id": 7}],
        "cards_json": [{"type": "character", "data": {"character_id": 7, "name": "顾念"}}],
    }
    rewritten = _rewrite_json_keys(payload, old, new)
    assert rewritten["images"][0]["object_key"] == "images/99/characters/abc.png"
    assert rewritten["images"][0]["url"] == "/api/v1/media/images/99/characters/abc.png"


def test_refresh_meta_images_uses_object_key():
    meta = refresh_meta_images(
        {
            "images": [
                {
                    "object_key": "images/12/covers/x.png",
                    "url": "/api/v1/media/images/3/covers/x.png",
                    "kind": "cover",
                }
            ]
        }
    )
    assert meta["images"][0]["url"] == media_url("images/12/covers/x.png")


def test_book_package_imports_characters_and_chat_images():
    """导入后角色页可读 Character 表；聊天图片 url 与新 book_id 对齐。"""
    db = _session()
    user = _user(db)
    book = create_book_from_template(db, user.id, "角色导入", "简介", "blank", genre="测试", target_chapters=3)
    old_key = f"images/{book.id}/characters/portrait.png"
    ch = Character(
        book_id=book.id,
        name="顾念",
        role="ai",
        summary="私人AI",
        voice_notes="梗外放",
        content="完整角色卡正文",
        images_json=[
            {
                "object_key": old_key,
                "url": media_url(old_key),
                "kind": "character",
                "prompt": "立绘",
                "character_id": 0,
            }
        ],
    )
    db.add(ch)
    db.flush()
    ch.images_json[0]["character_id"] = ch.id
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(ch, "images_json")
    db.add(
        SetupMessage(
            book_id=book.id,
            role="assistant",
            content="已生成封面",
            cards_json=[],
            meta_json={
                "images": [
                    {
                        "object_key": f"images/{book.id}/covers/c.png",
                        "url": media_url(f"images/{book.id}/covers/c.png"),
                        "kind": "cover",
                    }
                ]
            },
        )
    )
    db.add(
        WriteAgentMessage(
            book_id=book.id,
            session_id="s1",
            role="assistant",
            content="角色卡",
            cards_json=[
                {
                    "id": "c1",
                    "type": "character",
                    "title": "陆沉舟",
                    "status": "applied",
                    "data": {
                        "character_id": 9999,
                        "name": "陆沉舟",
                        "role": "protagonist",
                        "summary": "主角",
                        "content": "从消息卡片回填",
                    },
                }
            ],
            meta_json={},
        )
    )
    db.commit()

    raw, _ = export_book_package(db, book)
    db2 = _session()
    user2 = _user(db2)
    imported, stats = import_book_package(db2, user2.id, raw)

    assert stats["characters"] >= 2
    cards = list_character_cards(db2, imported.id)
    names = {c["data"]["name"] for c in cards}
    assert "顾念" in names
    assert "陆沉舟" in names
    api_cards = list_character_cards_api(imported.id, db2, user2)
    assert len(api_cards) >= 2

    guniang = (
        db2.query(Character)
        .filter(Character.book_id == imported.id, Character.name == "顾念")
        .first()
    )
    assert guniang is not None
    assert guniang.content == "完整角色卡正文"
    enriched = enrich_character_images(guniang)
    assert enriched
    assert enriched[0]["object_key"].startswith(f"images/{imported.id}/")
    assert enriched[0]["url"] == media_url(enriched[0]["object_key"])

    setup = (
        db2.query(SetupMessage)
        .filter(SetupMessage.book_id == imported.id, SetupMessage.role == "assistant")
        .first()
    )
    assert setup is not None
    imgs = (setup.meta_json or {}).get("images") or []
    assert imgs
    assert imgs[0]["object_key"].startswith(f"images/{imported.id}/")
    assert imgs[0]["url"] == media_url(imgs[0]["object_key"])
