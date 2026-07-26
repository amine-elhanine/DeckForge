"""Generate the application icon.

Drawing it here keeps the repository free of binary assets that nobody can
diff, and means the icon regenerates from source on every platform.

    python packaging/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent / "assets"
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)

BACKDROP = (24, 30, 44, 255)
SHEET_TOP = (86, 141, 255, 255)
SHEET_MID = (61, 110, 214, 255)
SHEET_LOW = (41, 78, 158, 255)


def draw(size: int) -> Image.Image:
    """A stack of three slides, drawn at ``size`` pixels."""
    scale = 8  # supersample, then downscale for clean edges
    canvas = size * scale
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    radius = canvas * 0.22
    draw.rounded_rectangle([(0, 0), (canvas - 1, canvas - 1)], radius=radius, fill=BACKDROP)

    # Three offset sheets suggesting a deck rather than a single slide.
    width, height = canvas * 0.52, canvas * 0.30
    left = (canvas - width) / 2
    sheet_radius = canvas * 0.04
    for index, colour in enumerate((SHEET_LOW, SHEET_MID, SHEET_TOP)):
        offset = canvas * (0.30 + index * 0.12)
        inset = canvas * 0.045 * (2 - index)
        draw.rounded_rectangle(
            [(left + inset, offset), (left + width - inset, offset + height)],
            radius=sheet_radius,
            fill=colour,
        )

    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    frames = [draw(size) for size in SIZES]

    frames[-1].save(OUT / "icon.png")
    # Windows .ico carries every size in one file.
    frames[-1].save(OUT / "icon.ico", sizes=[(s, s) for s in SIZES])
    # macOS iconutil consumes an .iconset directory; emit the PNGs it expects.
    iconset = OUT / "DeckForge.iconset"
    iconset.mkdir(exist_ok=True)
    for size, frame in zip(SIZES, frames, strict=True):
        if size >= 16:
            frame.save(iconset / f"icon_{size}x{size}.png")
    print(f"wrote {OUT / 'icon.ico'}, {OUT / 'icon.png'} and {iconset.name}/")


if __name__ == "__main__":
    main()
