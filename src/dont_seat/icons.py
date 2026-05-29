"""Procedurally drawn cat tray icons (Pillow)."""
from __future__ import annotations
from PIL import Image, ImageDraw

SIZE = 64  # internal draw size; pystray downscales for tray
BG = (255, 255, 255, 0)

CAT_FUR = (122, 98, 72, 255)
CAT_SHADOW = (89, 63, 38, 255)
CAT_MUZZLE = (202, 196, 180, 255)
CAT_STRIPE = (134, 116, 92, 255)
KEYBOARD = (216, 230, 234, 255)
OUTLINE = (30, 30, 30, 255)
ACCENT = (77, 231, 176, 255)


def _base(draw: ImageDraw.ImageDraw, paw_offset: int, eyes_open: bool) -> None:
    draw.ellipse((18, 30, 48, 58), fill=CAT_SHADOW, outline=OUTLINE, width=2)
    draw.polygon((16, 20, 22, 5, 30, 21), fill=CAT_FUR, outline=OUTLINE)
    draw.polygon((38, 21, 48, 5, 51, 23), fill=CAT_FUR, outline=OUTLINE)
    draw.polygon((21, 18, 23, 11, 27, 20), fill=CAT_MUZZLE)
    draw.polygon((41, 19, 46, 11, 47, 22), fill=CAT_MUZZLE)
    draw.ellipse((15, 16, 52, 49), fill=CAT_FUR, outline=OUTLINE, width=2)
    draw.arc((17, 10, 50, 32), start=180, end=360, fill=CAT_SHADOW, width=6)
    draw.line((28, 17, 25, 25), fill=CAT_STRIPE, width=2)
    draw.line((33, 15, 33, 25), fill=CAT_STRIPE, width=2)
    draw.line((38, 17, 41, 25), fill=CAT_STRIPE, width=2)

    if eyes_open:
        draw.ellipse((25, 29, 29, 33), fill=OUTLINE)
        draw.ellipse((38, 29, 42, 33), fill=OUTLINE)
    else:
        draw.line((25, 31, 29, 31), fill=OUTLINE, width=2)
        draw.line((38, 31, 42, 31), fill=OUTLINE, width=2)

    draw.ellipse((28, 33, 39, 45), fill=CAT_MUZZLE)
    draw.polygon((32, 35, 35, 35, 33, 38), fill=OUTLINE)
    draw.arc((28, 37, 34, 44), start=290, end=80, fill=OUTLINE, width=1)
    draw.arc((34, 37, 40, 44), start=100, end=250, fill=OUTLINE, width=1)
    for offset in (-3, 0, 3):
        draw.line((29, 38, 10, 35 + offset), fill=CAT_MUZZLE, width=1)
        draw.line((39, 38, 57, 35 + offset), fill=CAT_MUZZLE, width=1)

    left_paw_y = 48 + paw_offset
    right_paw_y = 48 - paw_offset
    draw.rounded_rectangle((13, 51, 55, 56), radius=2, fill=KEYBOARD, outline=OUTLINE)
    draw.line((18, 54, 50, 54), fill=ACCENT, width=1)
    draw.ellipse((13, left_paw_y - 4, 25, left_paw_y + 5), fill=CAT_FUR, outline=OUTLINE)
    draw.ellipse((43, right_paw_y - 4, 55, right_paw_y + 5), fill=CAT_FUR, outline=OUTLINE)


def _frame(paw_offset: int, eyes_open: bool) -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), BG)
    _base(ImageDraw.Draw(img), paw_offset, eyes_open)
    return img


def _grayscale(img: Image.Image) -> Image.Image:
    gray = img.convert("LA").convert("RGBA")
    # restore alpha mask
    r, g, b, a = img.split()
    gr, gg, gb, _ = gray.split()
    return Image.merge("RGBA", (gr, gg, gb, a))


def _add_pause_badge(img: Image.Image) -> Image.Image:
    out = img.copy()
    d = ImageDraw.Draw(out)
    cx, cy, r = 50, 14, 9
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(220, 60, 60, 255), outline=OUTLINE)
    d.rectangle((cx - 4, cy - 4, cx - 1, cy + 4), fill=(255, 255, 255, 255))
    d.rectangle((cx + 1, cy - 4, cx + 4, cy + 4), fill=(255, 255, 255, 255))
    return out


def working_frames() -> list[Image.Image]:
    """4-frame cat typing cycle with occasional blink."""
    return [
        _frame(paw_offset=0, eyes_open=True),
        _frame(paw_offset=2, eyes_open=True),
        _frame(paw_offset=0, eyes_open=True),
        _frame(paw_offset=2, eyes_open=False),
    ]


def idle_frame() -> Image.Image:
    return _grayscale(_frame(paw_offset=0, eyes_open=False))


def paused_frames() -> list[Image.Image]:
    return [_add_pause_badge(f) for f in working_frames()[:2]]
