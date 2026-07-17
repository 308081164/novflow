from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .license_keys import EMBEDDED_ISSUER_PUBLIC_KEY_HEX
from .products import ProductProfile

K_REQ = bytes.fromhex("6e6f76666c6f772d61637469766174696f6e2d6b65792d7631")  # novflow-activation-key-v1
DEVICE_CODE_LENGTH = 28
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def resolve_data_root() -> Path:
    env = os.environ.get("NOVFLOW_DATA_DIR", "").strip()
    if env:
        return Path(env).resolve()
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return (base / "NovFlow" / "data").resolve()


def license_file_path(profile: ProductProfile) -> Path:
    return resolve_data_root() / "config" / profile.license_basename


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def resolve_issuer_public_key() -> bytes | None:
    env_hex = os.environ.get("NOVFLOW_PUBKEY", "").strip()
    hex_str = env_hex or EMBEDDED_ISSUER_PUBLIC_KEY_HEX
    try:
        buf = bytes.fromhex(hex_str)
        return buf if len(buf) >= 16 else None
    except ValueError:
        return None


def resolve_private_key_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    import sys

    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        bundle = Path(getattr(sys, "_MEIPASS", ""))
        if str(bundle):
            candidates.append(bundle / ".issuer-private.der")
        candidates.append(Path(sys.executable).resolve().parent / ".issuer-private.der")
    repo_root = Path(__file__).resolve().parents[2]
    candidates.append(repo_root / "tools" / ".issuer-private.der")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "未找到发行方私钥 .issuer-private.der。"
        "请将私钥放在 tools/ 目录或管理员工具同目录。"
    )


def load_issuer_private_key(path: Path | None = None) -> Ed25519PrivateKey:
    key_path = resolve_private_key_path(path)
    data = key_path.read_bytes()
    key = serialization.load_der_private_key(data, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("私钥须为 Ed25519")
    return key


def normalize_hw_id_input(raw: str) -> tuple[bool, str, str | None]:
    hw_id = re.sub(r"[^0-9a-f]", "", str(raw or "").strip().lower())
    if not hw_id:
        return False, "", "HW_ID 不能为空"
    if len(hw_id) == 16:
        return (
            False,
            "",
            "您输入的是 16 位短 HW_ID。请在客户端「授权激活」复制完整 64 位设备指纹。",
        )
    if len(hw_id) != 64:
        return False, "", f"HW_ID 须为 64 位十六进制字符（当前 {len(hw_id)} 位）"
    return True, hw_id, None


def _crockford_base32_encode(buf: bytes) -> str:
    bits = 0
    bit_count = 0
    result: list[str] = []
    for byte in buf:
        bits = (bits << 8) | byte
        bit_count += 8
        while bit_count >= 5:
            bit_count -= 5
            result.append(_CROCKFORD[(bits >> bit_count) & 0x1F])
    if bit_count > 0:
        result.append(_CROCKFORD[(bits << (5 - bit_count)) & 0x1F])
    return "".join(result)


def _luhn_mod32_check(text: str) -> str:
    mapping = {ch: i for i, ch in enumerate(_CROCKFORD)}
    total = 0
    double = False
    for ch in reversed(text):
        val = mapping.get(ch, 0)
        if double:
            val *= 2
            if val >= 32:
                val = val - 32 + 1
        total += val
        double = not double
    return _CROCKFORD[(32 - (total % 32)) % 32]


def generate_device_code(profile: ProductProfile, hw_id: str) -> str:
    digest = hmac.new(K_REQ, b"", hashlib.sha256)
    digest.update(hw_id.encode("utf-8"))
    digest.update(profile.product_id.encode("utf-8"))
    digest.update(profile.layout.encode("utf-8"))
    encoded = _crockford_base32_encode(digest.digest())[: DEVICE_CODE_LENGTH - 1]
    device_code = encoded + _luhn_mod32_check(encoded)
    return "-".join(device_code[i : i + 4] for i in range(0, len(device_code), 4))


def validate_device_code_format(code: str) -> tuple[bool, str | None]:
    clean = re.sub(r"[^0-9A-Z]", "", str(code or "").upper())
    if not clean:
        return False, "激活设备码不能为空"
    if len(clean) != DEVICE_CODE_LENGTH:
        return False, f"激活设备码长度不正确（期望 {DEVICE_CODE_LENGTH} 位，实际 {len(clean)} 位）"
    data, check = clean[:-1], clean[-1]
    if check != _luhn_mod32_check(data):
        return False, "激活设备码校验位不正确"
    return True, None


def verify_device_code(profile: ProductProfile, device_code: str, hw_id: str) -> bool:
    ok, _ = validate_device_code_format(device_code)
    if not ok:
        return False
    expected = generate_device_code(profile, hw_id)
    clean = re.sub(r"[^0-9A-Z]", "", device_code.upper())
    expected_clean = re.sub(r"[^0-9A-Z]", "", expected.upper())
    return clean == expected_clean


def parse_expiry_date(value: str | None) -> date | None:
    """Parse YYYY-MM-DD (or ISO datetime prefix) into a local calendar date."""
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            pass
    try:
        normalized = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        return dt.date()
    except ValueError:
        return None


def check_license_expiry(
    payload: dict[str, Any],
    *,
    reference: date | None = None,
) -> tuple[bool, str | None]:
    """Return (ok, error). Expiry day itself is still valid (inclusive end date)."""
    today = reference or date.today()
    mode = str(payload.get("license_mode") or "permanent")

    if mode == "time_limited":
        expiry = parse_expiry_date(str(payload.get("valid_until") or ""))
        if expiry is None:
            return False, "限时授权激活码缺少 valid_until"
        if today > expiry:
            return False, f"激活码已过期（有效期至 {expiry.isoformat()}）"

    valid_until = str(payload.get("valid_until") or "").strip()
    if valid_until and mode != "time_limited":
        expiry = parse_expiry_date(valid_until)
        if expiry is not None and today > expiry:
            return False, f"激活码已过期（有效期至 {expiry.isoformat()}）"

    if mode == "permanent":
        activate_before = str(payload.get("activate_before") or "").strip()
        if activate_before:
            deadline = parse_expiry_date(activate_before)
            if deadline is not None and today > deadline:
                return False, f"激活码已超过首激截止日期（{deadline.isoformat()}）"

    return True, None


def build_license_payload(
    profile: ProductProfile,
    *,
    hw_id: str,
    license_mode: str = "permanent",
    issued_at: str | None = None,
    activate_before: str | None = None,
    valid_until: str | None = None,
    tier: str = "full",
    batch_id: str = "",
    customer_ref: str = "",
) -> str:
    payload: dict[str, Any] = {
        "product_id": profile.product_id,
        "layout": profile.layout,
        "hw_id": hw_id,
        "license_mode": license_mode,
        "tier": tier,
        "issued_at": issued_at or date.today().isoformat(),
    }
    if license_mode == "permanent" and activate_before:
        payload["activate_before"] = activate_before
    if license_mode == "time_limited":
        expiry = parse_expiry_date(valid_until)
        if expiry is None:
            raise ValueError("time_limited 授权必须提供有效 valid_until（YYYY-MM-DD）")
        payload["valid_until"] = expiry.isoformat()
    if batch_id:
        payload["batch_id"] = batch_id
    if customer_ref:
        payload["customer_ref"] = customer_ref
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def parse_license_code(license_code: str) -> dict[str, Any]:
    code = str(license_code or "").strip()
    if not code:
        return {"ok": False, "error": "激活码不能为空"}
    parts = code.split(".")
    if len(parts) != 3:
        return {"ok": False, "error": "激活码格式不正确（应为 v1.Payload.Signature）"}
    version, payload_b64, sig_b64 = parts
    if version != "v1":
        return {"ok": False, "error": f"不支持的激活码版本: {version}"}
    try:
        payload_json = _b64url_decode(payload_b64).decode("utf-8")
        payload = json.loads(payload_json)
        signature = _b64url_decode(sig_b64)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"ok": False, "error": f"激活码解析失败: {exc}"}
    return {
        "ok": True,
        "payload": payload,
        "payload_json": payload_json,
        "signature": signature,
    }


def verify_license_signature(parsed: dict[str, Any], public_key_bytes: bytes) -> tuple[bool, str | None]:
    if not parsed.get("ok"):
        return False, "无效的激活码解析结果"
    try:
        public_key = serialization.load_der_public_key(public_key_bytes)
        if not isinstance(public_key, Ed25519PublicKey):
            return False, "公钥类型不正确"
        public_key.verify(parsed["signature"], parsed["payload_json"].encode("utf-8"))
        return True, None
    except Exception as exc:
        return False, f"激活码签名验证失败: {exc}"


def validate_license_code(
    profile: ProductProfile,
    license_code: str,
    hw_id: str,
    public_key_bytes: bytes | None = None,
) -> dict[str, Any]:
    parsed = parse_license_code(license_code)
    if not parsed.get("ok"):
        return {"ok": False, "error": parsed.get("error", "解析失败")}

    payload = parsed["payload"]
    if payload.get("product_id") != profile.product_id:
        return {"ok": False, "error": "激活码产品不匹配"}
    if payload.get("hw_id") != hw_id:
        return {"ok": False, "error": "激活码与当前设备不匹配"}

    pub = public_key_bytes or resolve_issuer_public_key()
    if not pub:
        return {"ok": False, "error": "客户端缺少发行方公钥，无法接受激活码"}
    valid, err = verify_license_signature(parsed, pub)
    if not valid:
        return {"ok": False, "error": err}

    ok, err = check_license_expiry(payload)
    if not ok:
        return {"ok": False, "error": err}

    mode = payload.get("license_mode", "permanent")
    return {"ok": True, "license_mode": mode, "payload": payload}


def read_license(profile: ProductProfile) -> dict[str, Any] | None:
    path = license_file_path(profile)
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return None


def write_license(profile: ProductProfile, data: dict[str, Any]) -> None:
    path = license_file_path(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def check_license_status(
    profile: ProductProfile,
    hw_id: str,
    public_key_bytes: bytes | None = None,
) -> dict[str, Any]:
    license_data = read_license(profile)
    if not license_data:
        return {"activated": False, "error": "未激活"}
    if license_data.get("deactivated") is True:
        return {"activated": False, "error": "授权已卸载", "payload": license_data}

    pub = public_key_bytes or resolve_issuer_public_key()
    if not pub or not hw_id:
        return {"activated": False, "error": "无法校验授权状态（缺少校验上下文）", "payload": license_data}

    stored_code = str(license_data.get("license_code", "")).strip()
    if not stored_code:
        return {
            "activated": False,
            "error": "许可证缺少签名字段，请重新输入激活码",
            "payload": license_data,
        }

    result = validate_license_code(profile, stored_code, hw_id, pub)
    if not result.get("ok"):
        return {
            "activated": False,
            "error": f"许可证无效或已被篡改：{result.get('error')}",
            "payload": license_data,
        }

    payload = result.get("payload") or {}
    mode = payload.get("license_mode", license_data.get("license_mode", "permanent"))
    ok, err = check_license_expiry(payload)
    if not ok:
        return {
            "activated": False,
            "license_mode": mode,
            "error": err.replace("激活码", "许可证"),
            "payload": license_data,
        }

    valid_until = payload.get("valid_until") or license_data.get("valid_until")
    expiry = parse_expiry_date(str(valid_until or ""))
    status: dict[str, Any] = {
        "activated": True,
        "license_mode": mode,
        "payload": license_data,
    }
    if expiry is not None:
        status["valid_until"] = expiry.isoformat()
    return status


def activate_license(profile: ProductProfile, license_code: str, hw_id: str) -> dict[str, Any]:
    pub = resolve_issuer_public_key()
    result = validate_license_code(profile, license_code, hw_id, pub)
    if not result.get("ok"):
        return result

    payload = result["payload"]
    write_license(
        profile,
        {
            "license_code": license_code.strip(),
            "license_mode": payload.get("license_mode", "permanent"),
            "activated_at": datetime.now().isoformat(),
            "hw_id": hw_id,
            "valid_until": payload.get("valid_until"),
            "product_id": profile.product_id,
        },
    )
    return {"ok": True, "license_mode": payload.get("license_mode", "permanent")}


def deactivate_license(profile: ProductProfile) -> None:
    data = read_license(profile) or {}
    data["deactivated"] = True
    data["deactivated_at"] = datetime.now().isoformat()
    write_license(profile, data)


def generate_license_code(profile: ProductProfile, payload: dict[str, Any], private_key: Ed25519PrivateKey) -> str:
    payload_json = build_license_payload(profile, **payload)
    signature = private_key.sign(payload_json.encode("utf-8"))
    return f"v1.{_b64url_encode(payload_json.encode('utf-8'))}.{_b64url_encode(signature)}"


def generate_key_pair() -> tuple[bytes, bytes]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    private_der = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return public_der, private_der
