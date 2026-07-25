# Derives focused crops from the full-surface captures.
#
# These are not separate screenshots: cropping a captured surface keeps the
# pixels honest while letting a feature block show one thing instead of a whole
# screen. Boxes are in the 1440x900 capture coordinate space.
import sys
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "showcase" / "screenshots"
DST = REPO / "site" / "assets" / "shots"

# name -> (source stem, box)
CROPS = {
    # Post-call header: call segments, total duration, insight count.
    "session-header": ("postcall-insights", (336, 84, 1368, 250)),
    # The answered objection card with its ready-to-use suggested response.
    "live-answered": ("live-call", (288, 292, 1020, 800)),
    # Insight cards carrying speaker attribution badges.
    "insights-attributed": ("postcall-insights", (336, 440, 1368, 900)),
}


def main():
    made = []
    for name, (stem, box) in CROPS.items():
        for suffix in ("", "-dark"):
            src = SRC / f"{stem}{suffix}.png"
            if not src.exists():
                print(f"skip {name}{suffix}: missing {src.name}")
                continue
            im = Image.open(src).convert("RGB").crop(box)
            out = DST / f"{name}{suffix}.webp"
            im.save(out, "WEBP", quality=80, method=6)
            made.append((f"{name}{suffix}", f"{im.width}x{im.height}", out.stat().st_size // 1024))
    w = max(len(m[0]) for m in made)
    for n, d, kb in made:
        print(f"{n.ljust(w)}  {d.rjust(9)}  {str(kb).rjust(3)} KB")


if __name__ == "__main__":
    main()
