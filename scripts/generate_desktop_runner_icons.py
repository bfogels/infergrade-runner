#!/usr/bin/env python3
"""Generate desktop Runner app icons from a small brand-native badge."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "apps" / "desktop-runner" / "src-tauri" / "icons"


def _font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/SFNS.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    _rounded_rectangle(draw, (0, 0, size, size), radius=radius, fill=255)
    return mask


def _rounded_rectangle(draw: ImageDraw.ImageDraw, box, radius: int, fill, outline=None, width: int = 1) -> None:
    x0, y0, x1, y1 = box
    radius = max(0, min(radius, int((x1 - x0) / 2), int((y1 - y0) / 2)))
    draw.rectangle((x0 + radius, y0, x1 - radius, y1), fill=fill)
    draw.rectangle((x0, y0 + radius, x1, y1 - radius), fill=fill)
    draw.pieslice((x0, y0, x0 + 2 * radius, y0 + 2 * radius), 180, 270, fill=fill)
    draw.pieslice((x1 - 2 * radius, y0, x1, y0 + 2 * radius), 270, 360, fill=fill)
    draw.pieslice((x1 - 2 * radius, y1 - 2 * radius, x1, y1), 0, 90, fill=fill)
    draw.pieslice((x0, y1 - 2 * radius, x0 + 2 * radius, y1), 90, 180, fill=fill)
    if outline:
        for offset in range(width):
            inner = (x0 + offset, y0 + offset, x1 - offset, y1 - offset)
            _rounded_rectangle_outline(draw, inner, max(0, radius - offset), outline)


def _rounded_rectangle_outline(draw: ImageDraw.ImageDraw, box, radius: int, fill) -> None:
    x0, y0, x1, y1 = box
    draw.line((x0 + radius, y0, x1 - radius, y0), fill=fill)
    draw.line((x0 + radius, y1, x1 - radius, y1), fill=fill)
    draw.line((x0, y0 + radius, x0, y1 - radius), fill=fill)
    draw.line((x1, y0 + radius, x1, y1 - radius), fill=fill)
    draw.arc((x0, y0, x0 + 2 * radius, y0 + 2 * radius), 180, 270, fill=fill)
    draw.arc((x1 - 2 * radius, y0, x1, y0 + 2 * radius), 270, 360, fill=fill)
    draw.arc((x1 - 2 * radius, y1 - 2 * radius, x1, y1), 0, 90, fill=fill)
    draw.arc((x0, y1 - 2 * radius, x0 + 2 * radius, y1), 90, 180, fill=fill)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple:
    if hasattr(draw, "textbbox"):
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        return right - left, bottom - top
    return draw.textsize(text, font=font)


def _base_icon(size: int = 1024) -> Image.Image:
    scale = size / 1024.0
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    _rounded_rectangle(
        shadow_draw,
        tuple(int(v * scale) for v in (78, 88, 946, 956)),
        radius=int(196 * scale),
        fill=(23, 31, 38, 110),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(int(24 * scale)))
    canvas.alpha_composite(shadow)

    body = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    body_draw = ImageDraw.Draw(body)
    _rounded_rectangle(
        body_draw,
        tuple(int(v * scale) for v in (82, 76, 942, 936)),
        radius=int(190 * scale),
        fill=(18, 27, 33, 255),
        outline=(122, 220, 205, 120),
        width=max(1, int(9 * scale)),
    )

    grid = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    grid_draw = ImageDraw.Draw(grid)
    for x in range(160, 901, 124):
        grid_draw.line(
            [(int(x * scale), int(166 * scale)), (int(x * scale), int(846 * scale))],
            fill=(255, 255, 255, 14),
            width=max(1, int(2 * scale)),
        )
    for y in range(204, 821, 104):
        grid_draw.line(
            [(int(156 * scale), int(y * scale)), (int(868 * scale), int(y * scale))],
            fill=(255, 255, 255, 14),
            width=max(1, int(2 * scale)),
        )
    body.alpha_composite(grid)

    draw = ImageDraw.Draw(body)
    frontier = [(228, 668), (360, 548), (510, 470), (660, 384), (802, 290)]
    frontier = [(int(x * scale), int(y * scale)) for x, y in frontier]
    draw.line(frontier, fill=(125, 214, 201, 255), width=max(4, int(18 * scale)))
    for index, (x, y) in enumerate(frontier):
        radius = int((28 if index in (0, 4) else 22) * scale)
        fill = (246, 185, 96, 255) if index == 4 else (125, 214, 201, 255)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            outline=(255, 255, 255, 230),
            width=max(1, int(5 * scale)),
        )

    monogram_font = _font(int(250 * scale))
    text = "IG"
    text_w, text_h = _text_size(draw, text, monogram_font)
    text_x = int((size - text_w) / 2)
    text_y = int(522 * scale - text_h / 2)
    draw.text((text_x + int(6 * scale), text_y + int(8 * scale)), text, font=monogram_font, fill=(0, 0, 0, 90))
    draw.text((text_x, text_y), text, font=monogram_font, fill=(245, 248, 245, 255))

    highlight = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    highlight_draw = ImageDraw.Draw(highlight)
    _rounded_rectangle(
        highlight_draw,
        tuple(int(v * scale) for v in (140, 126, 884, 446)),
        radius=int(130 * scale),
        fill=(255, 255, 255, 18),
    )
    body.alpha_composite(highlight)

    mask = _rounded_mask(size, int(190 * scale))
    clipped = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    clipped.paste(body, (0, 0), mask)
    canvas.alpha_composite(clipped)
    return canvas


def _save_pngs(icon: Image.Image) -> None:
    sizes = {
        "32x32.png": 32,
        "128x128.png": 128,
        "128x128@2x.png": 256,
        "icon.png": 1024,
    }
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    for name, size in sizes.items():
        resized = icon.resize((size, size), Image.LANCZOS)
        resized.save(ICON_DIR / name)


def _save_icns(icon: Image.Image) -> None:
    iconset = ICON_DIR / "icon.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir()
    sizes = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]
    for size, name in sizes:
        icon.resize((size, size), Image.LANCZOS).save(iconset / name)
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(ICON_DIR / "icon.icns")], check=True)
    shutil.rmtree(iconset)


def _save_ico(icon: Image.Image) -> None:
    icon.save(ICON_DIR / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (128, 128), (256, 256)])


def main() -> int:
    icon = _base_icon()
    _save_pngs(icon)
    _save_icns(icon)
    _save_ico(icon)
    print("desktop_runner_icons=%s" % ICON_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
