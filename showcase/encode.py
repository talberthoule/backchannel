# Encodes showcase PNG captures to the WebP assets the site serves.
#
# Usage:  python showcase/encode.py
#         python showcase/encode.py --src DIR --dst DIR
#
# Format follows the spec set in design-review/site-refactor-plan-2026-07-09.md:
# RGB, WebP, quality=80, method=6. ffmpeg, ImageMagick, and cwebp are NOT present
# on the build machine; Pillow is, and is the intended tool.
#
# Crop policy: admin and tool panels drop the left sidebar, because those shots
# are about the panel itself. Post-call shots keep the sidebar, because session
# and group organization is part of what they demonstrate.
#
# This script handles ONLY the scripted captures. The legacy `user-*` assets are
# deliberately skipped: their PNGs are 2558-3838px originals, and the committed
# `.webp` beside them are hand-downscaled display variants (plus separate `-full`
# copies for the lightbox). Re-encoding those originals here would silently
# replace a 120 KB hero with a 388 KB one -- the exact LCP regression that
# design-review/site-refactor-plan-2026-07-09.md flags as P0-1. They are frozen
# assets that cannot be regenerated anyway; leave them alone.
import argparse
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
SIDEBAR_PX = 255  # sidebar occupies x < 255 at a 1440px viewport

SKIP_PREFIXES = ("user-",)

CROP_SIDEBAR = {
    "admin-agents", "admin-transcription", "admin-api-keys", "admin-about",
    "admin-privacy", "admin-privacy-preview",
    "offerings-catalog", "knowledge-sources",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(REPO / "showcase" / "screenshots"))
    ap.add_argument("--dst", default=str(REPO / "site" / "assets" / "shots"))
    args = ap.parse_args()

    src, dst = Path(args.src), Path(args.dst)
    dst.mkdir(parents=True, exist_ok=True)

    rows, skipped = [], []
    for png in sorted(src.glob("*.png")):
        stem = png.stem
        if stem.startswith(SKIP_PREFIXES):
            skipped.append(stem)
            continue
        base = stem[:-5] if stem.endswith("-dark") else stem
        im = Image.open(png).convert("RGB")
        if base in CROP_SIDEBAR:
            im = im.crop((SIDEBAR_PX, 0, im.width, im.height))
        out = dst / f"{stem}.webp"
        im.save(out, "WEBP", quality=80, method=6)
        rows.append((stem, f"{im.width}x{im.height}", out.stat().st_size // 1024))

    if not rows:
        raise SystemExit(f"no PNGs found in {src}")
    w = max(len(r[0]) for r in rows)
    for name, dims, kb in rows:
        print(f"{name.ljust(w)}  {dims.rjust(9)}  {str(kb).rjust(4)} KB")
    print(f"\n{len(rows)} files, {sum(r[2] for r in rows)} KB total -> {dst}")
    if skipped:
        print(f"skipped {len(skipped)} frozen user-* asset(s); see the note at the top of this file")


if __name__ == "__main__":
    main()
