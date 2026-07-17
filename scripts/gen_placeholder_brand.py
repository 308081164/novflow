"""Generate minimal NovFlow brand PNGs when master assets are missing."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _png_rgba(w: int, h: int, pixels: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + pixels[y * w * 4 : (y + 1) * w * 4] for y in range(h))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def draw_icon(size: int = 256) -> bytes:
    px = bytearray(size * size * 4)
    margin = size * 0.06
    for y in range(size):
        for x in range(size):
            i = (y * size + x) * 4
            if x < margin or y < margin or x >= size - margin or y >= size - margin:
                px[i : i + 4] = b"\x00\x00\x00\x00"
                continue
            r, g, b = 11, 27, 58
            t = (x + y) / (2 * size)
            if 0.35 < t < 0.55:
                r, g, b = 34, 211, 238
            elif 0.55 <= t < 0.62:
                r, g, b = 245, 197, 66
            if size * 0.55 < x < size * 0.72 and size * 0.55 < y < size * 0.78:
                if (x - size * 0.55) > (y - size * 0.55) * 0.4:
                    r, g, b = 248, 250, 252
            px[i] = r
            px[i + 1] = g
            px[i + 2] = b
            px[i + 3] = 255
    return bytes(px)


def draw_logo(w: int = 512, h: int = 160) -> bytes:
    px = bytearray(w * h * 4)
    icon = draw_icon(128)
    for y in range(h):
        for x in range(w):
            i = (y * w + x) * 4
            px[i : i + 4] = bytes((11, 27, 58, 255))
    ox, oy = 16, (h - 128) // 2
    for y in range(128):
        for x in range(128):
            si = (y * 128 + x) * 4
            if icon[si + 3] == 0:
                continue
            di = ((oy + y) * w + (ox + x)) * 4
            px[di : di + 4] = icon[si : si + 4]
    for y in range(h // 2 - 10, h // 2 + 10):
        for x in range(160, 480):
            i = (y * w + x) * 4
            px[i : i + 4] = bytes((248, 250, 252, 255))
    for y in range(h // 2 + 18, h // 2 + 28):
        for x in range(160, 360):
            i = (y * w + x) * 4
            px[i : i + 4] = bytes((34, 211, 238, 200))
    return bytes(px)


def _write_png_ico(path: Path, png: bytes, size: int = 32) -> None:
    data = struct.pack("<HHH", 0, 1, 1)
    data += struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(png), 22)
    data += png
    path.write_bytes(data)


def main() -> None:
    public = ROOT / "frontend" / "public"
    public.mkdir(parents=True, exist_ok=True)
    brand = ROOT / "assets" / "brand"
    brand.mkdir(parents=True, exist_ok=True)
    electron = ROOT / "desktop" / "electron"
    electron.mkdir(parents=True, exist_ok=True)

    icon256 = _png_rgba(256, 256, draw_icon(256))
    icon32 = _png_rgba(32, 32, draw_icon(32))
    logo = _png_rgba(512, 160, draw_logo())

    targets = [
        (public / "icon.png", icon256),
        (public / "logo.png", logo),
        (public / "favicon.png", icon32),
        (brand / "icon.png", icon256),
        (brand / "logo.png", logo),
        (electron / "icon.png", icon256),
        (electron / "logo.png", logo),
    ]
    for path, data in targets:
        path.write_bytes(data)
        print(f"wrote {path.relative_to(ROOT)} ({len(data)} bytes)")

    _write_png_ico(public / "favicon.ico", icon32)
    _write_png_ico(electron / "icon.ico", icon32)
    print("wrote favicon.ico / icon.ico")


if __name__ == "__main__":
    main()
