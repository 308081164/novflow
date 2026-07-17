#!/usr/bin/env python3
"""NovFlow 激活码 CLI（管理员签发 / 验证 / 设备码）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.license.license_common import (  # noqa: E402
    build_license_payload,
    generate_device_code,
    generate_license_code,
    load_issuer_private_key,
    normalize_hw_id_input,
    validate_license_code,
)
from shared.license.products import ALL_PRODUCTS, DESKTOP, IMAGE_DLC, ProductProfile


def _profile(name: str) -> ProductProfile:
    mapping = {p.product_id: p for p in ALL_PRODUCTS}
    aliases = {
        "desktop": DESKTOP,
        "dlc": IMAGE_DLC,
        "image": IMAGE_DLC,
    }
    if name in mapping:
        return mapping[name]
    if name in aliases:
        return aliases[name]
    raise SystemExit(f"未知产品: {name}（可选: {', '.join(mapping)} 或 desktop/dlc）")


def cmd_generate(args: argparse.Namespace) -> None:
    profile = _profile(args.product)
    ok, hw_id, err = normalize_hw_id_input(args.hw_id)
    if not ok:
        raise SystemExit(err)
    mode = args.mode
    if args.valid_until and mode == "permanent":
        mode = "time_limited"
        print("提示: 已指定 --valid-until，自动使用 time_limited 模式", file=sys.stderr)
    if mode == "time_limited" and not args.valid_until:
        raise SystemExit("限时授权必须指定 --valid-until（格式 YYYY-MM-DD）")
    private_key = load_issuer_private_key(Path(args.private_key) if args.private_key else None)
    payload = {
        "hw_id": hw_id,
        "license_mode": mode,
        "valid_until": args.valid_until,
        "activate_before": args.activate_before,
        "batch_id": args.batch or "",
        "customer_ref": args.customer or "",
    }
    code = generate_license_code(profile, payload, private_key)
    dc = generate_device_code(profile, hw_id)
    print(f"产品: {profile.display_name} ({profile.product_id})")
    print(f"HW_ID: {hw_id}")
    print(f"设备码: {dc}")
    print(f"授权: {mode}")
    print()
    print("激活码:")
    print(code)


def cmd_verify(args: argparse.Namespace) -> None:
    profile = _profile(args.product)
    ok, hw_id, err = normalize_hw_id_input(args.hw_id)
    if not ok:
        raise SystemExit(err)
    result = validate_license_code(profile, args.code, hw_id)
    if result.get("ok"):
        print("验证通过:", result.get("license_mode"))
    else:
        raise SystemExit(result.get("error", "验证失败"))


def cmd_device_code(args: argparse.Namespace) -> None:
    profile = _profile(args.product)
    ok, hw_id, err = normalize_hw_id_input(args.hw_id)
    if not ok:
        raise SystemExit(err)
    print(generate_device_code(profile, hw_id))


def main() -> None:
    parser = argparse.ArgumentParser(description="NovFlow 激活码管理 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_gen = sub.add_parser("generate", help="签发激活码")
    p_gen.add_argument("--product", default="novflow_desktop", help="产品 ID 或 desktop/dlc")
    p_gen.add_argument("--hw-id", required=True)
    p_gen.add_argument("--mode", choices=["permanent", "time_limited"], default="permanent")
    p_gen.add_argument("--valid-until", dest="valid_until", default=None)
    p_gen.add_argument("--activate-before", dest="activate_before", default=None)
    p_gen.add_argument("--batch", default="")
    p_gen.add_argument("--customer", default="")
    p_gen.add_argument("--private-key", default=None)
    p_gen.set_defaults(func=cmd_generate)

    p_ver = sub.add_parser("verify", help="验证激活码")
    p_ver.add_argument("--product", default="novflow_desktop")
    p_ver.add_argument("--hw-id", required=True)
    p_ver.add_argument("--code", required=True)
    p_ver.set_defaults(func=cmd_verify)

    p_dc = sub.add_parser("device-code", help="生成设备码")
    p_dc.add_argument("--product", default="novflow_desktop")
    p_dc.add_argument("--hw-id", required=True)
    p_dc.set_defaults(func=cmd_device_code)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
