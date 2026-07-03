from __future__ import annotations

import hashlib
import re
import subprocess
import uuid
from typing import Any

from .products import ProductProfile

HW_SALT = b"NOVFLOW-LICENSE-v1"


def _run(cmd: str | list[str], timeout: float = 3.0) -> str:
    try:
        if isinstance(cmd, str):
            out = subprocess.check_output(
                cmd,
                shell=True,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            out = subprocess.check_output(
                cmd,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        return out.decode("utf-8", errors="ignore")
    except (subprocess.SubprocessError, OSError, UnicodeDecodeError):
        return ""


def collect_device_info() -> dict[str, str]:
    info: dict[str, str] = {}

    reg_out = _run('reg query "HKLM\\SOFTWARE\\Microsoft\\Cryptography" /v MachineGuid')
    m = re.search(r"MachineGuid\s+REG_SZ\s+(\S+)", reg_out, re.I)
    if m:
        info["machineGuid"] = m.group(1).strip()

    vol_out = _run("vol C:")
    m = re.search(r"序列号\s+(\S+)", vol_out) or re.search(r"Serial Number\s+(\S+)", vol_out, re.I)
    if m:
        info["diskSerial"] = m.group(1).strip()

    mac_out = _run('wmic nic where "NetEnabled=true and AdapterTypeId=0" get MACAddress')
    macs = [
        line.strip()
        for line in mac_out.splitlines()
        if line.strip() and "MACAddress" not in line and line.strip() != "-"
    ]
    if macs:
        info["macAddress"] = macs[0]
    else:
        node = uuid.getnode()
        if (node >> 40) % 2 == 0:
            info["macAddress"] = ":".join(f"{(node >> shift) & 0xFF:02x}" for shift in range(40, -1, -8))

    return info


def generate_hw_id(profile: ProductProfile, options: dict[str, Any] | None = None) -> str:
    opts = options or collect_device_info()
    parts = [
        profile.product_id,
        profile.layout,
        str(opts.get("machineGuid", "")).strip().lower(),
        str(opts.get("cpuId", "")).strip().lower(),
        str(opts.get("diskSerial", "")).strip().upper(),
        re.sub(r"[^0-9a-f]", "", str(opts.get("macAddress", "")).strip().lower()),
    ]
    payload = "|".join(parts)
    return hashlib.sha256(HW_SALT + payload.encode("utf-8")).hexdigest()


def short_hw_id(hw_id: str) -> str:
    return hw_id[:16].upper() if hw_id else ""
