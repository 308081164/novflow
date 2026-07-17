"""许可证过期校验测试。"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from shared.license.license_common import (  # noqa: E402
    _b64url_encode,
    activate_license,
    build_license_payload,
    check_license_status,
    generate_key_pair,
    generate_license_code,
    parse_expiry_date,
    validate_license_code,
    write_license,
)
from shared.license.products import DESKTOP  # noqa: E402


HW_ID = "a" * 64
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
TOMORROW = (date.today() + timedelta(days=1)).isoformat()


@pytest.fixture()
def keypair(monkeypatch, tmp_path):
    public_der, private_der = generate_key_pair()
    monkeypatch.setenv("NOVFLOW_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NOVFLOW_PUBKEY", public_der.hex())
    private_path = tmp_path / "issuer-private.der"
    private_path.write_bytes(private_der)
    return public_der, private_path


def _signed_code(private_path: Path, *, mode: str, valid_until: str | None = None) -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_key = serialization.load_der_private_key(private_path.read_bytes(), password=None)
    assert isinstance(private_key, Ed25519PrivateKey)
    payload = {
        "hw_id": HW_ID,
        "license_mode": mode,
        "valid_until": valid_until,
    }
    return generate_license_code(DESKTOP, payload, private_key)


def test_parse_expiry_date_accepts_iso_date():
    assert parse_expiry_date("2026-12-31") == date(2026, 12, 31)
    assert parse_expiry_date("2026-12-31T23:59:59Z") == date(2026, 12, 31)


def test_expired_time_limited_license_rejected_on_validate(keypair):
    public_der, private_path = keypair
    code = _signed_code(private_path, mode="time_limited", valid_until=YESTERDAY)
    result = validate_license_code(DESKTOP, code, HW_ID, public_der)
    assert result["ok"] is False
    assert "过期" in result["error"]


def test_future_time_limited_license_accepted_on_validate(keypair):
    public_der, private_path = keypair
    code = _signed_code(private_path, mode="time_limited", valid_until=TOMORROW)
    result = validate_license_code(DESKTOP, code, HW_ID, public_der)
    assert result["ok"] is True
    assert result["license_mode"] == "time_limited"


def _store_license(private_path: Path, *, mode: str, valid_until: str) -> str:
    code = _signed_code(private_path, mode=mode, valid_until=valid_until)
    write_license(
        DESKTOP,
        {
            "license_code": code,
            "license_mode": mode,
            "activated_at": date.today().isoformat(),
            "hw_id": HW_ID,
            "valid_until": valid_until,
            "product_id": DESKTOP.product_id,
        },
    )
    return code


def test_expired_license_blocks_check_license_status(keypair):
    public_der, private_path = keypair
    _store_license(private_path, mode="time_limited", valid_until=YESTERDAY)
    st = check_license_status(DESKTOP, HW_ID, public_der)
    assert st["activated"] is False
    assert "过期" in st["error"]


def test_active_license_passes_check_license_status(keypair):
    public_der, private_path = keypair
    code = _signed_code(private_path, mode="time_limited", valid_until=TOMORROW)
    activate_license(DESKTOP, code, HW_ID)
    st = check_license_status(DESKTOP, HW_ID, public_der)
    assert st["activated"] is True
    assert st["valid_until"] == TOMORROW


def test_misissued_permanent_payload_with_valid_until_still_expires(keypair):
    """Defense: valid_until in signed payload is always enforced."""
    public_der, private_path = keypair
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_key = serialization.load_der_private_key(private_path.read_bytes(), password=None)
    assert isinstance(private_key, Ed25519PrivateKey)
    payload_json = json.dumps(
        {
            "product_id": DESKTOP.product_id,
            "layout": DESKTOP.layout,
            "hw_id": HW_ID,
            "license_mode": "permanent",
            "tier": "full",
            "issued_at": date.today().isoformat(),
            "valid_until": YESTERDAY,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    signature = private_key.sign(payload_json.encode("utf-8"))
    code = f"v1.{_b64url_encode(payload_json.encode('utf-8'))}.{_b64url_encode(signature)}"
    result = validate_license_code(DESKTOP, code, HW_ID, public_der)
    assert result["ok"] is False
    assert "过期" in result["error"]


def test_build_license_payload_requires_valid_until_for_time_limited():
    with pytest.raises(ValueError, match="valid_until"):
        build_license_payload(DESKTOP, hw_id=HW_ID, license_mode="time_limited")


def test_deps_license_blocks_expired_desktop_license(keypair, monkeypatch):
    public_der, private_path = keypair
    monkeypatch.setenv("NOVFLOW_DESKTOP", "1")
    _store_license(private_path, mode="time_limited", valid_until=YESTERDAY)

    backend_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend_root))
    from fastapi import HTTPException

    from app.deps_license import require_desktop_license

    with pytest.raises(HTTPException) as exc:
        require_desktop_license()
    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "license_expired"


def test_deps_license_skipped_in_non_desktop_mode(monkeypatch):
    monkeypatch.delenv("NOVFLOW_DESKTOP", raising=False)
    backend_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend_root))
    from app.deps_license import require_desktop_license

    require_desktop_license()
