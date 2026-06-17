#!/usr/bin/env python3
"""Generate a polished 1024x1024 macOS app icon for intraday-x."""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter

SIZE = 1024
RADIUS = int(SIZE * 0.22)

# Palette
BG_TOP = (15, 23, 42)      # slate-900
BG_BOTTOM = (30, 41, 59)   # slate-800
ACCENT_BULL = (34, 197, 94)   # green-500
ACCENT_BEAR = (239, 68, 68)   # red-500
WHITE = (255, 255, 255)
GLOW = (56, 189, 248)         # sky-400


def gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    base = Image.new("RGB", (size, size), top)
    draw = ImageDraw.Draw(base)
    for y in range(size):
        t = y / (size - 1)
        r = int(top[0] * (1 - t) + bottom[0] * t)
        g = int(top[1] * (1 - t) + bottom[1] * t)
        b = int(top[2] * (1 - t) + bottom[2] * t)
        draw.line([(0, y), (size, y)], fill=(r, g, b))
    return base


def rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size, size), radius=radius, fill=255)
    return mask


def draw_candle(draw: ImageDraw.ImageDraw, x: int, y: int, body_w: int, body_h: int, wick_h: int, color: tuple[int, int, int]) -> None:
    top = y - wick_h
    bottom = y + body_h + wick_h
    draw.line([(x, top), (x, bottom)], fill=(255, 255, 255), width=8)
    draw.rounded_rectangle(
        [x - body_w // 2, y, x + body_w // 2, y + body_h],
        radius=8,
        fill=color,
    )


def main() -> None:
    # Transparent base
    icon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))

    # Background with gradient, masked to rounded rect
    bg = gradient(SIZE, BG_TOP, BG_BOTTOM)
    mask = rounded_mask(SIZE, RADIUS)
    icon.paste(bg, (0, 0), mask)

    draw = ImageDraw.Draw(icon)

    # Subtle inner rim highlight
    rim = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    rim_draw = ImageDraw.Draw(rim)
    rim_draw.rounded_rectangle((8, 8, SIZE - 8, SIZE - 8), radius=RADIUS - 4, outline=(*WHITE, 40), width=4)
    icon = Image.alpha_composite(icon, rim)
    draw = ImageDraw.Draw(icon)

    # Center symbol area
    cx, cy = SIZE // 2, SIZE // 2

    # Soft glow circle behind the X
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse(
        [cx - 290, cy - 290, cx + 290, cy + 290],
        fill=(*GLOW, 25),
    )
    icon = Image.alpha_composite(icon, glow)
    draw = ImageDraw.Draw(icon)

    # Stylized "X" made of two thick diagonal bars
    bar_width = 110
    margin = 170
    # Bar 1: top-left to bottom-right
    draw.polygon(
        [
            (margin, margin - bar_width // 2),
            (margin + bar_width, margin),
            (SIZE - margin, SIZE - margin + bar_width // 2),
            (SIZE - margin - bar_width, SIZE - margin),
        ],
        fill=WHITE,
    )
    # Bar 2: top-right to bottom-left
    draw.polygon(
        [
            (SIZE - margin, margin - bar_width // 2),
            (SIZE - margin + bar_width, margin),
            (margin, SIZE - margin + bar_width // 2),
            (margin - bar_width, SIZE - margin),
        ],
        fill=WHITE,
    )

    # Candlestick crossing the center: body sits in the intersection
    body_w = 72
    body_h = 180
    wick_h = 120
    draw_candle(draw, cx, cy - body_h // 2, body_w, body_h, wick_h, ACCENT_BULL)

    # Tiny bearish candle to the upper-right for visual balance
    draw_candle(draw, cx + 210, cy - 130, 50, 120, 70, ACCENT_BEAR)

    # Save master (clean, no extra shadow — macOS composes its own)
    out_path = "src-tauri/icons/icon.png"
    icon.save(out_path, "PNG")
    print(f"Saved {out_path} ({SIZE}x{SIZE})")


if __name__ == "__main__":
    main()
