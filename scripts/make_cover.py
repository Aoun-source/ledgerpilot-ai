"""Draw the 16:9 cover image for the submission page.

    python scripts/make_cover.py            # -> docs/submission/cover.png (1920x1080)
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "submission" / "cover.png"
W, H = 1920, 1080
INK, PAPER, MUTED, AMBER, GREEN, RED = "#1D2A36", "#F4F1EA", "#BFC9D3", "#E0A458", "#7FD1A3", "#F2A19A"

# Bold and regular sans faces found on most machines; the first one present is used.
BOLD = ["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"]
REGULAR = ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"]


def font(names: list[str], size: int) -> ImageFont.FreeTypeFont:
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def stamp(text: str, color: str, size: int, angle: float) -> Image.Image:
    f = font(BOLD, size)
    left, top, right, bottom = f.getbbox(text)
    pad = size // 3
    img = Image.new("RGBA", (right - left + 2 * pad, bottom - top + 2 * pad), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([3, 3, img.width - 4, img.height - 4], radius=14, outline=color, width=7)
    d.text((pad - left, pad - top), text, font=f, fill=color)
    return img.rotate(angle, expand=True, resample=Image.BICUBIC)


def main() -> None:
    img = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(img)
    d.text((128, 250), "ACCOUNTS-PAYABLE AGENT", font=font(BOLD, 34), fill=AMBER)
    d.text((122, 300), "LedgerPilot AI", font=font(BOLD, 150), fill=PAPER)
    lede = font(REGULAR, 46)
    d.text((128, 500), "Stops wrong and fraudulent supplier payments", font=lede, fill=MUTED)
    d.text((128, 560), "before they go out.", font=lede, fill=MUTED)
    for text, color, x, y, angle in (("READY TO PAY", GREEN, 120, 720, 3), ("ON HOLD", AMBER, 690, 735, -4),
                                     ("PAYMENT BLOCKED", RED, 1085, 715, 3)):
        s = stamp(text, color, 64, angle)
        img.paste(s, (x, y), s)
    d.line([(128, 960), (W - 128, 960)], fill="#3A4856", width=2)
    d.text((128, 985), "Evolus agents  ·  open model on AMD Token Factory  ·  AMD Developer Hackathon: ACT III",
           font=font(REGULAR, 30), fill=MUTED)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, optimize=True)
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
