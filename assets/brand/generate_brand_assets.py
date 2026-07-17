"""Generate NovFlow brand assets from the official horizontal logo reference."""
from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
BRAND = Path(__file__).resolve().parent
REF = Path(
    r"C:\Users\yangx\.cursor\projects\d-Hui-Files-MyProjects-AI-nov\assets"
    r"\c__Users_yangx_AppData_Roaming_Cursor_User_workspaceStorage_empty-window_images"
    r"_image-8b006916-eb12-4631-b7c6-e09d0d5bf5cd.png"
)

ICON_SIZES = (16, 32, 48, 64, 128, 256, 512)
# Windows ICO traditionally caps at 256; 512 remains as PNG only.
ICO_SIZES = (16, 32, 48, 64, 128, 256)
MASTER_ICON_SIZE = 1024
# Left rounded-square icon region in the 1024x682 reference (includes glow).
ICON_CROP = (8, 152, 328, 472)  # left, top, right, bottom — 320x320


def crop_icon(logo: Image.Image) -> Image.Image:
    icon = logo.crop(ICON_CROP)
    # Ensure exact square
    w, h = icon.size
    side = max(w, h)
    if w != h:
        canvas = Image.new("RGBA", (side, side), (1, 16, 49, 255))
        canvas.paste(icon.convert("RGBA"), ((side - w) // 2, (side - h) // 2))
        icon = canvas
    return icon.convert("RGBA")


def resize_icon(icon: Image.Image, size: int) -> Image.Image:
    return icon.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    if not REF.is_file():
        raise SystemExit(f"Reference logo not found: {REF}")

    BRAND.mkdir(parents=True, exist_ok=True)
    logo = Image.open(REF).convert("RGBA")
    logo_path = BRAND / "logo.png"
    logo.save(logo_path, format="PNG", optimize=True)
    print(f"logo.png {logo.size}")

    icon_src = crop_icon(logo)
    master = resize_icon(icon_src, MASTER_ICON_SIZE)
    master_path = BRAND / "icon.png"
    master.save(master_path, format="PNG", optimize=True)
    print(f"icon.png {master.size}")

    sized_dir = BRAND / "icons"
    sized_dir.mkdir(exist_ok=True)
    for size in ICON_SIZES:
        img = resize_icon(icon_src, size)
        out = sized_dir / f"icon-{size}.png"
        img.save(out, format="PNG", optimize=True)
        print(f"  icons/icon-{size}.png")

    # Multi-size ICO (Windows taskbar / installer / Electron).
    # Pillow resizes the source into each entry listed in `sizes`.
    ico_path = BRAND / "icon.ico"
    master.save(ico_path, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    print(f"icon.ico sizes={list(ICO_SIZES)}")

    # Sync copies
    copies = [
        (ROOT / "frontend" / "public" / "favicon.png", resize_icon(icon_src, 32)),
        (ROOT / "frontend" / "public" / "favicon.ico", None),  # copy ico
        (ROOT / "frontend" / "public" / "icon.png", master),
        (ROOT / "frontend" / "public" / "logo.png", logo),
        (ROOT / "desktop" / "electron" / "icon.png", master),
        (ROOT / "desktop" / "electron" / "icon.ico", None),
        (ROOT / "desktop" / "electron" / "logo.png", logo),
    ]
    for dest, img in copies:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if img is None:
            shutil.copy2(ico_path, dest)
            print(f"copy {dest.relative_to(ROOT)}")
        else:
            img.save(dest, format="PNG", optimize=True)
            print(f"write {dest.relative_to(ROOT)} {img.size}")

    # favicon.ico for browsers that prefer .ico
    shutil.copy2(ico_path, ROOT / "frontend" / "public" / "favicon.ico")
    print("done")


if __name__ == "__main__":
    main()
