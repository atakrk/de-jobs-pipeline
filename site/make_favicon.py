"""Draw docs/favicon.ico: the DE plate from favicon.svg, as pixels.

favicon.svg is what a client that reads the page's <link rel="icon"> gets.
Plenty do not read the page first -- they ask for /favicon.ico by convention,
and were answered with GitHub's 404. This draws the same plate on the same
64-unit grid, at the sizes an .ico carries, in the monospace face matplotlib
ships, so it needs nothing the pipeline does not already install.

It holds no data, so nothing runs it on a schedule. Run it by hand when the
mark changes, and change favicon.svg with it.

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
# Schwarz-Rot-Gold, with the dark theme's black so the first stripe shows on
# the plate. The same three values as favicon.svg.
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
