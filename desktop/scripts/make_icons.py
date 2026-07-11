"""Render the Backchannel brand icons used by the desktop bundle.

Reproduces site/assets/favicon.svg (five rounded waveform bars) with
Pillow and writes desktop/assets/icon.png (tray, transparent), icon.ico
(Windows executable), and icon.icns (macOS bundle). Rerun after brand
changes; the outputs are committed so CI builds need no extra tooling.
"""

from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets"

# favicon.svg geometry in its 64x64 viewbox: (x, y, w, h, fill).
TILE_BG = "#0f172a"
TILE_RADIUS = 14
BARS = [
    (10, 26, 7, 18, "#0d9488"),
    (21, 16, 7, 38, "#0d9488"),
    (32, 8, 7, 48, "#2dd4bf"),
    (43, 20, 7, 30, "#0d9488"),
    (52, 28, 7, 14, "#2dd4bf"),
]
BAR_RADIUS = 3.5
# The tray renders at 16-24px, often on a dark background: skip the dark
# tile and brighten the dim bars so the mark stays legible.
TRAY_BRIGHT = {"#0d9488": "#14b8a6"}


def draw_mark(size: int, tile: bool) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    s = size / 64
    if tile:
        draw.rounded_rectangle(
            (0, 0, size - 1, size - 1), radius=TILE_RADIUS * s, fill=TILE_BG
        )
    for x, y, w, h, fill in BARS:
        if not tile:
            fill = TRAY_BRIGHT.get(fill, fill)
        draw.rounded_rectangle(
            (x * s, y * s, (x + w) * s, (y + h) * s),
            radius=BAR_RADIUS * s,
            fill=fill,
        )
    return image


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)

    tray = draw_mark(256, tile=False)
    tray.save(ASSETS / "icon.png")

    tile = draw_mark(256, tile=True)
    tile.save(
        ASSETS / "icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)],
    )

    draw_mark(1024, tile=True).save(ASSETS / "icon.icns")

    for name in ("icon.png", "icon.ico", "icon.icns"):
        with Image.open(ASSETS / name) as check:
            check.load()
            print(f"{name}: {check.format} {check.size}")


if __name__ == "__main__":
    main()
