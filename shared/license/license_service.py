from __future__ import annotations

from .hardware_id import collect_device_info, generate_hw_id, short_hw_id
from .license_common import (
    activate_license,
    check_license_status,
    deactivate_license,
    generate_device_code,
    read_license,
    resolve_issuer_public_key,
)
from .products import ProductProfile


class LicenseService:
    def __init__(self, profile: ProductProfile) -> None:
        self.profile = profile
        self._hw_id: str | None = None

    @property
    def hw_id(self) -> str:
        if self._hw_id is None:
            self._hw_id = generate_hw_id(self.profile, collect_device_info())
        return self._hw_id

    def device_info(self) -> dict[str, str | object]:
        info = collect_device_info()
        hw_id = self.hw_id
        return {
            "hw_id": hw_id,
            "short_hw_id": short_hw_id(hw_id),
            "device_code": generate_device_code(self.profile, hw_id),
            "product_id": self.profile.product_id,
            "product_name": self.profile.display_name,
            "collected": info,
        }

    def status(self) -> dict[str, object]:
        pub = resolve_issuer_public_key()
        if not pub:
            return {"activated": False, "error": "未配置发行方公钥"}
        st = check_license_status(self.profile, self.hw_id, pub)
        st["hw_id"] = self.hw_id
        st["short_hw_id"] = short_hw_id(self.hw_id)
        st["product_id"] = self.profile.product_id
        st["product_name"] = self.profile.display_name
        return st

    def activate(self, license_code: str) -> dict[str, object]:
        return activate_license(self.profile, license_code.strip(), self.hw_id)

    def deactivate(self) -> None:
        deactivate_license(self.profile)

    def is_activated(self) -> bool:
        return bool(self.status().get("activated"))

    def status_label(self) -> str:
        st = self.status()
        name = self.profile.display_name
        if st.get("activated"):
            mode = st.get("license_mode", "permanent")
            valid_until = st.get("valid_until")
            if valid_until:
                return f"{name}：已激活（有效期至 {valid_until}）"
            if mode == "permanent":
                return f"{name}：已激活"
            return f"{name}：已激活（{mode}）"
        return f"{name}：未激活"
