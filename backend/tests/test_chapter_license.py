"""章节生成授权与定稿（无授权）测试。"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from shared.license.license_common import (  # noqa: E402
    generate_key_pair,
    generate_license_code,
    write_license,
)
from shared.license.products import DESKTOP  # noqa: E402

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import hash_password
from app.database import Base
from app.deps_license import require_desktop_license
from app.models import Chapter, GenerationJob, User
from app.routers import chapters as chapters_router
from app.routers.chapters import approve
from app.services.chapter_content import set_content
from app.services.pipeline import create_book_from_template, execute_generation_job

HW_ID = "b" * 64
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


@pytest.fixture()
def keypair(monkeypatch, tmp_path):
    public_der, private_der = generate_key_pair()
    monkeypatch.setenv("NOVFLOW_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NOVFLOW_PUBKEY", public_der.hex())
    private_path = tmp_path / "issuer-private.der"
    private_path.write_bytes(private_der)
    return public_der, private_path


def _signed_code(private_path: Path, *, valid_until: str) -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_key = serialization.load_der_private_key(private_path.read_bytes(), password=None)
    assert isinstance(private_key, Ed25519PrivateKey)
    payload = {
        "hw_id": HW_ID,
        "license_mode": "time_limited",
        "valid_until": valid_until,
    }
    return generate_license_code(DESKTOP, payload, private_key)


def _store_expired_license(private_path: Path) -> None:
    code = _signed_code(private_path, valid_until=YESTERDAY)
    write_license(
        DESKTOP,
        {
            "license_code": code,
            "license_mode": "time_limited",
            "activated_at": date.today().isoformat(),
            "hw_id": HW_ID,
            "valid_until": YESTERDAY,
            "product_id": DESKTOP.product_id,
        },
    )


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _book_with_chapter(db):
    user = User(email="ch@test.com", password_hash=hash_password("pass"), display_name="Author")
    db.add(user)
    db.commit()
    db.refresh(user)
    book = create_book_from_template(db, user.id, "授权测试", "", "blank", target_chapters=3)
    ch = db.query(Chapter).filter(Chapter.book_id == book.id, Chapter.chapter_no == 1).first()
    set_content(ch, "# 第001章 测试\n\n" + "正文内容。" * 200)
    ch.status = "draft"
    db.commit()
    return user, book, ch


def _enable_desktop_mode(monkeypatch):
    monkeypatch.setenv("NOVFLOW_DESKTOP", "1")
    monkeypatch.setattr("app.config.IS_DESKTOP", True, raising=False)
    monkeypatch.setattr("app.deps_license.IS_DESKTOP", True, raising=False)


def _patch_expired_license(monkeypatch):
    class _FakeLicenseService:
        def __init__(self, _product):
            pass

        def status(self):
            return {
                "activated": False,
                "error": "授权已过期",
                "valid_until": YESTERDAY,
            }

    monkeypatch.setattr("app.deps_license.LicenseService", _FakeLicenseService)


def test_chapter_ai_routes_are_license_gated():
    gated = set()
    for route in chapters_router.router.routes:
        path = getattr(route, "path", "")
        for dep in getattr(route, "dependencies", []) or []:
            if getattr(dep, "dependency", None) is require_desktop_license:
                gated.add(path)
    assert "/books/{book_id}/chapters/{chapter_no}/generate" in gated
    assert "/books/{book_id}/chapters/{chapter_no}/expand" in gated
    assert "/books/{book_id}/chapters/{chapter_no}/fix-ai" in gated
    assert "/books/{book_id}/chapters/{chapter_no}/approve" not in gated


def test_require_desktop_license_returns_license_expired(keypair, monkeypatch):
    _enable_desktop_mode(monkeypatch)
    _patch_expired_license(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        require_desktop_license()
    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "license_expired"


def test_execute_generation_job_fails_when_license_expired(keypair, monkeypatch):
    _enable_desktop_mode(monkeypatch)
    _patch_expired_license(monkeypatch)

    db = _session()
    user, book, ch = _book_with_chapter(db)
    job = GenerationJob(book_id=book.id, chapter_no=ch.chapter_no, job_type="draft", status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)

    asyncio.run(execute_generation_job(db, job.id))

    db.refresh(job)
    assert job.status == "failed"
    assert job.error


def test_approve_works_without_valid_desktop_license(keypair, monkeypatch):
    _enable_desktop_mode(monkeypatch)
    _patch_expired_license(monkeypatch)

    db = _session()
    user, book, ch = _book_with_chapter(db)

    with pytest.raises(HTTPException) as gate_exc:
        require_desktop_license()
    assert gate_exc.value.status_code == 403

    result = approve(book.id, 1, db, user)
    assert result.status == "approved"
    db.refresh(ch)
    assert ch.status == "approved"
