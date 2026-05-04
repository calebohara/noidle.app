"""Generate a placeholder 256x256 ICO with a green circle.

Run from repo root: `python scripts/make_icon.py`
Writes to `assets/icon.ico`. Used by the GitHub Actions build when
no committed icon exists. Replace with a real designed icon when ready.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"
SIZE = 256
PADDING = 12
GREEN = (46, 204, 113, 255)
TRANSPARENT = (0, 0, 0, 0)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (SIZE, SIZE), TRANSPARENT)
    draw = ImageDraw.Draw(img)
    draw.ellipse(
        (PADDING, PADDING, SIZE - PADDING, SIZE - PADDING),
        fill=GREEN,
    )
    # Multi-resolution ICO so Windows picks an appropriate size everywhere.
    img.save(
        OUT,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
