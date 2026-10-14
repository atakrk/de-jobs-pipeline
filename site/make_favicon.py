"""Draw docs/favicon.ico: the DE plate from favicon.svg, as pixels.

For clients that request /favicon.ico directly. Run by hand when the mark
changes, together with favicon.svg.

Usage:
    python site/make_favicon.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs" / "favicon.ico"
FONT = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSansMono-Bold.ttf"

SIZES = [16, 32, 48]
# Drawn large and reduced, so the small sizes come out antialiased.
CANVAS = 256

INK = "#0b0b0b"
PAPER = "#fcfcfb"
# Flag stripes, same values as favicon.svg (grey instead of black).
STRIPES = ["#5c5c58", "#dd0000", "#ffce00"]


def draw() -> Image.Image:
    unit = CANVAS / 64
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    pen.rounded_rectangle([0, 0, CANVAS - 1, CANVAS - 1], radius=10 * unit, fill=INK)
    font = ImageFont.truetype(str(FONT), round(29 * unit))
    # (32, 40) is the SVG's text-anchor middle on the baseline.
    pen.text((32 * unit, 40 * unit), "DE", font=font, fill=PAPER, anchor="ms")
    for i, colour in enumerate(STRIPES):
        left = 11 + 14 * i
        pen.rectangle([left * unit, 49 * unit, (left + 14) * unit, 53 * unit], fill=colour)
    return image


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    draw().save(OUTPUT, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"{OUTPUT.relative_to(ROOT)}: {', '.join(f'{s}px' for s in SIZES)}")


if __name__ == "__main__":
    main()
